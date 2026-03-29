"""FFmpeg-based video rendering pipeline.

Handles clip extraction, normalization, transitions, countdown overlays,
and final concatenation into a Power Hour video.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Callable, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


async def extract_clip_segment(
    source_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
) -> str:
    """Create a standalone clip file from a source video."""
    duration = max(end_time - start_time, 0.1)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        settings.ffmpeg_path,
        "-y",
        "-ss", str(start_time),
        "-i", source_path,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"FFmpeg clip extraction failed: {stderr.decode()[-500:]}")
        raise RuntimeError(f"Failed to extract clip from {source_path}")

    return str(output)


class RenderPipeline:
    """Renders a Power Hour video from a list of clips."""

    def __init__(
        self,
        clips: list[dict],
        output_path: str,
        resolution: str = "1280x720",
        transition_type: str = "crossfade",
        transition_duration: float = 1.5,
        countdown_start: int = 55,
        include_countdown: bool = True,
        progress_callback: Optional[Callable[[float], None]] = None,
    ):
        self.clips = clips  # List of {file_path, start_time, end_time, title}
        self.output_path = Path(output_path)
        self.width, self.height = map(int, resolution.split("x"))
        self.transition_type = transition_type
        self.transition_duration = transition_duration
        self.countdown_start = countdown_start
        self.include_countdown = include_countdown
        self.progress_callback = progress_callback

    async def render(self) -> str:
        """Execute the full render pipeline."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        total_steps = len(self.clips) + 1  # normalize each clip + final concat
        current_step = 0

        # Step 1: Normalize each clip (resolution, codec, audio levels)
        normalized_clips = []
        for clip in self.clips:
            norm_path = await self._normalize_clip(clip)
            normalized_clips.append(norm_path)
            current_step += 1
            if self.progress_callback:
                self.progress_callback(current_step / total_steps * 90)  # 0-90%

        # Step 2: Concatenate all clips with transitions
        await self._concatenate(normalized_clips)
        if self.progress_callback:
            self.progress_callback(100)

        # Cleanup temp files
        for path in normalized_clips:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass

        return str(self.output_path)

    async def _normalize_clip(self, clip: dict) -> str:
        """Normalize a single clip: trim, scale, normalize audio."""
        file_path = clip["file_path"]
        start_time = clip.get("start_time", 0)
        end_time = clip.get("end_time", 60)
        duration = end_time - start_time

        # Create temp output for normalized clip
        suffix = Path(file_path).suffix or ".mp4"
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, dir=str(settings.temp_dir))
        tmp.close()

        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-ss", str(start_time),
            "-i", file_path,
            "-t", str(duration),
            # Video: scale to target resolution, pad if aspect ratio differs
            "-vf", (
                f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,"
                "setsar=1"
            ),
            # Audio: normalize loudness
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            # Codec settings
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            # Ensure consistent framerate
            "-r", "30",
            "-movflags", "+faststart",
            tmp.name,
        ]

        # Add countdown overlay if enabled
        if self.include_countdown:
            countdown_filter = self._build_countdown_filter(duration)
            if countdown_filter:
                vf_idx = cmd.index("-vf") + 1
                cmd[vf_idx] = cmd[vf_idx] + "," + countdown_filter

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"FFmpeg normalize failed: {stderr.decode()[-500:]}")
            raise RuntimeError(f"Failed to normalize clip: {file_path}")

        return tmp.name

    def _build_countdown_filter(self, clip_duration: float) -> str:
        """Build FFmpeg drawtext filter for countdown overlay."""
        countdown_seconds = int(clip_duration - self.countdown_start)
        if countdown_seconds <= 0:
            return ""

        # Show countdown from 5 to 1 in the last 5 seconds
        filters = []
        for i in range(min(countdown_seconds, 5), 0, -1):
            appear_time = clip_duration - i
            filters.append(
                f"drawtext=text='{i}':"
                f"fontsize=120:fontcolor=white:borderw=4:bordercolor=black:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:"
                f"enable='between(t,{appear_time},{appear_time + 0.9})'"
            )

        # "DRINK!" text at the very end
        filters.append(
            f"drawtext=text='DRINK!':"
            f"fontsize=100:fontcolor=yellow:borderw=4:bordercolor=black:"
            f"x=(w-text_w)/2:y=(h-text_h)/2:"
            f"enable='between(t,{clip_duration - 0.5},{clip_duration})'"
        )

        return ",".join(filters)

    async def _concatenate(self, clip_paths: list[str]) -> None:
        """Concatenate normalized clips into final video."""
        if self.transition_type == "hard_cut":
            await self._concat_hard_cut(clip_paths)
        else:
            # Default: use concat demuxer for gapless playback
            await self._concat_demuxer(clip_paths)

    async def _concat_demuxer(self, clip_paths: list[str]) -> None:
        """Concatenate using FFmpeg concat demuxer (fast, no re-encode)."""
        # Create concat file list
        concat_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, dir=str(settings.temp_dir)
        )
        for path in clip_paths:
            concat_file.write(f"file '{path}'\n")
        concat_file.close()

        cmd = [
            settings.ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file.name,
            "-c", "copy",
            "-movflags", "+faststart",
            str(self.output_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        Path(concat_file.name).unlink(missing_ok=True)

        if proc.returncode != 0:
            raise RuntimeError(f"Concatenation failed: {stderr.decode()[-500:]}")

    async def _concat_hard_cut(self, clip_paths: list[str]) -> None:
        """Simple hard-cut concatenation."""
        await self._concat_demuxer(clip_paths)  # Same for now


async def get_video_duration(file_path: str) -> float:
    """Get video duration using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 0.0
