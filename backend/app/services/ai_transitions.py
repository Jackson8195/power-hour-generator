"""AI-created transition clips: several varied changeovers the renderer cycles through.

The AI plans a set of transitions for a playlist theme. Each is either a generated text card
(rendered locally by ffmpeg) or a short clip found on YouTube. Everything the AI returns is
treated as untrusted: text is length-limited and stripped, colors come from a fixed palette,
and text reaches ffmpeg only via files (see ``build_text_card``).
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.schemas import ChangoverClipDB
from app.services.ffmpeg import build_changeover_clip, build_text_card
from app.services.youtube import download_video, search_youtube

logger = logging.getLogger(__name__)

# Named colors the AI may choose from, mapped to hex so it can never inject arbitrary values.
PALETTE = {
    "yellow": "#FFE600", "pink": "#FF4FA3", "cyan": "#1AFFE4", "green": "#39FF14",
    "orange": "#FF8A00", "red": "#FF2D2D", "white": "#FFFFFF", "purple": "#B266FF",
    "black": "#000000", "navy": "#0B1030", "maroon": "#2B0A12", "forest": "#06210F",
}
DARK_BACKGROUNDS = ("black", "navy", "maroon", "forest")
MAX_COUNT = 8
MAX_YOUTUBE_SECONDS = 90
FALLBACK_HEADLINE = "SHOT!"


@dataclass
class TransitionSpec:
    kind: str  # "card" | "youtube"
    label: str
    headline: str = FALLBACK_HEADLINE
    subline: str = ""
    countdown: list[str] = field(default_factory=list)
    text_color: str = PALETTE["yellow"]
    bg_color: str = PALETTE["black"]
    duration: float = 4.0
    query: str = ""


def _clean_text(value: object, limit: int) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return " ".join(text.split())[:limit].strip()


def sanitize_spec(raw: dict, sources: str) -> TransitionSpec | None:
    """Turn one AI-proposed transition into a safe spec, or None if unusable."""
    kind = "youtube" if str(raw.get("kind", "")).strip().lower() == "youtube" else "card"
    if sources == "cards":
        kind = "card"
    elif sources == "youtube":
        kind = "youtube"

    headline = _clean_text(raw.get("headline"), 18) or FALLBACK_HEADLINE
    query = _clean_text(raw.get("query"), 80)
    label = _clean_text(raw.get("label"), 60) or headline
    if kind == "youtube" and not query:
        query = label  # a youtube transition needs something to search for

    text_name = str(raw.get("text_color", "")).strip().lower()
    bg_name = str(raw.get("bg_color", "")).strip().lower()
    text_color = PALETTE.get(text_name, PALETTE["yellow"])
    bg_color = PALETTE.get(bg_name, PALETTE["black"])
    if text_color == bg_color:
        bg_color = PALETTE["black"] if text_color != PALETTE["black"] else PALETTE["white"]

    countdown_raw = raw.get("countdown")
    countdown: list[str] = []
    if isinstance(countdown_raw, list):
        countdown = [c for c in (_clean_text(x, 8) for x in countdown_raw[:3]) if c]

    try:
        duration = float(raw.get("duration", 4.0))
    except (TypeError, ValueError):
        duration = 4.0
    duration = min(max(duration, 3.0), 6.0)

    return TransitionSpec(
        kind=kind,
        label=label,
        headline=headline,
        subline=_clean_text(raw.get("subline"), 32),
        countdown=countdown,
        text_color=text_color,
        bg_color=bg_color,
        duration=duration,
        query=query,
    )


def sanitize_specs(raw_items: object, count: int, sources: str) -> list[TransitionSpec]:
    """Sanitize, drop duplicates, and cap at ``count`` (and MAX_COUNT)."""
    limit = max(0, min(count, MAX_COUNT))
    specs: list[TransitionSpec] = []
    seen: set[str] = set()
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict):
            continue
        spec = sanitize_spec(raw, sources)
        if not spec:
            continue
        key = (spec.query if spec.kind == "youtube" else spec.headline).lower()
        if key in seen:
            continue
        seen.add(key)
        specs.append(spec)
        if len(specs) >= limit:
            break
    return specs


def _fallback_specs(count: int, sources: str) -> list[TransitionSpec]:
    """Used when planning fails: a few distinct generated cards so the cycle still varies."""
    variants = [
        {"headline": "SHOT!", "countdown": ["3", "2", "1"], "text_color": "yellow", "bg_color": "black"},
        {"headline": "DRINK!", "countdown": ["2", "1"], "text_color": "pink", "bg_color": "navy"},
        {"headline": "CHEERS!", "countdown": [], "text_color": "cyan", "bg_color": "maroon"},
        {"headline": "BOTTOMS UP", "countdown": ["1"], "text_color": "green", "bg_color": "black"},
    ]
    return sanitize_specs(variants, count, "cards")


async def plan_transitions(theme: str, count: int, sources: str) -> list[TransitionSpec]:
    """Ask the AI for ``count`` varied transitions that fit the playlist theme."""
    from app.services.auto_generate import _get_openai_client  # lazy: avoids an import cycle

    count = max(1, min(count, MAX_COUNT))
    if sources == "cards":
        mix = 'Every transition must have kind "card".'
    elif sources == "youtube":
        mix = 'Every transition must have kind "youtube".'
    else:
        mix = 'Use a mix of kind "card" and kind "youtube" (at least one of each when count >= 2).'

    client = _get_openai_client()
    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You design short transition clips (3-6 seconds) that play between songs in a drinking-game "
                    "'power hour' video, signalling it's time for the next shot. Make them distinct from each other. "
                    'Return only strict JSON shaped as {"transitions": [{"kind": "card" | "youtube", "label": string, '
                    '"headline": string, "subline": string, "countdown": [string], "text_color": string, '
                    '"bg_color": string, "duration": number, "query": string}]}. '
                    "For kind card: headline is 1-2 punchy words (max 18 chars), subline optional (max 32 chars), "
                    "countdown is 0-3 short words/numbers shown one per second before the headline, and colors must be "
                    f"from this list: {', '.join(PALETTE)}. Use a dark bg_color with a bright text_color. "
                    "For kind youtube: query is a YouTube search for a short, recognizable, safe-for-work clip "
                    "(meme, movie moment, sound effect, etc.) that fits the theme; other fields can be minimal. "
                    + mix
                ),
            },
            {"role": "user", "content": f"Playlist theme: {theme}\nCreate {count} different transitions."},
        ],
    )
    payload = json.loads(response.choices[0].message.content or "{}")
    return sanitize_specs(payload.get("transitions"), count, sources)


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


async def _build_card(spec: TransitionSpec, output_path: str, resolution: str) -> None:
    await build_text_card(
        output_path,
        countdown=spec.countdown,
        headline=spec.headline,
        subline=spec.subline,
        text_color=spec.text_color,
        bg_color=spec.bg_color,
        duration=spec.duration,
        resolution=resolution,
    )


async def _build_youtube(
    spec: TransitionSpec, project_id: int, index: int, output_path: str, resolution: str
) -> str:
    """Find, download and trim a short clip. Returns the YouTube id used."""
    results = await search_youtube(spec.query, max_results=5, music=False)
    results = [r for r in results if r.youtube_id]
    if not results:
        raise RuntimeError(f"No YouTube results for {spec.query!r}")
    short = [r for r in results if (_duration_seconds(r.duration) or 10**6) <= MAX_YOUTUBE_SECONDS]
    chosen = (short or results)[0]

    raw_stem = f"project_{project_id}_ai_{index}_raw"
    info = await download_video(chosen.youtube_id, output_dir=settings.changeover_dir, file_stem=raw_stem)
    raw_path = Path(info["file_path"])
    try:
        await build_changeover_clip(
            output_path, duration=spec.duration, resolution=resolution, video_path=str(raw_path),
        )
    finally:
        raw_path.unlink(missing_ok=True)
    return chosen.youtube_id


async def create_ai_transitions(
    db: AsyncSession,
    project_id: int,
    theme: str,
    count: int,
    sources: str = "both",
    resolution: str = "1280x720",
) -> int:
    """Plan and build the project's AI transitions. Returns how many are ready (0 = none).

    Never raises for a single bad transition: a YouTube clip that can't be fetched falls
    back to a generated card, and a failed plan falls back to a few default cards.
    """
    await db.execute(
        delete(ChangoverClipDB).where(
            ChangoverClipDB.project_id == project_id, ChangoverClipDB.origin == "ai"
        )
    )
    for stale in settings.changeover_dir.glob(f"project_{project_id}_ai_*"):
        stale.unlink(missing_ok=True)

    try:
        specs = await plan_transitions(theme, count, sources)
    except Exception as exc:
        logger.warning("AI transition planning failed for project %s: %s", project_id, exc)
        specs = []
    if not specs:
        specs = _fallback_specs(count, "cards")

    ready = 0
    for index, spec in enumerate(specs):
        output_path = str(settings.changeover_dir / f"project_{project_id}_ai_{index}.mp4")
        youtube_id = ""
        source_type = "ai_card"
        try:
            if spec.kind == "youtube":
                try:
                    youtube_id = await _build_youtube(spec, project_id, index, output_path, resolution)
                    source_type = "ai_youtube"
                except Exception as exc:
                    logger.warning("AI YouTube transition %r failed (%s); using a card", spec.query, exc)
                    await _build_card(spec, output_path, resolution)
            else:
                await _build_card(spec, output_path, resolution)
        except Exception as exc:
            logger.warning("AI transition %s for project %s failed: %s", index, project_id, exc)
            continue

        db.add(
            ChangoverClipDB(
                project_id=project_id,
                origin="ai",
                position=index,
                label=spec.label,
                source_type=source_type,
                youtube_id=youtube_id,
                image_path="",
                audio_path="",
                raw_video_path="",
                output_path=output_path,
                duration=spec.duration,
                trim_start=0.0,
                trim_end=0.0,
                status="ready",
                error_message="",
            )
        )
        ready += 1

    await db.commit()
    return ready
