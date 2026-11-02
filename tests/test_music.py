from __future__ import annotations

import pytest
import numpy as np

from gt_trainer.audio import detect_pitch
from gt_trainer.models import Exercise, TabNote
from gt_trainer.music import (
    PitchObservation,
    evaluate_performance,
    frequency_to_midi,
    midi_to_frequency,
    score_attempts,
)


def test_frequency_midi_round_trip() -> None:
    assert midi_to_frequency(69) == pytest.approx(440.0)
    assert frequency_to_midi(440.0) == pytest.approx(69.0)
    assert frequency_to_midi(midi_to_frequency(40)) == pytest.approx(40.0)


def test_evaluation_matches_pitch_and_timing() -> None:
    exercise = Exercise(steps_per_beat=4, notes=[
        TabNote(step=0, string=5, fret=0),
        TabNote(step=4, string=5, fret=2),
    ])
    observations = [
        PitchObservation(time=2.02, midi=40.1, confidence=0.9, rms=0.2),
        PitchObservation(time=2.53, midi=42.0, confidence=0.9, rms=0.2),
    ]
    attempts = evaluate_performance(exercise, 120, observations, count_in_beats=4)
    assert len(attempts) == 2
    assert all(attempt.correct_pitch for attempt in attempts)
    assert all(attempt.correct_timing for attempt in attempts)
    pitch, timing, total = score_attempts(attempts)
    assert pitch == 100.0
    assert timing > 85.0
    assert total > 90.0


def test_missed_note_scores_zero() -> None:
    exercise = Exercise(notes=[TabNote(step=0, string=0, fret=0)])
    attempts = evaluate_performance(exercise, 90, [])
    assert attempts[0].detected_midi is None
    assert score_attempts(attempts) == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("frequency", [82.41, 220.0, 440.0])
def test_pitch_detector_on_clean_tone(frequency: float) -> None:
    sample_rate = 48_000
    time = np.arange(4096) / sample_rate
    samples = np.sin(2 * np.pi * frequency * time).astype(np.float32) * 0.2
    detected, confidence = detect_pitch(samples, sample_rate)
    assert detected == pytest.approx(frequency, rel=0.015)
    assert confidence > 0.5

