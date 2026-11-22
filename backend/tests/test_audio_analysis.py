"""Highlight analysis: songs keep beat-based scoring; speech-like audio is scored differently.

Uses synthetic audio, so these pin behavior/invariants rather than real-world accuracy.
"""

import numpy as np
import pytest

pytest.importorskip("librosa")

from app.services import audio_analysis as aa  # noqa: E402

SR = 22050


def _click_track(seconds=30, bpm=120):
    y = np.zeros(seconds * SR, dtype=np.float32)
    t = np.arange(int(0.05 * SR)) / SR
    click = (np.sin(2 * np.pi * 440 * t) * np.hanning(len(t))).astype(np.float32)
    for beat in np.arange(0, seconds, 60 / bpm):
        i = int(beat * SR)
        y[i:i + len(click)] += click[: len(y) - i]
    return y


def _onset_env(y):
    import librosa

    return librosa.onset.onset_strength(y=y, sr=SR, hop_length=512)


def test_rhythmic_audio_scores_as_music_and_noise_does_not():
    rng = np.random.default_rng(0)
    assert aa._music_likeness(_onset_env(_click_track()), SR, 512) > 0.8
    noise = (0.3 * rng.standard_normal(30 * SR)).astype(np.float32)
    assert aa._music_likeness(_onset_env(noise), SR, 512) < 0.2


def test_very_short_audio_defaults_to_music():
    assert aa._music_likeness(np.zeros(10), SR, 512) == 1.0


def test_activity_score_prefers_talking_over_loud_steady_noise():
    rng = np.random.default_rng(3)
    y = 0.004 * rng.standard_normal(240 * SR)
    # steady loud noise 0-60s (decoy); bursty "speech" 120-180s
    y[: 60 * SR] += 0.45 * rng.standard_normal(60 * SR)
    i = 120 * SR
    while i < 180 * SR:
        n = int(rng.uniform(0.15, 0.35) * SR)
        t = np.arange(n) / SR
        y[i:i + n] += sum(np.sin(2 * np.pi * 120 * h * t) / h for h in range(1, 20)) * np.hanning(n) * 0.4
        i += n + int(rng.uniform(0.0, 1.0) * SR)
    y = y.astype(np.float32)

    score = aa._compute_activity_score(y, SR, 512, _onset_env(y))
    fps = SR / 512
    decoy = score[int(10 * fps):int(50 * fps)].mean()
    talking = score[int(125 * fps):int(175 * fps)].mean()
    assert talking > decoy


def test_pause_snap_stays_within_limit():
    times = np.array([10.0, 50.0])
    assert aa._snap_to_nearest(11.5, times, max_distance=3.0) == 10.0
    assert aa._snap_to_nearest(30.0, times, max_distance=3.0) == 30.0  # too far: unchanged
    assert aa._snap_to_nearest(30.0, times) in (10.0, 50.0)  # unbounded (beat snapping)
    assert aa._snap_to_nearest(30.0, np.array([])) == 30.0


def test_analysis_reports_music_likeness_and_valid_range():
    import soundfile as sf
    import tempfile, os

    y = np.tile(_click_track(30), 4)  # 120s, longer than a clip so scoring runs
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.wav")
        sf.write(path, y, SR)
        result = aa._analyze_sync(path)
    assert 0.0 <= result["music_likeness"] <= 1.0
    assert result["suggested_end"] > result["suggested_start"] >= 0.0
    assert result["suggested_end"] <= result["duration"] + 0.01
