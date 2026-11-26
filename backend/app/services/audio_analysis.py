"""Audio analysis service for waveform previews and segment recommendations."""

import asyncio
import logging
import subprocess
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


async def analyze_audio(
    file_path: str, clip_duration: int = 60, segment_count: int = 1, music_likeness: float | None = None
) -> dict:
    """Analyze audio and produce recommendations for clip review.

    ``segment_count`` > 1 additionally asks for that many non-overlapping clip ranges
    (used by the AI flow to cut several clips from one compilation video).
    ``music_likeness`` overrides the measured value (0.0 = score as speech/talk only, used
    by AI video transitions so a moment lands on a line rather than crowd noise).

    Returns:
        dict with keys:
            - suggested_start: float, best start time in seconds
            - suggested_end: float, recommended end time in seconds
            - bpm: float, estimated BPM
            - energy: float, overall energy score (0-1)
            - duration: float, total duration
            - waveform: list[float], normalized bar values for preview UI
            - highlights: list[dict], recommended regions with relative scores
            - segments: list[dict], up to ``segment_count`` non-overlapping ranges, best first
    """
    # Run CPU-intensive analysis in a thread pool
    return await asyncio.to_thread(_analyze_sync, file_path, clip_duration, segment_count, music_likeness)


# Sources longer than this skip the second full-length beat_track pass for BPM.
LONG_SOURCE_SECONDS = 600


ANALYSIS_SAMPLE_RATE = 22050


def _load_audio(file_path: str, sr: int = ANALYSIS_SAMPLE_RATE) -> tuple[np.ndarray, int]:
    """Mono float audio at ``sr``.

    librosa first (unchanged behaviour wherever it can read the file). librosa 1.0 dropped its
    audioread fallback, so it can no longer open MP4/M4A downloads at all; for those, decode
    with ffmpeg (always present: the render pipeline needs it) and hand librosa the samples.
    """
    import librosa

    try:
        return librosa.load(file_path, sr=sr, mono=True)
    except Exception as exc:
        logger.info("librosa could not read %s (%s); decoding with ffmpeg", file_path, exc)

    from app.core.config import settings

    proc = subprocess.run(
        [settings.ffmpeg_path, "-v", "error", "-nostdin", "-i", file_path,
         "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"ffmpeg could not decode audio: {proc.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(proc.stdout, dtype=np.float32).copy(), sr


def _analyze_sync(
    file_path: str, clip_duration: int = 60, segment_count: int = 1, music_likeness: float | None = None
) -> dict:
    """Synchronous audio analysis (runs in thread pool)."""
    import librosa

    try:
        # Load audio (mono, 22050 Hz for analysis speed)
        y, sr = _load_audio(file_path)
        duration = librosa.get_duration(y=y, sr=sr)

        if duration <= clip_duration:
            full = {"start": 0.0, "end": round(duration, 2), "score": 1.0}
            return {
                "suggested_start": 0.0,
                "suggested_end": round(duration, 2),
                "bpm": _estimate_bpm(y, sr),
                "energy": _compute_energy(y),
                "duration": round(duration, 2),
                "waveform": _build_waveform(y),
                "highlights": [{**full, "label": "Full track"}],
                "segments": [full],
            }

        features = _segment_features(y, sr, clip_duration, music_likeness)
        music_likeness = features.music_likeness
        rhythmic = music_likeness >= 0.5
        # Long talk/compilation sources have many good moments: offer a few more to the reviewer.
        highlight_count = 5 if (not rhythmic and duration >= LONG_SOURCE_SECONDS) else 3
        segment_scores = _rank_highlights(features, highlight_count)
        segments = (
            _rank_non_overlapping(features, segment_count)
            if segment_count > 1
            else [{k: s[k] for k in ("start", "end", "score")} for s in segment_scores[:1]]
        )
        suggested_start = segment_scores[0]["start"] if segment_scores else 0.0
        suggested_end = segment_scores[0]["end"] if segment_scores else min(duration, clip_duration)
        if rhythmic:
            suggested_end = min(duration, suggested_start + clip_duration)
        if duration >= LONG_SOURCE_SECONDS:
            bpm = _tempo_from_onsets(features.onset_env, sr, features.hop_length)
        else:
            bpm = _estimate_bpm(y, sr)
        energy = _compute_energy(y)

        return {
            "suggested_start": round(suggested_start, 2),
            "suggested_end": round(suggested_end, 2),
            "bpm": round(bpm, 1),
            "energy": round(energy, 4),
            "duration": round(duration, 2),
            "waveform": _build_waveform(y),
            "highlights": segment_scores,
            "segments": segments,
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
            "segments": [],
        }


# Max distance a recommendation may move to land on a pause (non-rhythmic audio only).
PAUSE_SNAP_SECONDS = 3.0
# Max distance a non-music start may move to land on a content change (e.g. the next bit of
# a compilation). Preferred over a plain pause: starting a clip at the top of a bit reads best.
BOUNDARY_SNAP_SECONDS = 6.0
# YouTube intros ("hey guys, welcome back") and end screens ("subscribe!") are poor clip
# material in non-music videos; the activity score is damped across them.
INTRO_SECONDS = 10.0
OUTRO_SECONDS = 20.0


@dataclass
class _SegmentFeatures:
    score: np.ndarray            # per-frame blended score
    window_sums: np.ndarray      # score summed over each clip-length window, by start frame
    music_likeness: float
    onset_env: np.ndarray
    snap_times: np.ndarray       # beats (rhythmic) or pauses (non-rhythmic)
    boundary_times: np.ndarray   # content changes (non-rhythmic only; empty for songs)
    duration: float
    clip_duration: int
    sr: int
    hop_length: int

    @property
    def rhythmic(self) -> bool:
        return self.music_likeness >= 0.5


def _segment_features(
    y: np.ndarray, sr: int, clip_duration: int, likeness_override: float | None = None
) -> _SegmentFeatures:
    """Compute everything the window rankers need, once per source.

    Songs are scored on loudness + onset activity and snapped to the beat. Speech, sketches,
    and other non-music audio have no beat to snap to and "loud" is a poor proxy for "good",
    so they are scored on sustained activity (no dead air) plus dynamic moments, damped over
    intros/end screens, and snapped to content changes or pauses so a clip doesn't start
    mid-word. The two are blended by how rhythmic the audio is, so a misjudged clip degrades
    gracefully.
    """
    import librosa

    hop_length = 512
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    music_likeness = _music_likeness(onset_env, sr, hop_length)
    if likeness_override is not None:
        music_likeness = float(min(1.0, max(0.0, likeness_override)))
    party = _compute_party_score(y, sr, hop_length, onset_env)
    activity = _compute_activity_score(y, sr, hop_length, onset_env)
    n = min(len(party), len(activity))
    duration = librosa.get_duration(y=y, sr=sr)
    if music_likeness < 1.0:
        activity = activity[:n] * _edge_weights(n, sr, hop_length, duration, clip_duration)
    score = music_likeness * party[:n] + (1.0 - music_likeness) * activity[:n]
    frames_per_clip = int(clip_duration * sr / hop_length)

    if len(score) > frames_per_clip:
        cumsum = np.concatenate(([0.0], np.cumsum(score)))
        window_sums = cumsum[frames_per_clip:] - cumsum[:-frames_per_clip]
    else:
        window_sums = np.array([])

    boundary_times = np.array([])
    if music_likeness >= 0.5:
        _, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=hop_length)
        snap_times = librosa.frames_to_time(beats, sr=sr, hop_length=hop_length)
    else:
        snap_times = _find_pauses(y, sr, hop_length)
        boundary_times = _find_content_boundaries(y, sr, hop_length)

    return _SegmentFeatures(
        score=score, window_sums=window_sums, music_likeness=music_likeness,
        onset_env=onset_env, snap_times=snap_times, boundary_times=boundary_times,
        duration=duration, clip_duration=clip_duration, sr=sr, hop_length=hop_length,
    )


def _score_segments(y: np.ndarray, sr: int, clip_duration: int) -> tuple[list[dict], float]:
    """Top-3 recommended segments for the UI and the music likeness (kept for callers/tests)."""
    features = _segment_features(y, sr, clip_duration)
    return _rank_highlights(features, 3), features.music_likeness


def _place_window(f: _SegmentFeatures, frame: int) -> tuple[float, float]:
    """Snap a raw window start to a good cut point and choose its end."""
    import librosa

    start = float(librosa.frames_to_time(frame, sr=f.sr, hop_length=f.hop_length))
    if f.rhythmic:
        start = _snap_to_nearest(start, f.snap_times, None)
    else:
        snapped = _snap_to_nearest(start, f.boundary_times, BOUNDARY_SNAP_SECONDS)
        if snapped == start:
            snapped = _snap_to_nearest(start, f.snap_times, PAUSE_SNAP_SECONDS)
        start = snapped
    start = min(start, max(0.0, f.duration - f.clip_duration))
    end = min(f.duration, start + f.clip_duration)
    if not f.rhythmic:
        end = _snap_to_nearest(end, f.snap_times, PAUSE_SNAP_SECONDS)
        end = min(f.duration, max(end, start + f.clip_duration * 0.5))
    return start, end


def _whole_source(f: _SegmentFeatures) -> list[dict]:
    return [{"start": 0.0, "end": round(f.duration, 2), "score": 1.0, "label": "Best match"}]


def _rank_highlights(f: _SegmentFeatures, count: int) -> list[dict]:
    """Best ``count`` windows for the review UI; they may overlap by up to half a clip."""
    if len(f.window_sums) == 0:
        return _whole_source(f)
    max_score = float(f.window_sums.max() + 1e-8)
    ranked: list[dict] = []
    min_gap = max(f.clip_duration * 0.5, 15)
    for best_frame in np.argsort(f.window_sums)[::-1]:
        start, end = _place_window(f, int(best_frame))
        if any(abs(start - segment["start"]) < min_gap for segment in ranked):
            continue
        ranked.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "score": round(float(f.window_sums[best_frame] / max_score), 4),
            "label": _segment_label(len(ranked)),
        })
        if len(ranked) == count:
            break
    return ranked


def _rank_non_overlapping(f: _SegmentFeatures, count: int) -> list[dict]:
    """Up to ``count`` windows that never overlap, best first (several clips from one source)."""
    if len(f.window_sums) == 0:
        return [{k: v for k, v in s.items() if k != "label"} for s in _whole_source(f)]
    max_score = float(f.window_sums.max() + 1e-8)
    chosen: list[dict] = []
    frames_per_sec = f.sr / f.hop_length
    # Snapping can move a window by a few seconds, so reject raw starts near a chosen window
    # cheaply before snapping (keeps this fast on hour-long sources).
    margin = BOUNDARY_SNAP_SECONDS + PAUSE_SNAP_SECONDS
    for best_frame in np.argsort(f.window_sums)[::-1]:
        raw = best_frame / frames_per_sec
        if any(s["start"] - f.clip_duration - margin < raw < s["end"] + margin for s in chosen):
            continue
        start, end = _place_window(f, int(best_frame))
        if any(start < s["end"] + 1.0 and s["start"] < end + 1.0 for s in chosen):
            continue
        chosen.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "score": round(float(f.window_sums[best_frame] / max_score), 4),
        })
        if len(chosen) == count:
            break
    return chosen


def _edge_weights(
    n: int, sr: int, hop_length: int, duration: float, clip_duration: int
) -> np.ndarray:
    """Per-frame weight < 1 over the intro and end screen of a video long enough to skip them."""
    weights = np.ones(n)
    if duration < clip_duration + INTRO_SECONDS + OUTRO_SECONDS:
        return weights
    times = np.arange(n) * hop_length / sr
    intro = np.clip(times / INTRO_SECONDS, 0.0, 1.0)
    outro = np.clip((duration - times) / OUTRO_SECONDS, 0.0, 1.0)
    return weights * (0.35 + 0.65 * np.minimum(intro, outro))


def _find_content_boundaries(y: np.ndarray, sr: int, hop_length: int) -> np.ndarray:
    """Times (s) where the sound changes character: a new bit, scene, or speaker.

    Compares the average timbre (MFCCs, energy term dropped) of the ~2s before and after each
    half-second step and keeps the strong local peaks. In compilations these line up with cuts
    between clips, which are the most natural places to start one.
    """
    import librosa

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13, hop_length=hop_length)[1:]
    if mfcc.shape[1] == 0:
        return np.array([])
    mfcc = (mfcc - mfcc.mean(axis=1, keepdims=True)) / (mfcc.std(axis=1, keepdims=True) + 1e-8)
    block = max(int(0.5 * sr / hop_length), 1)
    n_blocks = mfcc.shape[1] // block
    side = 4  # blocks on each side (~2s)
    if n_blocks < 2 * side + 1:
        return np.array([])
    blocks = mfcc[:, : n_blocks * block].reshape(mfcc.shape[0], n_blocks, block).mean(axis=2).T
    cumsum = np.concatenate((np.zeros((1, blocks.shape[1])), np.cumsum(blocks, axis=0)))
    idx = np.arange(side, n_blocks - side + 1)
    before = (cumsum[idx] - cumsum[idx - side]) / side
    after = (cumsum[idx + side] - cumsum[idx]) / side
    novelty = np.linalg.norm(after - before, axis=1)
    threshold = max(float(np.percentile(novelty, 90)), 1.5 * float(np.median(novelty)))
    peaks = [
        int(idx[i])
        for i in range(len(novelty))
        if novelty[i] >= threshold and novelty[i] == novelty[max(0, i - side): i + side + 1].max()
    ]
    return np.array(peaks, dtype=float) * block * hop_length / sr


def _tempo_from_onsets(onset_env: np.ndarray, sr: int, hop_length: int) -> float:
    """Cheap BPM estimate from an existing onset envelope (for long sources)."""
    import librosa

    try:
        tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=sr, hop_length=hop_length)
    except AttributeError:  # librosa < 0.10
        tempo = librosa.beat.tempo(onset_envelope=onset_env, sr=sr, hop_length=hop_length)
    return float(np.atleast_1d(tempo)[0])


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
