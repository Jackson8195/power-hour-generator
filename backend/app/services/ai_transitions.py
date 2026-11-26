"""AI-created transition clips: several varied changeovers the renderer cycles through.

The AI plans a set of transitions for a playlist theme. Every transition reads like a real
power hour changeover: a small 3·2·1 countdown in the corner, then either

* an **animated card** (rendered locally, see ``transition_fx``): the AI's headline slides in
  with its one-liner under it, then a flash + shake + "DRINK!"-style call word on a generated
  recorded drink cue (beer can, clink, pop, ...), or
* a **video clip**: a short, punchy moment from a themed YouTube video (picked with the audio
  highlight analysis), followed by a freeze-frame call word and the drink cue.

With ``sources == "both"`` the kinds alternate (video, card, video, ...) so the result is a
real mix rather than whatever the AI felt like. A YouTube pick never reuses a video that is
already in the playlist (or another transition), skips results that look like one of the
playlist's songs, and falls back to an animated card with a logged reason when nothing works.

Everything the AI returns is treated as untrusted: text is length-limited and stripped, colors
come from a fixed palette, sounds and call words from fixed lists, and text reaches ffmpeg only
via files (see ``build_text_card``).
"""

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.schemas import ChangoverClipDB, ClipDB
from app.services.changeover import render_resolution
from app.services.ffmpeg import build_text_card
from app.services.transition_fx import (
    CARD_SECONDS,
    HIT_WORDS,
    DEFAULT_SOUND,
    SOUNDS,
    MAX_VIDEO_CLIP_SECONDS,
    MIN_TRIM_SECONDS,
    VIDEO_CLIP_SECONDS,
    VIDEO_TAIL_SECONDS,
    available_sounds,
    build_art_card,
    build_video_transition,
    pick_bundled_art,
    probe_duration,
)
from app.services.youtube import _meaningful_terms, _normalize_text, download_video, search_youtube

logger = logging.getLogger(__name__)

# Named colors the AI may choose from, mapped to hex so it can never inject arbitrary values.
PALETTE = {
    "yellow": "#FFE600", "pink": "#FF4FA3", "cyan": "#1AFFE4", "green": "#39FF14",
    "orange": "#FF8A00", "red": "#FF2D2D", "white": "#FFFFFF", "purple": "#B266FF",
    "black": "#000000", "navy": "#0B1030", "maroon": "#2B0A12", "forest": "#06210F",
}
DARK_BACKGROUNDS = ("black", "navy", "maroon", "forest")
MAX_COUNT = 8
SHORT_SOURCE_SECONDS = 90  # preferred: short clips/memes download fast and are mostly "moment"
MAX_SOURCE_SECONDS = 600  # never download anything longer for a 5 second transition
YOUTUBE_CANDIDATES = 3  # results tried (download/build) per search before the next search
REVIEW_POOL = 8  # usable results sent to the AI review per search
QUERY_CHARS = 80
# Talk moments: the transition's 4s should land on a line, not on applause or a music bed.
MOMENT_MUSIC_LIKENESS = 0.0
FALLBACK_HEADLINE = "SHOT!"
ART_PROMPT_CHARS = 400
STYLE_CHARS = 300
DRINK_TEXT_CHARS = 24  # the user's own call word ("DRINK!", "SHOTS FOR TABLE 4", ...)
ART_CONCURRENCY = 3  # image generations in flight at once (~25s each)
# Always appended to the AI's art description: the app draws its own text, and the image
# model should not try to depict real people.
ART_RULES = (
    " Bold party-poster illustration, cinematic lighting, high contrast, subject centered with room "
    "around it, 16:9 landscape. Absolutely no text, letters, numbers, logos or watermarks. "
    "No real people's faces or likenesses."
)

# Words that say nothing about which song a video is (ignored when matching playlist titles).
_TITLE_NOISE = {
    "official", "video", "music", "audio", "lyrics", "lyric", "hd", "hq", "4k", "live", "the",
    "and", "feat", "ft", "with", "remastered", "remaster", "version", "performance", "full",
}


@dataclass
class TransitionSpec:
    kind: str  # "card" | "youtube"
    label: str
    headline: str = FALLBACK_HEADLINE
    subline: str = ""
    text_color: str = PALETTE["yellow"]
    bg_color: str = PALETTE["black"]
    hit_text: str = "DRINK!"
    sound: str = DEFAULT_SOUND
    duration: float = CARD_SECONDS
    query: str = ""
    fallback_query: str = ""  # a broader search for the same idea, tried when ``query`` finds nothing
    context: str = ""  # power hour prompt + transition direction, for the result review
    art_prompt: str = ""  # what the AI wants illustrated (sent to the image model, never ffmpeg)
    art_path: str = ""    # set once art is generated (or a bundled drink image is chosen)
    # Set by a video build: the kept full source (for re-trimming), the used range in it, and
    # the source's waveform so the review screen can show the whole video.
    source_path: str = ""
    trim_start: float = 0.0
    trim_end: float = 0.0
    waveform: list | None = None
    source_seconds: float = 0.0


def _clean_text(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return " ".join(text.split())[:limit].strip()


def clean_drink_text(value: object) -> str:
    """The user's call word: one line, no control characters, short. Empty means no text.
    (It reaches ffmpeg only through a text file, like every other transition text.)"""
    return _clean_text(value, DRINK_TEXT_CHARS)


def _pick(value: object, allowed: tuple[str, ...]) -> str | None:
    """Match ``value`` against a fixed list, ignoring case and punctuation."""
    wanted = re.sub(r"[^a-z]", "", str(value or "").lower())
    for option in allowed:
        if wanted and wanted == re.sub(r"[^a-z]", "", option.lower()):
            return option
    return None


def sanitize_spec(raw: dict, sources: str, index: int = 0) -> TransitionSpec | None:
    """Turn one AI-proposed transition into a safe spec, or None if unusable.

    ``index`` rotates the default sound / call word so unset fields still vary.
    """
    kind = "youtube" if str(raw.get("kind", "")).strip().lower() == "youtube" else "card"
    if sources == "cards":
        kind = "card"
    elif sources == "youtube":
        kind = "youtube"

    headline = (
        _clean_text(raw.get("headline"), 18) or _clean_text(raw.get("label"), 18) or FALLBACK_HEADLINE
    )
    query = _clean_text(raw.get("query"), QUERY_CHARS)
    label = _clean_text(raw.get("label"), 60) or headline
    if not query and kind == "youtube":
        query = label  # a youtube transition needs something to search for

    text_name = str(raw.get("text_color", "")).strip().lower()
    bg_name = str(raw.get("bg_color", "")).strip().lower()
    text_color = PALETTE.get(text_name, PALETTE["yellow"])
    bg_color = PALETTE.get(bg_name, PALETTE["black"])
    if text_color == bg_color:
        bg_color = PALETTE["black"] if text_color != PALETTE["black"] else PALETTE["white"]

    return TransitionSpec(
        kind=kind,
        label=label,
        headline=headline,
        subline=_clean_text(raw.get("subline"), 40),
        text_color=text_color,
        bg_color=bg_color,
        hit_text=_pick(raw.get("hit_text"), HIT_WORDS) or HIT_WORDS[index % 3],
        sound=_pick(raw.get("sound"), available_sounds()) or (available_sounds() or SOUNDS)[index % len(available_sounds() or SOUNDS)],
        duration=VIDEO_CLIP_SECONDS if kind == "youtube" else CARD_SECONDS,
        query=query,
        fallback_query=_clean_text(raw.get("fallback_query"), QUERY_CHARS),
        art_prompt=_clean_text(raw.get("art_prompt"), ART_PROMPT_CHARS),
    )


def assign_kinds(specs: list[TransitionSpec], sources: str) -> list[TransitionSpec]:
    """For ``both``, alternate video / card (video first) so the user actually gets a mix.

    The AI is asked for both a card and a search query on every item, so any slot can be
    either kind; a slot without a usable query searches for its label.
    """
    if sources != "both":
        return specs
    for index, spec in enumerate(specs):
        spec.kind = "youtube" if index % 2 == 0 else "card"
        if spec.kind == "youtube" and not spec.query:
            spec.query = spec.label
        spec.duration = VIDEO_CLIP_SECONDS if spec.kind == "youtube" else CARD_SECONDS
    return specs


def sanitize_specs(raw_items: object, count: int, sources: str) -> list[TransitionSpec]:
    """Sanitize, drop duplicates, cap at ``count`` (and MAX_COUNT), and settle the mix."""
    limit = max(0, min(count, MAX_COUNT))
    specs: list[TransitionSpec] = []
    seen: set[str] = set()
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        spec = sanitize_spec(raw, sources, len(specs))
        if not spec:
            continue
        # Art cards have no headline of their own (it falls back to the label), so cards are
        # told apart by label and art too; otherwise every headline-less card looks the same.
        if sources == "youtube":
            key = spec.query.lower()
        elif sources == "cards":
            key = f"{spec.headline}|{spec.label}|{spec.art_prompt}".lower()
        else:
            key = f"{spec.headline}|{spec.label}|{spec.query}".lower()
        if key in seen:
            continue
        seen.add(key)
        specs.append(spec)
        if len(specs) >= limit:
            break
    return assign_kinds(specs, sources)


def _fallback_specs(count: int, sources: str) -> list[TransitionSpec]:
    """Used when planning fails: a few distinct generated cards so the cycle still varies."""
    variants = [
        {"headline": "GET READY", "hit_text": "SHOT!", "sound": "can", "text_color": "yellow", "bg_color": "black"},
        {"headline": "NEXT SONG", "hit_text": "DRINK!", "sound": "clink", "text_color": "pink", "bg_color": "navy"},
        {"headline": "LAST CALL", "hit_text": "CHEERS!", "sound": "cheer", "text_color": "cyan", "bg_color": "maroon"},
        {"headline": "NO MERCY", "hit_text": "BOTTOMS UP!", "sound": "pop", "text_color": "green", "bg_color": "black"},
    ]
    return sanitize_specs(variants, count, "cards")


async def plan_transitions(
    theme: str,
    count: int,
    sources: str,
    avoid_titles: list[str] | None = None,
    transition_prompt: str = "",
    avoid_labels: list[str] | None = None,
) -> list[TransitionSpec]:
    """Ask the AI for ``count`` varied transitions that fit the power hour.

    ``theme`` is the power hour's own prompt; ``transition_prompt`` is the user's direction
    for the transitions themselves; ``avoid_labels`` are transitions already in the set (so
    a regenerated one comes out different)."""
    from app.services.auto_generate import _get_openai_client  # lazy: avoids an import cycle

    count = max(1, min(count, MAX_COUNT))
    if sources == "cards":
        mix = 'Every transition must have kind "card".'
    elif sources == "youtube":
        mix = 'Every transition must have kind "youtube".'
    else:
        mix = (
            "Fill in BOTH art_prompt and query for every transition: the app alternates video "
            "clips and art cards and uses the art card if a video can't be found."
        )
    avoid = ""
    if avoid_titles:
        listed = "; ".join(_clean_text(t, 80) for t in avoid_titles[:40])
        avoid = f" These songs are already in the playlist, never search for them or their performances: {listed}."
    already = ""
    if avoid_labels:
        listed = "; ".join(_clean_text(t, 60) for t in avoid_labels[:MAX_COUNT * 2])
        already = f"\nThe set already has these transitions, so make yours clearly different: {listed}."
    direction = _clean_text(transition_prompt, 600)
    user_content = f"Power hour prompt: {theme}\n"
    if direction:
        user_content += f"Direction for the transitions: {direction}\n"
    user_content += f"Create {count} different transitions.{already}"

    client = _get_openai_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You design the changeovers that play between songs in a drinking-game 'power hour' "
                    "video. Each one shows a small 3-2-1 countdown in the corner and ends on a big call "
                    "word (like DRINK!) with a sound cue telling everyone to drink. A transition is either "
                    "an art card (a full-screen illustration with the call word) or a short funny video "
                    "moment that ends with the call word over its last frame (no illustration). "
                    'Return only strict JSON shaped as {"style": string, "transitions": [{"kind": "card" | '
                    '"youtube", "label": string, "art_prompt": string, "hit_text": string, "sound": string, '
                    '"text_color": string, "query": string, "fallback_query": string}]}. '
                    "style: one shared art direction for the whole set (palette, era, rendering style) so the "
                    "hour looks designed. "
                    "art_prompt: a vivid description of one illustration that always features a drink (a shot "
                    "glass, beer mug or bottles, cocktails, a toast) and ties it to the theme through objects, "
                    "settings, props and colors, e.g. a shot glass on a judges' desk beside a golden "
                    "microphone under stage lights. Never describe text or signs, and never real people. "
                    "label: 2-5 words naming the transition. "
                    f"hit_text: one of {', '.join(HIT_WORDS)}. sound: one of {', '.join(available_sounds())}. "
                    f"text_color (for the call word): one of {', '.join(c for c in PALETTE if c not in DARK_BACKGROUNDS)}. "
                    "query: a SHORT YouTube search (3-6 words) for a short, recognizable, safe-for-work "
                    "NON-MUSIC moment that fits the theme (a reaction, catchphrase, blooper, famous quote, "
                    "insult, meme or sound effect). Write it the way people title uploads: the person and "
                    "the show plus the kind of moment, e.g. 'Simon Cowell harsh comments American Idol'. "
                    "No season or episode numbers, years, quoted lines or long descriptions: over-specific "
                    "searches find nothing. Keep every query on the exact show/franchise the theme names. "
                    "fallback_query: a broader 2-4 word search for the same idea, e.g. "
                    "'Simon Cowell insults'. "
                    "Never a song, music video or musical performance." + avoid + " " + mix
                ),
            },
            {"role": "user", "content": user_content},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    specs = sanitize_specs(payload.get("transitions"), count, sources)
    style = _clean_text(payload.get("style"), STYLE_CHARS)
    context = f"Power hour: {_clean_text(theme, 400)}"
    if direction:
        context += f" | Transitions: {direction}"
    for spec in specs:
        spec.context = context
        if spec.art_prompt and style:
            spec.art_prompt = f"{style}. {spec.art_prompt}"
    return specs


async def generate_art(prompt: str, output_path: str) -> bool:
    """Render one illustration with the OpenAI image model. Returns False on any failure
    (no key, model refused, network), and the caller falls back to bundled drink art."""
    if not prompt or not settings.openai_api_key or not settings.openai_image_model:
        return False
    from app.services.auto_generate import _get_openai_client

    try:
        client = _get_openai_client()
        result = await client.images.generate(
            model=settings.openai_image_model,
            prompt=prompt + ART_RULES,
            size="1536x1024",
            quality=settings.openai_image_quality,
            n=1,
        )
        data = result.data[0]
        if getattr(data, "b64_json", None):
            raw = base64.b64decode(data.b64_json)
        else:  # pragma: no cover - URL responses are only used by older image models
            import httpx

            async with httpx.AsyncClient(timeout=60) as http:
                raw = (await http.get(data.url)).content
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(raw)
        return True
    except Exception as exc:
        logger.warning("AI transition art failed (%s); using bundled drink art", exc)
        return False


async def _attach_art(specs: list[TransitionSpec], stems: list[str]) -> None:
    """Give every spec an image: AI art when it can be generated, else bundled drink art.
    Generations run a few at a time."""
    limit = asyncio.Semaphore(ART_CONCURRENCY)

    async def one(index: int, spec: TransitionSpec, stem: str) -> None:
        path = str(settings.changeover_dir / f"{stem}_art.png")
        async with limit:
            ok = await generate_art(spec.art_prompt, path)
        if ok:
            spec.art_path = path
        else:
            fallback = pick_bundled_art(index)
            spec.art_path = str(fallback) if fallback else ""

    await asyncio.gather(*(one(i, s, stem) for i, (s, stem) in enumerate(zip(specs, stems))))


def _duration_seconds(label: str) -> int | None:
    """Parse '3:45' / '1:02:03' (as produced by the search layer) into seconds."""
    if not label:
        return None
    parts = label.strip().split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    seconds = 0
    for n in nums:
        seconds = seconds * 60 + n
    return seconds


def _title_words(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (title or "").lower())
    return {w for w in words if len(w) > 1 and w not in _TITLE_NOISE}


def _looks_like_playlist_song(title: str, playlist_titles: list[str]) -> bool:
    """True when a result title contains (nearly) all the words of a playlist song's title,
    e.g. another upload of a song that is already in the power hour."""
    words = _title_words(title)
    if not words:
        return False
    for song in playlist_titles:
        song_words = _title_words(song)
        if len(song_words) >= 2 and len(song_words & words) / len(song_words) >= 0.75:
            return True
    return False


def _relevance(result, query: str) -> float:
    """Share of the search's meaningful words found in the result's title + channel."""
    terms = _meaningful_terms(query)
    if not terms:
        return 1.0
    haystack = f" {_normalize_text(result.title)} {_normalize_text(getattr(result, 'artist', '') or '')} "
    return sum(1 for term in terms if f" {term} " in haystack) / len(terms)


_SPECIFIC_WORDS = re.compile(
    r"\b(?:season|series|episode|ep|s\d+|e\d+|week|round|part|spoken|audition(?:s)?\s+day)\b|\b\d+\b",
    re.IGNORECASE,
)


def broaden_query(query: str, words: int = 4) -> str:
    """A shorter search for the same idea: drop season/episode numbers, years and filler,
    keep the first few words (they name the person and the show)."""
    cleaned = " ".join(_SPECIFIC_WORDS.sub(" ", query or "").split())
    return " ".join(cleaned.split()[:words])


def search_plan(spec: TransitionSpec) -> list[str]:
    """The searches tried in order for a video transition: the planner's query, its broader
    fallback, then an automatically shortened query; no repeats."""
    seen: list[str] = []
    for query in (spec.query, spec.fallback_query, broaden_query(spec.query), spec.label):
        query = (query or "").strip()
        if query and query.lower() not in (q.lower() for q in seen):
            seen.append(query)
    return seen[:3]


def choose_youtube_candidates(
    results: list, exclude_ids: set[str], playlist_titles: list[str], query: str = "",
    limit: int = YOUTUBE_CANDIDATES,
) -> list:
    """Order usable search results for a transition: never a video already in the playlist
    (or used by another transition), never something that looks like a playlist song,
    nothing too long to download. Most relevant to ``query`` first (title words), then short
    videos before longer ones, then the search's own order."""
    usable = []
    for result in results:
        if not result.youtube_id or result.youtube_id in exclude_ids:
            continue
        if _looks_like_playlist_song(result.title, playlist_titles):
            continue
        seconds = _duration_seconds(result.duration)
        if seconds is not None and seconds > MAX_SOURCE_SECONDS:
            continue
        usable.append(result)

    def rank(pair):
        position, result = pair
        relevance = round(_relevance(result, query), 2) if query else 1.0
        short = (_duration_seconds(result.duration) or 10**6) <= SHORT_SOURCE_SECONDS
        return (-relevance, not short, position)

    return [result for _, result in sorted(enumerate(usable), key=rank)][:limit]


TRANSITION_REVIEW_PROMPT = (
    "You check YouTube search results for a drinking-game power hour TRANSITION: a few seconds of a "
    "funny, recognizable, non-music moment that plays between songs. You get the power hour's theme "
    "and the user's direction for the transitions, the moment wanted, and numbered results with their "
    "real title, channel and length. Reject a result when its title or channel shows it does not fit: "
    "a different show, franchise or competition than the one named (even with shared judges or hosts, "
    "e.g. Got Talent or X Factor for American Idol), a person, era or season outside what is asked, a "
    "song, music video or full musical performance, news, interviews, podcasts, reaction or commentary "
    "videos about the moment instead of the moment itself (unless asked for), or anything unrelated. "
    "Do not reject only because a detail is missing from the title; reject on evidence. "
    'Return only strict JSON shaped as {"reject": [numbers]} (an empty list when all fit).'
)


async def review_transition_results(spec: TransitionSpec, results: list) -> list:
    """Drop the results the AI says don't fit the theme/direction. Fails open: any error keeps
    every result, so a flaky review never blocks a transition."""
    if not results:
        return results
    listing = "\n".join(
        f"{n}. {r.title} | channel: {getattr(r, 'artist', '') or '?'} | length: {r.duration or '?'}"
        for n, r in enumerate(results, start=1)
    )
    wanted = f"{spec.label} (search: {spec.query})"
    try:
        from app.services.auto_generate import _get_openai_client  # lazy: avoids an import cycle

        client = _get_openai_client()
        response = await client.chat.completions.create(
            model=settings.openai_review_model or settings.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": TRANSITION_REVIEW_PROMPT},
                {"role": "user", "content": f"{spec.context or 'Power hour'}\nMoment wanted: {wanted}\n\nResults:\n{listing}"},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        raw = payload.get("reject", []) if isinstance(payload, dict) else []
    except Exception as exc:
        logger.info("Transition result review unavailable; keeping %d results: %s", len(results), exc)
        return results
    rejected = set()
    for number in raw if isinstance(raw, list) else []:
        try:
            index = int(number) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(results):
            rejected.add(index)
    if rejected:
        logger.info(
            "Transition review rejected %d of %d for %r: %s",
            len(rejected), len(results), spec.query, [results[i].title for i in sorted(rejected)],
        )
    return [r for i, r in enumerate(results) if i not in rejected]


async def _pick_moment(path: str, source_seconds: float, clip_seconds: float) -> tuple[float, list, float]:
    """``(start, waveform, source_seconds)``: the start of the punchiest ``clip_seconds`` of the
    source via the highlight analysis (snaps to content changes in non-music video), plus the
    waveform for the review screen. Falls back to a quarter of the way in, with no waveform."""
    start = None
    waveform: list = []
    try:
        from app.services.audio_analysis import analyze_audio

        analysis = await analyze_audio(
            path, clip_duration=max(1, round(clip_seconds)), music_likeness=MOMENT_MUSIC_LIKENESS
        )
        if analysis.get("duration"):
            source_seconds = float(analysis["duration"])
            start = float(analysis.get("suggested_start") or 0.0)
            waveform = list(analysis.get("waveform") or [])
    except Exception as exc:  # librosa missing or analysis failed
        logger.info("Transition moment analysis unavailable for %s: %s", path, exc)
    if start is None:
        start = source_seconds * 0.25 if source_seconds > clip_seconds * 3 else 0.0
    return max(0.0, min(start, max(0.0, source_seconds - clip_seconds))), waveform, source_seconds


async def _build_card(spec: TransitionSpec, output_path: str, resolution: str) -> float:
    """An art card (the spec's AI or bundled drink art + corner countdown + call word + cue).
    Falls back to the animated text card only when there is no art at all."""
    if spec.art_path and Path(spec.art_path).is_file():
        return await build_art_card(
            output_path,
            spec.art_path,
            text_color=spec.text_color,
            duration=CARD_SECONDS,
            resolution=resolution,
            hit_text=spec.hit_text,
            sound=spec.sound,
        )
    return await build_text_card(
        output_path,
        headline=spec.headline,
        subline=spec.subline,
        text_color=spec.text_color,
        bg_color=spec.bg_color,
        duration=CARD_SECONDS,
        resolution=resolution,
        hit_text=spec.hit_text,
        sound=spec.sound,
    )


async def _build_youtube(
    spec: TransitionSpec,
    project_id: int,
    index: int,
    output_path: str,
    resolution: str,
    exclude_ids: set[str],
    playlist_titles: list[str],
) -> tuple[str, float]:
    """Find, download and cut a punchy moment, then end it on the call word.

    Tries the planner's query, then broader searches (``search_plan``). Each search's usable
    results are ranked by relevance and checked by the AI review against the theme and the
    user's direction before anything is downloaded.
    Returns ``(youtube_id, length)``. Raises with the reason when nothing usable was found.
    """
    errors: list[str] = []
    tried: set[str] = set()
    for query in search_plan(spec):
        results = await search_youtube(query, max_results=10, music=False)
        pool = choose_youtube_candidates(
            results, exclude_ids | tried, playlist_titles, query=query, limit=REVIEW_POOL
        )
        if not pool:
            errors.append(f"{query!r}: no usable results ({len(results)} found)")
            continue
        kept = await review_transition_results(spec, pool)
        if not kept:
            errors.append(f"{query!r}: all {len(pool)} results off-topic")
            continue
        for candidate in kept[:YOUTUBE_CANDIDATES]:
            tried.add(candidate.youtube_id)
            built = await _try_candidate(spec, project_id, index, output_path, resolution, candidate, errors)
            if built is not None:
                if query != spec.query:
                    logger.info("AI transition %s: found via broader search %r", index, query)
                return built
    raise RuntimeError("; ".join(errors)[:500] or "no usable results")


async def _try_candidate(
    spec: TransitionSpec, project_id: int, index: int, output_path: str, resolution: str,
    candidate, errors: list[str],
) -> tuple[str, float] | None:
    """Download one result and build the transition from it; None (reason appended) on failure."""
    raw_stem = f"project_{project_id}_ai_{index}_{uuid4().hex[:6]}_raw"
    raw_path: Path | None = None
    kept: Path | None = None
    try:
        info = await download_video(
            candidate.youtube_id, output_dir=settings.changeover_dir, file_stem=raw_stem
        )
        raw_path = Path(info["file_path"])
        source_seconds = float(info.get("duration") or 0.0)
        start, waveform, source_seconds = await _pick_moment(str(raw_path), source_seconds, VIDEO_CLIP_SECONDS)
        # Keep the WHOLE download beside the transition so the user can watch all of it and
        # re-trim to any part. It is deleted when the power hour is rendered (or trashed).
        kept = Path(output_path).with_name(Path(output_path).stem + "_src" + raw_path.suffix)
        raw_path.replace(kept)
        raw_path = None
        spec.source_path, spec.waveform, spec.source_seconds = str(kept), waveform, source_seconds
        clip_seconds = VIDEO_CLIP_SECONDS
        if source_seconds:
            clip_seconds = max(MIN_TRIM_SECONDS, min(VIDEO_CLIP_SECONDS, source_seconds - start))
        length = await _render_moment(spec, output_path, str(kept), start, clip_seconds, resolution)
        spec.trim_start, spec.trim_end = round(start, 2), round(start + clip_seconds, 2)
        logger.info(
            "AI transition %s: using %s (%r) from %.1fs", index, candidate.youtube_id, candidate.title, start
        )
        return candidate.youtube_id, length
    except Exception as exc:
        errors.append(f"{candidate.youtube_id}: {exc}")
        if kept is not None:
            kept.unlink(missing_ok=True)
        spec.source_path, spec.waveform, spec.source_seconds = "", None, 0.0
    finally:
        if raw_path is not None:
            raw_path.unlink(missing_ok=True)
        for stray in settings.changeover_dir.glob(f"{raw_stem}*"):
            stray.unlink(missing_ok=True)
    return None


async def _render_moment(
    spec: TransitionSpec, output_path: str, source: str, start: float, clip_seconds: float, resolution: str
) -> float:
    """The clip from ``start`` with the corner countdown, ending on the user's call word over
    the video's last frame (no art card). Empty text: just the clip, the held frame and the cue."""
    return await build_video_transition(
        output_path, source, start=start, clip_seconds=clip_seconds, resolution=resolution,
        text_color=spec.text_color, hit_text=spec.hit_text, sound=spec.sound,
    )


def _style_json(spec: TransitionSpec) -> str:
    style = {"text_color": spec.text_color, "hit_text": spec.hit_text, "sound": spec.sound}
    if spec.source_path:
        style["waveform"] = [round(float(v), 4) for v in (spec.waveform or [])][:400]
        style["source_seconds"] = round(float(spec.source_seconds or 0.0), 2)
    return json.dumps(style)


def _style(row: ChangoverClipDB) -> dict:
    try:
        style = json.loads(row.style or "{}")
    except ValueError:
        return {}
    return style if isinstance(style, dict) else {}


def _spec_from_row(row: ChangoverClipDB) -> TransitionSpec:
    """Rebuild what a re-trim / new text needs (art, color, call word, cue, waveform) from a row."""
    style = _style(row)
    color = str(style.get("text_color") or "")
    is_video = row.source_type == "ai_youtube"
    return TransitionSpec(
        kind="youtube" if is_video else "card",
        label=row.label or "Transition",
        text_color=color if color in PALETTE.values() else PALETTE["yellow"],
        hit_text=clean_drink_text(style["hit_text"]) if "hit_text" in style else "DRINK!",
        sound=_pick(style.get("sound"), available_sounds()) or DEFAULT_SOUND,
        art_path=row.image_path or "",
        source_path=row.raw_video_path or "",
        trim_start=row.trim_start or 0.0,
        trim_end=row.trim_end or 0.0,
        waveform=list(style.get("waveform") or []),
        source_seconds=float(style.get("source_seconds") or 0.0),
    )


async def _playlist(db: AsyncSession, project_id: int) -> tuple[set[str], list[str]]:
    rows = await db.execute(
        select(ClipDB.youtube_id, ClipDB.source_title).where(ClipDB.project_id == project_id)
    )
    ids: set[str] = set()
    titles: list[str] = []
    for youtube_id, title in rows.all():
        if youtube_id:
            ids.add(youtube_id)
        if title:
            titles.append(title)
    return ids, titles


# ─── review state (what the transition review screen polls) ─────────────────────

_review: dict[int, dict] = {}


def review_state(project_id: int) -> dict:
    """``{"state": "idle" | "planning" | "building", "error": str}`` for a project."""
    return dict(_review.get(project_id, {"state": "idle", "error": ""}))


def _set_review(project_id: int, state: str, error: str = "") -> None:
    _review[project_id] = {"state": state, "error": error}


def _new_stem(project_id: int) -> str:
    # A fresh name per build, so a regenerated transition never serves a cached old file.
    return f"project_{project_id}_ai_{uuid4().hex[:10]}"


def _remove_owned_file(path: str) -> None:
    """Delete a transition's file only when it lives in the changeover folder (never the
    bundled art shipped with the app)."""
    if not path:
        return
    try:
        file = Path(path).resolve()
        if file.parent == settings.changeover_dir.resolve():
            file.unlink(missing_ok=True)
    except OSError:
        pass


async def _build_one(
    spec: TransitionSpec,
    project_id: int,
    index: int,
    stem: str,
    resolution: str,
    used_ids: set[str],
    playlist_titles: list[str],
    card_fallback: bool = True,
) -> tuple[str, str, str, float]:
    """Build one transition. Returns ``(source_type, youtube_id, output_path, length)``.

    A video slot that can't find a usable clip falls back to an art card (logged with the
    reason) only when ``card_fallback`` is on (the cards + videos mix); otherwise it raises
    so the slot shows the reason and can be regenerated."""
    output_path = str(settings.changeover_dir / f"{stem}.mp4")
    if spec.kind == "youtube":
        try:
            youtube_id, length = await _build_youtube(
                spec, project_id, index, output_path, resolution, used_ids, playlist_titles
            )
            return "ai_youtube", youtube_id, output_path, length
        except Exception as exc:
            if not card_fallback:
                raise RuntimeError(f"No usable video found for {spec.query!r}: {exc}"[:500]) from exc
            logger.warning(
                "AI transition %s for project %s: YouTube clip for %r failed (%s); "
                "falling back to an art card",
                index + 1, project_id, spec.query, exc,
            )
    length = await _build_card(spec, output_path, resolution)
    return "ai_card", "", output_path, length


async def create_ai_transitions(
    db: AsyncSession,
    project_id: int,
    theme: str,
    count: int,
    sources: str = "both",
    resolution: str | None = None,
    transition_prompt: str = "",
    drink_text: str | None = None,
) -> int:
    """Plan and build the project's AI transitions. ``drink_text`` (when given, even empty)
    replaces the AI's call word on every transition. Returns how many are ready (0 = none).

    Rows appear right away as "building" placeholders (the review screen shows progress),
    then each is built in turn. Never raises for a single bad transition: a YouTube clip
    that can't be fetched falls back to an art card (logged with the reason), a failed plan
    falls back to a few default drink cards, and a slot that can't be built at all is left
    with status "error" so it can be regenerated.
    """
    resolution = resolution or render_resolution()
    _set_review(project_id, "planning")
    try:
        await db.execute(
            delete(ChangoverClipDB).where(
                ChangoverClipDB.project_id == project_id, ChangoverClipDB.origin == "ai"
            )
        )
        for stale in settings.changeover_dir.glob(f"project_{project_id}_ai_*"):
            stale.unlink(missing_ok=True)
        await db.commit()

        playlist_ids, playlist_titles = await _playlist(db, project_id)
        try:
            specs = await plan_transitions(
                theme, count, sources, avoid_titles=playlist_titles, transition_prompt=transition_prompt
            )
        except Exception as exc:
            logger.warning("AI transition planning failed for project %s: %s", project_id, exc)
            specs = []
        if not specs:
            specs = _fallback_specs(count, "cards")
        if drink_text is not None:
            for spec in specs:
                spec.hit_text = clean_drink_text(drink_text)

        rows = []
        for index, spec in enumerate(specs):
            row = ChangoverClipDB(
                project_id=project_id, origin="ai", position=index, label=spec.label,
                source_type="ai_youtube" if spec.kind == "youtube" else "ai_card",
                youtube_id="", image_path="", audio_path="", raw_video_path="", output_path="",
                duration=float(spec.duration), trim_start=0.0, trim_end=0.0,
                status="building", error_message="",
            )
            db.add(row)
            rows.append(row)
        await db.commit()

        _set_review(project_id, "building")
        stems = [_new_stem(project_id) for _ in specs]
        await _attach_art(specs, stems)

        used_ids = set(playlist_ids)
        ready = videos = fallbacks = 0
        for index, (spec, row, stem) in enumerate(zip(specs, rows, stems)):
            try:
                source_type, youtube_id, output_path, length = await _build_one(
                    spec, project_id, index, stem, resolution, used_ids, playlist_titles,
                    card_fallback=sources == "both",
                )
            except Exception as exc:
                logger.warning("AI transition %s for project %s failed: %s", index, project_id, exc)
                row.status = "error"
                row.error_message = str(exc)[:500]
                await db.commit()
                continue
            if youtube_id:
                used_ids.add(youtube_id)
                videos += 1
            elif spec.kind == "youtube":
                fallbacks += 1
            _store_build(row, spec, source_type, youtube_id, output_path,
                         length or (VIDEO_CLIP_SECONDS + VIDEO_TAIL_SECONDS if youtube_id else CARD_SECONDS))
            await db.commit()
            ready += 1

        logger.info(
            "AI transitions for project %s (sources=%s): %s ready of %s planned, %s video, %s card "
            "(%s YouTube fallbacks)",
            project_id, sources, ready, len(specs), videos, ready - videos, fallbacks,
        )
        _set_review(project_id, "idle")
        return ready
    except Exception as exc:
        _set_review(project_id, "idle", f"Transition generation failed: {exc}"[:300])
        raise


async def regenerate_ai_transition(
    db: AsyncSession,
    project_id: int,
    row_id: int,
    theme: str,
    transition_prompt: str = "",
    kind: str | None = None,
    resolution: str | None = None,
    drink_text: str | None = None,
) -> bool:
    """Replace one AI transition with a fresh, different one (same slot in the cycle).

    ``kind`` is "card" or "youtube"; by default the slot keeps its current kind. The old
    files are only removed once the new transition is built. Returns True when it worked;
    on failure the row is left with status "error" and the reason."""
    resolution = resolution or render_resolution()
    row = await db.get(ChangoverClipDB, row_id)
    if row is None or row.project_id != project_id or row.origin != "ai":
        return False
    wanted = kind if kind in ("card", "youtube") else ("youtube" if row.source_type == "ai_youtube" else "card")
    old_output, old_art, old_source = row.output_path or "", row.image_path or "", row.raw_video_path or ""
    row.status = "building"
    row.error_message = ""
    await db.commit()

    others = (
        await db.execute(
            select(ChangoverClipDB).where(
                ChangoverClipDB.project_id == project_id,
                ChangoverClipDB.origin == "ai",
                ChangoverClipDB.id != row_id,
            )
        )
    ).scalars().all()
    playlist_ids, playlist_titles = await _playlist(db, project_id)
    try:
        specs = await plan_transitions(
            theme, 1, "youtube" if wanted == "youtube" else "cards",
            avoid_titles=playlist_titles,
            transition_prompt=transition_prompt,
            avoid_labels=[o.label for o in others if o.label] + ([row.label] if row.label else []),
        )
    except Exception as exc:
        logger.warning("Regenerating AI transition %s: planning failed: %s", row_id, exc)
        specs = []
    if not specs:
        specs = _fallback_specs(len(others) + 2, "cards")[-1:]
    spec = specs[0]
    # Keep the slot's own call word unless a new one was given.
    spec.hit_text = clean_drink_text(drink_text) if drink_text is not None else _spec_from_row(row).hit_text

    stem = _new_stem(project_id)
    await _attach_art([spec], [stem])
    used_ids = set(playlist_ids) | {o.youtube_id for o in others if o.youtube_id}
    try:
        # A video the user asked for never turns into an art card behind their back.
        source_type, youtube_id, output_path, length = await _build_one(
            spec, project_id, row.position or 0, stem, resolution, used_ids, playlist_titles,
            card_fallback=False,
        )
    except Exception as exc:
        row.status = "error"
        row.error_message = str(exc)[:500]
        await db.commit()
        return False

    if old_output != output_path:
        _remove_owned_file(old_output)
    if old_art != spec.art_path:
        _remove_owned_file(old_art)
    if old_source != spec.source_path:
        _remove_owned_file(old_source)
    row.label = spec.label
    _store_build(row, spec, source_type, youtube_id, output_path, length)
    await db.commit()
    return True


def _store_build(
    row: ChangoverClipDB, spec: TransitionSpec, source_type: str, youtube_id: str, output_path: str, length: float
) -> None:
    row.source_type = source_type
    row.youtube_id = youtube_id
    row.output_path = output_path
    row.image_path = spec.art_path
    is_video = source_type == "ai_youtube"
    row.raw_video_path = spec.source_path if is_video else ""
    row.trim_start = spec.trim_start if is_video else 0.0
    row.trim_end = spec.trim_end if is_video else 0.0
    row.style = _style_json(spec)
    row.duration = float(length)
    row.status = "ready"
    row.error_message = ""


async def trim_ai_transition(
    db: AsyncSession, project_id: int, row_id: int, start: float, end: float,
    resolution: str | None = None, drink_text: str | None = None,
) -> bool:
    """Rebuild a video transition from its kept full source, using ``start``..``end`` of it
    (clamped to the source and to 1-20s) and the same color and cue; ``drink_text`` replaces
    the call word when given. On failure the old version stays and the reason is kept in
    ``error_message``. Returns True when the new cut is in place."""
    resolution = resolution or render_resolution()
    row = await db.get(ChangoverClipDB, row_id)
    if row is None or row.project_id != project_id or row.origin != "ai" or row.source_type != "ai_youtube":
        return False
    source = row.raw_video_path or ""
    old_output = row.output_path or ""
    spec = _spec_from_row(row)
    if drink_text is not None:
        spec.hit_text = clean_drink_text(drink_text)
    try:
        if not source or not Path(source).is_file():
            raise RuntimeError("this transition has no source kept to trim; regenerate it instead")
        available = await probe_duration(source)
        if available <= 0:
            raise RuntimeError("could not read the transition source")
        start = max(0.0, min(float(start), available - MIN_TRIM_SECONDS))
        end = max(start + MIN_TRIM_SECONDS, min(float(end), available, start + MAX_VIDEO_CLIP_SECONDS))
        output_path = str(settings.changeover_dir / f"{_new_stem(project_id)}.mp4")
        length = await _render_moment(spec, output_path, source, start, round(end - start, 2), resolution)
    except Exception as exc:
        logger.warning("Trimming AI transition %s failed: %s", row_id, exc)
        row.status = "ready" if old_output and Path(old_output).is_file() else "error"
        row.error_message = f"Trim failed: {exc}"[:500]
        await db.commit()
        return False
    _remove_owned_file(old_output)
    row.output_path = output_path
    row.trim_start, row.trim_end = round(start, 2), round(end, 2)
    row.style = _style_json(spec)
    row.duration = float(length)
    row.status = "ready"
    row.error_message = ""
    await db.commit()
    return True


async def retext_ai_transition(
    db: AsyncSession, project_id: int, row_id: int, drink_text: str, resolution: str | None = None
) -> bool:
    """Rebuild one transition with a new call word (same clip range / same art)."""
    row = await db.get(ChangoverClipDB, row_id)
    if row is None or row.project_id != project_id or row.origin != "ai":
        return False
    if row.source_type == "ai_youtube":
        return await trim_ai_transition(
            db, project_id, row_id, row.trim_start or 0.0, row.trim_end or 0.0, resolution, drink_text
        )
    resolution = resolution or render_resolution()
    spec = _spec_from_row(row)
    spec.hit_text = clean_drink_text(drink_text)
    old_output = row.output_path or ""
    output_path = str(settings.changeover_dir / f"{_new_stem(project_id)}.mp4")
    try:
        length = await _build_card(spec, output_path, resolution)
    except Exception as exc:
        logger.warning("Re-texting AI transition %s failed: %s", row_id, exc)
        row.status = "ready" if old_output and Path(old_output).is_file() else "error"
        row.error_message = f"Text change failed: {exc}"[:500]
        await db.commit()
        return False
    _remove_owned_file(old_output)
    row.output_path = output_path
    row.style = _style_json(spec)
    row.duration = float(length)
    row.status = "ready"
    row.error_message = ""
    await db.commit()
    return True


async def add_ai_transition_row(db: AsyncSession, project_id: int, kind: str = "card") -> int | None:
    """Append an empty "building" slot to the cycle (then regenerate it). None when full."""
    rows = (
        await db.execute(
            select(ChangoverClipDB).where(
                ChangoverClipDB.project_id == project_id, ChangoverClipDB.origin == "ai"
            )
        )
    ).scalars().all()
    if len(rows) >= MAX_COUNT:
        return None
    row = ChangoverClipDB(
        project_id=project_id, origin="ai",
        position=max((r.position or 0 for r in rows), default=-1) + 1,
        label="New transition",
        source_type="ai_youtube" if kind == "youtube" else "ai_card",
        youtube_id="", image_path="", audio_path="", raw_video_path="", output_path="",
        duration=CARD_SECONDS, trim_start=0.0, trim_end=0.0, status="building", error_message="",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row.id


async def delete_ai_transition(db: AsyncSession, project_id: int, row_id: int) -> bool:
    row = await db.get(ChangoverClipDB, row_id)
    if row is None or row.project_id != project_id or row.origin != "ai":
        return False
    _remove_owned_file(row.output_path or "")
    _remove_owned_file(row.image_path or "")
    _remove_owned_file(row.raw_video_path or "")
    await db.delete(row)
    await db.commit()
    return True


