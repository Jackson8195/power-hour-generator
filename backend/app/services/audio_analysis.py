"""Audio analysis service for finding the best 60-second segment in a song.

Uses librosa for beat tracking, onset detection, and spectral analysis
to automatically suggest the most energetic/interesting segment.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


async def analyze_audio(file_path: str, clip_duration: int = 60) -> dict:
    """Analyze audio and find the best segment for a power hour clip.

    Returns:
        dict with keys:
            - suggested_start: float, best start time in seconds
            - bpm: float, estimated BPM
            - energy: float, overall energy score (0-1)
            - duration: float, total duration
    """
    # Run CPU-intensive analysis in a thread pool
    return await asyncio.to_thread(_analyze_sync, file_path, clip_duration)


def _analyze_sync(file_path: str, clip_duration: int = 60) -> dict:
    """Synchronous audio analysis (runs in thread pool)."""
    import librosa
    import soundfile as sf

    try:
        # Load audio (mono, 22050 Hz for analysis speed)
        y, sr = librosa.load(file_path, sr=22050, mono=True)
        duration = librosa.get_duration(y=y, sr=sr)

        if duration <= clip_duration:
            return {
                "suggested_start": 0.0,
                "bpm": _estimate_bpm(y, sr),
                "energy": _compute_energy(y),
                "duration": duration,
            }

        # Find the most energetic segment
        suggested_start = _find_best_segment(y, sr, clip_duration)
        bpm = _estimate_bpm(y, sr)
        energy = _compute_energy(y)

        return {
            "suggested_start": round(suggested_start, 2),
            "bpm": round(bpm, 1),
            "energy": round(energy, 4),
            "duration": round(duration, 2),
        }

    except Exception as e:
        logger.error(f"Audio analysis failed for {file_path}: {e}")
        return {
            "suggested_start": 0.0,
            "bpm": None,
            "energy": None,
            "duration": 0.0,
        }


def _find_best_segment(y: np.ndarray, sr: int, clip_duration: int) -> float:
    """Find the start time of the most energetic segment.

    Strategy:
    1. Compute RMS energy envelope
    2. Compute spectral flux (change in spectrum = excitement)
    3. Combine into a "party score" per frame
    4. Slide a window of clip_duration and find the peak
    """
    import librosa

    hop_length = 512

    # RMS energy
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    rms_norm = rms / (rms.max() + 1e-8)

    # Spectral flux (onset strength)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    onset_norm = onset_env / (onset_env.max() + 1e-8)

    # Combine: favor segments that are both loud and rhythmically active
    party_score = 0.6 * rms_norm[:len(onset_norm)] + 0.4 * onset_norm[:len(rms_norm)]

    # Sliding window to find the best segment
    frames_per_clip = int(clip_duration * sr / hop_length)

    if len(party_score) <= frames_per_clip:
        return 0.0

    # Compute rolling sum
    cumsum = np.cumsum(party_score)
    window_sums = cumsum[frames_per_clip:] - cumsum[:-frames_per_clip]

    best_frame = np.argmax(window_sums)
    best_time = librosa.frames_to_time(best_frame, sr=sr, hop_length=hop_length)

    # Snap to nearest beat for a clean start
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=hop_length)

    if len(beat_times) > 0:
        nearest_beat_idx = np.argmin(np.abs(beat_times - best_time))
        best_time = beat_times[nearest_beat_idx]

    # Ensure we don't exceed the track length
    duration = librosa.get_duration(y=y, sr=sr)
    max_start = max(0, duration - clip_duration)
    best_time = min(best_time, max_start)

    return float(best_time)


def _estimate_bpm(y: np.ndarray, sr: int) -> float:
    """Estimate the BPM of the track."""
    import librosa
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    if isinstance(tempo, np.ndarray):
        tempo = tempo[0]
    return float(tempo)


def _compute_energy(y: np.ndarray) -> float:
    """Compute overall energy score (0-1)."""
    rms = np.sqrt(np.mean(y ** 2))
    # Normalize to roughly 0-1 range (typical music RMS is 0.05-0.3)
    return float(min(rms / 0.3, 1.0))
