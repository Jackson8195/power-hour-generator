"""Audio analysis service for waveform previews and segment recommendations."""

import asyncio
import logging

import numpy as np

logger = logging.getLogger(__name__)


async def analyze_audio(file_path: str, clip_duration: int = 60) -> dict:
    """Analyze audio and produce recommendations for clip review.

    Returns:
        dict with keys:
            - suggested_start: float, best start time in seconds
            - suggested_end: float, recommended end time in seconds
            - bpm: float, estimated BPM
            - energy: float, overall energy score (0-1)
            - duration: float, total duration
            - waveform: list[float], normalized bar values for preview UI
            - highlights: list[dict], recommended regions with relative scores
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
                "suggested_end": round(duration, 2),
                "bpm": _estimate_bpm(y, sr),
                "energy": _compute_energy(y),
                "duration": round(duration, 2),
                "waveform": _build_waveform(y),
                "highlights": [
                    {
                        "start": 0.0,
                        "end": round(duration, 2),
                        "score": 1.0,
                        "label": "Full track",
                    }
                ],
            }

        segment_scores = _score_segments(y, sr, clip_duration)
        suggested_start = segment_scores[0]["start"] if segment_scores else 0.0
        suggested_end = min(duration, suggested_start + clip_duration)
        bpm = _estimate_bpm(y, sr)
        energy = _compute_energy(y)

        return {
            "suggested_start": round(suggested_start, 2),
            "suggested_end": round(suggested_end, 2),
            "bpm": round(bpm, 1),
            "energy": round(energy, 4),
            "duration": round(duration, 2),
            "waveform": _build_waveform(y),
            "highlights": segment_scores[:3],
        }

    except Exception as e:
        logger.error(f"Audio analysis failed for {file_path}: {e}")
        return {
            "suggested_start": 0.0,
            "suggested_end": 0.0,
            "bpm": None,
            "energy": None,
            "duration": 0.0,
            "waveform": [],
            "highlights": [],
        }


def _score_segments(y: np.ndarray, sr: int, clip_duration: int) -> list[dict]:
    """Rank recommended segments for the UI."""
    import librosa

    hop_length = 512
    party_score = _compute_party_score(y, sr, hop_length)
    frames_per_clip = int(clip_duration * sr / hop_length)
    duration = librosa.get_duration(y=y, sr=sr)

    if len(party_score) <= frames_per_clip:
        return [{
            "start": 0.0,
            "end": round(duration, 2),
            "score": 1.0,
            "label": "Best match",
        }]

    cumsum = np.concatenate(([0.0], np.cumsum(party_score)))
    window_sums = cumsum[frames_per_clip:] - cumsum[:-frames_per_clip]
    max_score = float(window_sums.max() + 1e-8)

    _, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
    beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=hop_length)

    ranked_segments = []
    min_gap = max(clip_duration * 0.5, 15)
    for best_frame in np.argsort(window_sums)[::-1]:
        candidate_time = float(librosa.frames_to_time(best_frame, sr=sr, hop_length=hop_length))
        candidate_time = _snap_to_nearest_beat(candidate_time, beat_times)
        candidate_time = min(candidate_time, max(0.0, duration - clip_duration))
        if any(abs(candidate_time - segment["start"]) < min_gap for segment in ranked_segments):
            continue
        ranked_segments.append({
            "start": round(candidate_time, 2),
            "end": round(min(duration, candidate_time + clip_duration), 2),
            "score": round(float(window_sums[best_frame] / max_score), 4),
            "label": _segment_label(len(ranked_segments)),
        })
        if len(ranked_segments) == 3:
            break

    return ranked_segments


def _compute_party_score(y: np.ndarray, sr: int, hop_length: int) -> np.ndarray:
    """Combine loudness and onset activity into a recommendation score."""
    import librosa

    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    rms_norm = rms / (rms.max() + 1e-8)

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    onset_norm = onset_env / (onset_env.max() + 1e-8)

    return 0.6 * rms_norm[:len(onset_norm)] + 0.4 * onset_norm[:len(rms_norm)]


def _build_waveform(y: np.ndarray, bars: int = 160) -> list[float]:
    """Build normalized waveform bars for a compact equalizer-style preview."""
    if len(y) == 0:
        return []

    chunks = np.array_split(np.abs(y), bars)
    values = np.array([float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0 for chunk in chunks])
    max_value = float(values.max() or 1.0)
    normalized = np.clip(values / max_value, 0.05, 1.0)
    return [round(float(v), 4) for v in normalized]


def _snap_to_nearest_beat(candidate_time: float, beat_times: np.ndarray) -> float:
    """Snap a recommendation to the nearest beat when available."""
    if len(beat_times) == 0:
        return candidate_time
    nearest_beat_idx = int(np.argmin(np.abs(beat_times - candidate_time)))
    return float(beat_times[nearest_beat_idx])


def _segment_label(rank: int) -> str:
    labels = ["Best match", "Also strong", "Worth a look"]
    return labels[rank] if rank < len(labels) else "Suggested"


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
