"""YouTube search, ranking, recommendations, and video download service."""

import asyncio
import html
import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings
from app.models.schemas import ClipDB, SearchResult

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

NEGATIVE_TITLE_HINTS = {
    "live", "cover", "reaction", "karaoke", "instrumental", "nightcore",
    "slowed", "reverb", "sped up", "8d audio", "lyrics", "audio only", "fanmade",
}
POSITIVE_TITLE_HINTS = {
    "official video", "official music video", "music video", "hd", "remastered",
}
ARTIST_SPLIT_RE = re.compile(r"\s*(?:,|&| x | ft\.?| feat\.?| featuring | with )\s*", re.IGNORECASE)
STOPWORDS = {
    "official", "video", "music", "feat", "featuring", "ft", "the", "and",
    "a", "an", "of", "version", "explicit", "clean", "lyrics",
}


async def search_youtube(
    query: str,
    max_results: int = 10,
    preferred_artists: Optional[list[str]] = None,
    music: bool = True,
) -> list[SearchResult]:
    """Search YouTube using the Data API v3 or yt-dlp fallback, then rerank.

    When ``music`` is False the search is a plain YouTube search — no music-category
    filter, no "official music video" query suffix, and no music-specific ranking.
    Used for changeover/transition clips, which usually aren't songs.
    """
    fetch_limit = min(max(max_results * 3, 15), 30)
    if settings.youtube_api_key:
        try:
            results = await _search_with_api(query, fetch_limit, music=music)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "YouTube Data API search failed with %s for query %r; falling back to yt-dlp search.",
                exc.response.status_code,
                query,
            )
            results = await _search_with_ytdlp(query, fetch_limit, music=music)
        except Exception as exc:
            logger.warning(
                "YouTube Data API search failed for query %r (%s: %s); falling back to yt-dlp search.",
                query,
                type(exc).__name__,
                exc,
            )
            results = await _search_with_ytdlp(query, fetch_limit, music=music)
    else:
        results = await _search_with_ytdlp(query, fetch_limit)

    ranked = _rank_search_results(query, results, preferred_artists=preferred_artists or [], music=music)
    return ranked[:max_results]


async def recommend_for_project(clips: list[ClipDB], max_results: int = 12) -> list[SearchResult]:
    """Recommend additional tracks based on artists already chosen in a project."""
    selected_ids = {clip.youtube_id for clip in clips if clip.youtube_id}
    selected_titles = {_normalize_text(clip.source_title) for clip in clips if clip.source_title}

    artist_counts: dict[str, int] = {}
    for clip in clips:
        for artist in _split_artist_names(clip.source_artist):
            if artist:
                artist_counts[artist] = artist_counts.get(artist, 0) + 1

    top_artists = [artist for artist, _ in sorted(artist_counts.items(), key=lambda item: (-item[1], item[0]))[:4]]
    if not top_artists:
        return []

    recommendations: list[SearchResult] = []
    seen_ids: set[str] = set()

    for artist in top_artists:
        seed_count = artist_counts.get(artist, 1)
        query = f"{artist} official music video"
        results = await search_youtube(query, max_results=6, preferred_artists=[artist])
        for result in results:
            normalized_title = _normalize_text(result.title)
            if not result.youtube_id or result.youtube_id in selected_ids or result.youtube_id in seen_ids:
                continue
            if normalized_title in selected_titles:
                continue
            result.recommendation_reason = (
                f"Because you've already picked {seed_count} track"
                f"{'' if seed_count == 1 else 's'} from {artist}"
            )
            recommendations.append(result)
            seen_ids.add(result.youtube_id)
            if len(recommendations) >= max_results:
                return recommendations

    return recommendations[:max_results]


async def _search_with_api(query: str, max_results: int, music: bool = True) -> list[SearchResult]:
    """Search using YouTube Data API v3."""
    params = {
        "part": "snippet",
        "q": _build_search_query(query, music),
        "type": "video",
        "maxResults": max_results,
        "key": settings.youtube_api_key,
    }
    if music:
        params["videoCategoryId"] = "10"  # restrict to YouTube's Music category
    async with httpx.AsyncClient(timeout=15.0) as client:
        search_resp = await client.get(YOUTUBE_SEARCH_URL, params=params)
        search_resp.raise_for_status()
        search_data = search_resp.json()

        video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
        if not video_ids:
            return []

        details_resp = await client.get(YOUTUBE_VIDEOS_URL, params={
            "part": "contentDetails,statistics",
            "id": ",".join(video_ids),
            "key": settings.youtube_api_key,
        })
        details_resp.raise_for_status()
        details_data = details_resp.json()

        details_map = {}
        for item in details_data.get("items", []):
            details_map[item["id"]] = {
                "duration": _parse_iso_duration(item["contentDetails"]["duration"]),
                "view_count": item.get("statistics", {}).get("viewCount", ""),
            }

        return [
            SearchResult(
                youtube_id=item["id"]["videoId"],
                title=html.unescape(item["snippet"]["title"]),
                artist=html.unescape(item["snippet"]["channelTitle"]),
                thumbnail=item["snippet"]["thumbnails"].get("high", item["snippet"]["thumbnails"]["default"])["url"],
                duration=details_map.get(item["id"]["videoId"], {}).get("duration", ""),
                view_count=details_map.get(item["id"]["videoId"], {}).get("view_count", ""),
                search_source="youtube_api",
            )
            for item in search_data.get("items", [])
        ]


async def _search_with_ytdlp(query: str, max_results: int, music: bool = True) -> list[SearchResult]:
    """Fallback search using yt-dlp."""
    cmd = [
        "yt-dlp",
        f"ytsearch{max_results}:{_build_search_query(query, music)}",
        "--dump-json",
        "--flat-playlist",
        "--no-download",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    results = []
    for line in stdout.decode().strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            results.append(SearchResult(
                youtube_id=data.get("id", ""),
                title=html.unescape(data.get("title", "Unknown")),
                artist=html.unescape(data.get("channel", data.get("uploader", ""))),
                thumbnail=data.get("thumbnail", data.get("thumbnails", [{}])[-1].get("url", "")),
                duration=_seconds_to_timestamp(data.get("duration", 0)),
                view_count=str(data.get("view_count", "")),
                search_source="yt_dlp",
            ))
        except json.JSONDecodeError:
            continue

    return results


def _build_search_query(query: str, music: bool = True) -> str:
    """Nudge YouTube toward official music videos without making search too rigid.

    For non-music (transition) searches the query is used verbatim.
    """
    cleaned = query.strip()
    if not music:
        return cleaned
    lowered = cleaned.lower()
    if any(term in lowered for term in ("official", "lyrics", "live", "cover", "karaoke", "instrumental")):
        return cleaned
    return f"{cleaned} official music video"


def _rank_search_results(
    query: str,
    results: list[SearchResult],
    preferred_artists: list[str],
    music: bool = True,
) -> list[SearchResult]:
    """Rank raw YouTube results. Music-specific heuristics apply only when ``music``
    is True; otherwise results are ranked by plain term relevance + view count."""
    parsed_artist, parsed_song = _split_query(query)
    query_terms = _meaningful_terms(query)
    preferred_terms = {_normalize_text(artist) for artist in preferred_artists if artist}

    scored: list[SearchResult] = []
    for result in results:
        title_norm = _normalize_text(result.title)
        artist_norm = _normalize_text(result.artist)
        combined = f"{title_norm} {artist_norm}"
        score = 0.0

        for term in query_terms:
            if term in title_norm:
                score += 2.4
            elif term in combined:
                score += 1.1

        if music:
            if parsed_artist:
                artist_terms = _meaningful_terms(parsed_artist)
                song_terms = _meaningful_terms(parsed_song) if parsed_song else []
                if all(term in combined for term in artist_terms):
                    score += 8
                if song_terms and all(term in title_norm for term in song_terms):
                    score += 7
                if artist_terms and song_terms and all(term in combined for term in artist_terms + song_terms):
                    score += 6

            for positive in POSITIVE_TITLE_HINTS:
                if positive in title_norm:
                    score += 2

            for negative in NEGATIVE_TITLE_HINTS:
                if negative in title_norm and negative not in _normalize_text(query):
                    score -= 4

            if preferred_terms and any(pref in artist_norm for pref in preferred_terms):
                score += 5

            if "vevo" in artist_norm or "official" in artist_norm:
                score += 1.5

        score += min(_parse_view_count(result.view_count) / 50_000_000, 3)
        result.match_score = round(score, 2)
        scored.append(result)

    return sorted(
        scored,
        key=lambda item: (item.match_score, _parse_view_count(item.view_count)),
        reverse=True,
    )


async def download_video(
    youtube_id: str,
    output_dir: Optional[Path] = None,
    quality: Optional[int] = None,
) -> dict:
    """Download a YouTube video using yt-dlp."""
    output_dir = output_dir or settings.downloads_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    quality = quality or settings.default_video_quality

    output_template = str(output_dir / f"{youtube_id}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={youtube_id}"

    cmd = [
        "yt-dlp",
        url,
        "-f", f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]",
        "--merge-output-format", "mp4",
        "-o", output_template,
        "--print-json",
        "--no-playlist",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {stderr.decode()}")

    json_lines = [l for l in stdout.decode().strip().split("\n") if l.startswith("{")]
    if not json_lines:
        raise RuntimeError("No JSON output from yt-dlp")

    data = json.loads(json_lines[-1])
    file_path = (
        data.get("requested_downloads", [{}])[0].get("filepath")
        or data.get("_filename")
        or _resolve_downloaded_file(output_dir, youtube_id)
    )

    return {
        "file_path": str(file_path) if file_path else "",
        "duration": data.get("duration", 0),
        "title": html.unescape(data.get("title", "")),
        "artist": html.unescape(data.get("channel", data.get("uploader", ""))),
    }


async def download_audio_only(
    youtube_id: str,
    output_dir: Optional[Path] = None,
) -> str:
    """Download audio-only from a YouTube video using yt-dlp. Returns the file path."""
    output_dir = output_dir or settings.downloads_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(output_dir / f"{youtube_id}_audio.%(ext)s")
    url = f"https://www.youtube.com/watch?v={youtube_id}"

    cmd = [
        "yt-dlp",
        url,
        "-f", "bestaudio",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", output_template,
        "--no-playlist",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp audio download failed: {stderr.decode()[-300:]}")

    # yt-dlp may output as .mp3 directly or convert
    mp3_path = output_dir / f"{youtube_id}_audio.mp3"
    if mp3_path.exists():
        return str(mp3_path)

    # Fallback: find any matching file
    candidates = sorted(output_dir.glob(f"{youtube_id}_audio.*"))
    for c in candidates:
        if c.is_file():
            return str(c)

    raise RuntimeError(f"Audio file not found after download for {youtube_id}")


def _resolve_downloaded_file(output_dir: Path, youtube_id: str) -> str:
    """Find the actual downloaded file when yt-dlp omits filepath metadata."""
    exact_mp4 = output_dir / f"{youtube_id}.mp4"
    if exact_mp4.exists():
        return str(exact_mp4)

    candidates = sorted(output_dir.glob(f"{youtube_id}.*"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    return ""


def _split_query(query: str) -> tuple[str, str]:
    """Split a query into likely artist/song parts when possible."""
    separators = [" - ", " by ", " — ", " – ", ":"]
    for separator in separators:
        if separator in query.lower():
            parts = re.split(re.escape(separator), query, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                return parts[0].strip(), parts[1].strip()
    if "-" in query:
        left, right = query.split("-", 1)
        return left.strip(), right.strip()
    return "", query.strip()


def _split_artist_names(artist_text: str) -> list[str]:
    """Expand common feature/collaboration separators into artist seeds."""
    return [part.strip() for part in ARTIST_SPLIT_RE.split(artist_text or "") if part.strip()]


def _meaningful_terms(text: str) -> list[str]:
    """Extract normalized query terms that are useful for ranking."""
    tokens = [token for token in _normalize_text(text).split() if len(token) > 1 and token not in STOPWORDS]
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen


def _normalize_text(text: str) -> str:
    """Lowercase and strip punctuation for heuristic matching."""
    text = html.unescape(text or "").lower()
    text = re.sub(r"\(.*?\)|\[.*?\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_view_count(value: str) -> int:
    digits = re.sub(r"\D", "", value or "")
    return int(digits) if digits else 0


def _parse_iso_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (PT4M33S) to human readable (4:33)."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not match:
        return ""
    hours, minutes, seconds = match.groups()
    hours = int(hours or 0)
    minutes = int(minutes or 0)
    seconds = int(seconds or 0)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _seconds_to_timestamp(seconds: float) -> str:
    """Convert seconds to M:SS format."""
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
