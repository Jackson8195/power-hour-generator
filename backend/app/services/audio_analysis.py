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

        segment_scores, music_likeness = _score_segments(y, sr, clip_duration)
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
            "music_likeness": round(music_likeness, 3),
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


# Max distance a recommendation may move to land on a pause (non-rhythmic audio only).
PAUSE_SNAP_SECONDS = 3.0


def _score_segments(y: np.ndarray, sr: int, clip_duration: int) -> tuple[list[dict], float]:
    """Rank recommended segments for the UI.

    Returns ``(segments, music_likeness)``. Songs are scored on loudness + onset activity and
    snapped to the beat. Speech, sketches, and other non-music audio have no beat to snap to
    and "loud" is a poor proxy for "good", so they are scored on sustained activity (no dead
    air) plus dynamic moments, and snapped to pauses so a clip doesn't start mid-word. The two
    are blended by how rhythmic the audio is, so a misjudged clip degrades gracefully.
    """
    import librosa

    hop_length = 512
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    music_likeness = _music_likeness(onset_env, sr, hop_length)
    party = _compute_party_score(y, sr, hop_length, onset_env)
    activity = _compute_activity_score(y, sr, hop_length, onset_env)
    n = min(len(party), len(activity))
    score = music_likeness * party[:n] + (1.0 - music_likeness) * activity[:n]
    frames_per_clip = int(clip_duration * sr / hop_length)
    duration = librosa.get_duration(y=y, sr=sr)

    if len(score) <= frames_per_clip:
        return [{
            "start": 0.0,
            "end": round(duration, 2),
            "score": 1.0,
            "label": "Best match",
        }], music_likeness

    cumsum = np.concatenate(([0.0], np.cumsum(score)))
    window_sums = cumsum[frames_per_clip:] - cumsum[:-frames_per_clip]
    max_score = float(window_sums.max() + 1e-8)

    rhythmic = music_likeness >= 0.5
    if rhythmic:
        _, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
        snap_times = librosa.frames_to_time(beats, sr=sr, hop_length=hop_length)
    else:
        snap_times = _find_pauses(y, sr, hop_length)
    snap_limit = None if rhythmic else PAUSE_SNAP_SECONDS

    ranked_segments = []
    min_gap = max(clip_duration * 0.5, 15)
    for best_frame in np.argsort(window_sums)[::-1]:
        candidate_time = float(librosa.frames_to_time(best_frame, sr=sr, hop_length=hop_length))
        candidate_time = _snap_to_nearest(candidate_time, snap_times, snap_limit)
        candidate_time = min(candidate_time, max(0.0, duration - clip_duration))
        if any(abs(candidate_time - segment["start"]) < min_gap for segment in ranked_segments):
            continue
        end_time = min(duration, candidate_time + clip_duration)
        if not rhythmic:
            end_time = _snap_to_nearest(end_time, snap_times, snap_limit)
            end_time = min(duration, max(end_time, candidate_time + clip_duration * 0.5))
        ranked_segments.append({
            "start": round(candidate_time, 2),
            "end": round(end_time, 2),
            "score": round(float(window_sums[best_frame] / max_score), 4),
            "label": _segment_label(len(ranked_segments)),
        })
        if len(ranked_segments) == 3:
            break

    return ranked_segments, music_likeness


def _music_likeness(onset_env: np.ndarray, sr: int, hop_length: int) -> float:
    """0..1 estimate of how rhythmic/musical the audio is.

    Uses the strength of the onset envelope's autocorrelation peak in the 60-240 BPM range.
    Measured on 60 real song clips: median 0.53, 10th percentile 0.36; steady noise ~0.06 and
    a synthetic syllable-rate speech signal ~0.23. The ramp below maps 0.15 -> 0, 0.45 -> 1.
    It is a heuristic, not a classifier: weakly rhythmic songs land mid-range and get a
    blended score rather than a hard switch.
    """
    import librosa

    if len(onset_env) < int(2 * sr / hop_length):
        return 1.0
    ac = librosa.autocorrelate(onset_env - onset_env.mean())
    ac = ac / (ac[0] + 1e-9)
    lo, hi = int(0.25 * sr / hop_length), int(1.0 * sr / hop_length)
    peak = float(ac[lo:hi].max()) if hi < len(ac) else 0.0
    return float(np.clip((peak - 0.15) / 0.30, 0.0, 1.0))


def _smooth(x: np.ndarray, frames: int) -> np.ndarray:
    kernel = np.ones(max(frames, 1)) / max(frames, 1)
    return np.convolve(x, kernel, mode="same")


def _compute_activity_score(
    y: np.ndarray, sr: int, hop_length: int, onset_env: np.ndarray
) -> np.ndarray:
    """Score for non-music audio: sound that is present and *changing* (speech, banter, events).

    Raw loudness is deliberately not rewarded: steady loud noise (crowd, wind, a vacuum) would
    otherwise beat actual content. Instead we reward sound being present (no dead air),
    modulation over time (speech/laughter fluctuate; steady noise doesn't), and onsets.
    """
    import librosa

    frames_per_sec = sr / hop_length
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    rms_s = _smooth(rms, int(0.25 * frames_per_sec))

    # Is there actual sound nearby, as opposed to silence or room tone?
    active = (rms_s > 0.15 * np.percentile(rms_s, 95)).astype(float)
    activity = _smooth(active, int(2.0 * frames_per_sec))

    # Modulation: local spread of log-energy over ~1.5s. High for speech, low for steady noise.
    log_rms = np.log(rms_s + 1e-4)
    win = max(int(1.5 * frames_per_sec), 2)
    mean = _smooth(log_rms, win)
    modulation = np.sqrt(np.clip(_smooth(log_rms ** 2, win) - mean ** 2, 0.0, None))
    modulation = np.clip(modulation / (np.percentile(modulation, 95) + 1e-8), 0.0, 1.0)

    onset_norm = onset_env / (onset_env.max() + 1e-8)
    onset_s = _smooth(onset_norm, int(0.5 * frames_per_sec))
    onset_s = onset_s / (onset_s.max() + 1e-8)

    n = min(len(activity), len(modulation), len(onset_s))
    return 0.35 * activity[:n] + 0.40 * modulation[:n] + 0.25 * onset_s[:n]


def _find_pauses(y: np.ndarray, sr: int, hop_length: int) -> np.ndarray:
    """Times (s) of quiet gaps: natural places to start or end a clip."""
    import librosa

    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    rms_s = _smooth(rms, 3)
    quiet = rms_s < 0.2 * float(np.percentile(rms_s, 90) + 1e-8)
    pauses = []
    i = 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            pauses.append((i + j - 1) / 2)  # centre of the quiet run
            i = j
        else:
            i += 1
    return librosa.frames_to_time(np.array(pauses), sr=sr, hop_length=hop_length)


def _compute_party_score(
    y: np.ndarray, sr: int, hop_length: int, onset_env: np.ndarray | None = None
) -> np.ndarray:
    """Combine loudness and onset activity into a recommendation score."""
    import librosa

    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    rms_norm = rms / (rms.max() + 1e-8)

    if onset_env is None:
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


def _snap_to_nearest(
    candidate_time: float, times: np.ndarray, max_distance: float | None = None
) -> float:
    """Snap to the nearest time in times; unchanged if none is within max_distance."""
    if len(times) == 0:
        return candidate_time
    nearest = float(times[int(np.argmin(np.abs(times - candidate_time)))])
    if max_distance is not None and abs(nearest - candidate_time) > max_distance:
        return candidate_time
    return nearest


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
