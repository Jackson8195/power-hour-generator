"""YouTube search and video download service."""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

from app.core.config import settings
from app.models.schemas import SearchResult

logger = logging.getLogger(__name__)

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


async def search_youtube(query: str, max_results: int = 10) -> list[SearchResult]:
    """Search YouTube using the Data API v3.

    Falls back to yt-dlp search if no API key is configured.
    """
    if settings.youtube_api_key:
        return await _search_with_api(query, max_results)
    else:
        return await _search_with_ytdlp(query, max_results)


async def _search_with_api(query: str, max_results: int) -> list[SearchResult]:
    """Search using YouTube Data API v3."""
    async with httpx.AsyncClient() as client:
        # Search for videos
        search_resp = await client.get(YOUTUBE_SEARCH_URL, params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoCategoryId": "10",  # Music category
            "maxResults": max_results,
            "key": settings.youtube_api_key,
        })
        search_resp.raise_for_status()
        search_data = search_resp.json()

        video_ids = [item["id"]["videoId"] for item in search_data.get("items", [])]
        if not video_ids:
            return []

        # Get video details (duration, view count)
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

        results = []
        for item in search_data.get("items", []):
            vid_id = item["id"]["videoId"]
            snippet = item["snippet"]
            details = details_map.get(vid_id, {})
            results.append(SearchResult(
                youtube_id=vid_id,
                title=snippet["title"],
                artist=snippet["channelTitle"],
                thumbnail=snippet["thumbnails"].get("high", snippet["thumbnails"]["default"])["url"],
                duration=details.get("duration", ""),
                view_count=details.get("view_count", ""),
            ))

        return results


async def _search_with_ytdlp(query: str, max_results: int) -> list[SearchResult]:
    """Fallback search using yt-dlp (no API key needed)."""
    cmd = [
        "yt-dlp",
        f"ytsearch{max_results}:{query} music video",
        "--dump-json",
        "--flat-playlist",
        "--no-download",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    results = []
    for line in stdout.decode().strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            results.append(SearchResult(
                youtube_id=data.get("id", ""),
                title=data.get("title", "Unknown"),
                artist=data.get("channel", data.get("uploader", "")),
                thumbnail=data.get("thumbnail", data.get("thumbnails", [{}])[-1].get("url", "")),
                duration=_seconds_to_timestamp(data.get("duration", 0)),
                view_count=str(data.get("view_count", "")),
            ))
        except json.JSONDecodeError:
            continue

    return results


async def download_video(
    youtube_id: str,
    output_dir: Optional[Path] = None,
    quality: Optional[int] = None,
) -> dict:
    """Download a YouTube video using yt-dlp.

    Returns dict with file_path, duration, title, etc.
    """
    output_dir = output_dir or settings.media_dir
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

    # Parse the JSON output (last line)
    json_lines = [l for l in stdout.decode().strip().split("\n") if l.startswith("{")]
    if not json_lines:
        raise RuntimeError("No JSON output from yt-dlp")

    data = json.loads(json_lines[-1])

    return {
        "file_path": data.get("requested_downloads", [{}])[0].get("filepath", ""),
        "duration": data.get("duration", 0),
        "title": data.get("title", ""),
        "artist": data.get("channel", data.get("uploader", "")),
    }


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
