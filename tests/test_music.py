from __future__ import annotations

import pytest
import numpy as np

from gt_trainer.audio import (
    AttackPitchTracker,
    compensate_input_latency,
    detect_pitch,
    playback_end_step,
    render_exercise,
    render_note_preview,
    render_practice_interval,
    rms_to_level,
)
from gt_trainer.models import Exercise, TabNote, format_tab_cell, parse_tab_cell
from gt_trainer.music import (
    PitchObservation,
    calibration_exercise,
    calibration_silent_click_steps,
    estimate_timing_calibration,
    evaluate_performance,
    exercise_duration_seconds,
    expected_events,
    format_duration,
    frequency_to_midi,
    midi_to_frequency,
    score_attempts,
)


def test_frequency_midi_round_trip() -> None:
    assert midi_to_frequency(69) == pytest.approx(440.0)
    assert frequency_to_midi(440.0) == pytest.approx(69.0)
    assert frequency_to_midi(midi_to_frequency(40)) == pytest.approx(40.0)


def test_exercise_duration_uses_bpm_and_last_note_end() -> None:
    exercise = Exercise(
        steps_per_beat=4,
        notes=[TabNote(step=15, string=5, fret=0, duration_steps=1)],
    )

    assert exercise_duration_seconds(exercise, 60) == pytest.approx(4.0)
    assert exercise_duration_seconds(exercise, 120) == pytest.approx(2.0)
    assert format_duration(64.25) == "1:04.2"


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0", (0, "")), ("24h", (24, "h")), ("7P", (7, "p")), ("9/", (9, "/")), ("9\\", (9, "\\"))],
)
def test_tab_cell_techniques(text: str, expected: tuple[int, str]) -> None:
    assert parse_tab_cell(text) == expected
    fret, technique = expected
    assert format_tab_cell(TabNote(0, 0, fret, technique=technique)) == text.lower()


@pytest.mark.parametrize("text", ["-1", "25", "h5", "5x", "5hh"])
def test_invalid_tab_cells(text: str) -> None:
    assert parse_tab_cell(text) is None


def test_input_latency_is_subtracted_safely() -> None:
    assert compensate_input_latency(1.0, 0.0058) == pytest.approx(0.9942)
    assert compensate_input_latency(0.002, 0.0058) == 0.0
    assert compensate_input_latency(1.0, float("nan")) == 1.0


def test_input_level_maps_rms_to_visible_range() -> None:
    assert rms_to_level(0.0) == 0.0
    assert rms_to_level(10 ** -1.5) == pytest.approx(0.5)
    assert rms_to_level(1.0) == 1.0


def test_note_preview_renders_and_normalizes_a_chord() -> None:
    audio = render_note_preview([40, 47, 52], duration=0.2, sample_rate=8_000)

    assert len(audio) == 1_600
    assert np.any(audio != 0)
    assert np.max(np.abs(audio)) <= 0.95


def test_practice_interval_has_two_silent_bars_then_one_click_bar() -> None:
    audio = render_practice_interval(60, 4, sample_rate=1_000)

    assert len(audio) == 12_000
    assert not np.any(audio[:8_000])
    assert np.any(audio[8_000:12_000])


def test_attack_tracker_keeps_attack_time_and_ignores_sustain() -> None:
    sample_rate = 48_000
    block_size = 1024
    tracker = AttackPitchTracker(sample_rate, analysis_samples=4096)

    def tone(frequency: float, block: int, amplitude: float = 0.3) -> np.ndarray:
        time = np.arange(block * block_size, (block + 1) * block_size) / sample_rate
        return (np.sin(2 * np.pi * frequency * time) * amplitude).astype(np.float32)

    assert tracker.process(np.zeros(block_size, dtype=np.float32), 0.0) is None
    assert tracker.process(tone(82.41, 0), 1.0) is None
    for index in range(1, 4):
        assert tracker.process(
            tone(82.41, index), 1.0 + index * block_size / sample_rate
        ) is None
    observation = tracker.process(tone(82.41, 4), 1.0 + 4 * block_size / sample_rate)

    assert observation is not None
    assert observation.time == pytest.approx(1.0 + block_size / sample_rate / 2)
    assert observation.midi == pytest.approx(40.0, abs=0.25)
    for index in range(5, 14):
        assert tracker.process(tone(82.41, index), 1.0 + index * block_size / sample_rate) is None

    assert tracker.process(tone(110.0, 14, 0.55), 1.0 + 14 * block_size / sample_rate) is None
    for index in range(15, 18):
        assert tracker.process(
            tone(110.0, index), 1.0 + index * block_size / sample_rate
        ) is None
    next_observation = tracker.process(
        tone(110.0, 18), 1.0 + 18 * block_size / sample_rate
    )
    assert next_observation is not None
    assert next_observation.midi == pytest.approx(45.0, abs=0.25)


def test_timing_calibration_uses_all_open_strings_and_rejects_outlier() -> None:
    exercise = calibration_exercise()
    events = expected_events(exercise, 90, count_in_beats=4)
    observations = [
        PitchObservation(
            time=expected_time + (0.31 if index == 0 else 0.12),
            midi=expected_midi,
            confidence=0.9,
            rms=0.2,
        )
        for index, (expected_time, expected_midi) in enumerate(events)
    ]

    estimate = estimate_timing_calibration(
        exercise, 90, observations, count_in_beats=4
    )

    assert estimate is not None
    assert estimate.offset_seconds == pytest.approx(0.12)
    assert set(estimate.errors_by_midi) == {40, 45, 50, 55, 59, 64}


def test_calibration_has_four_count_beats_before_each_of_six_notes() -> None:
    exercise = calibration_exercise()

    assert [(note.step, note.string) for note in exercise.notes] == [
        (0, 5), (7, 4), (14, 3), (21, 2), (28, 1), (35, 0),
    ]
    assert calibration_silent_click_steps(exercise) == {
        1, 2, 8, 9, 15, 16, 22, 23, 29, 30,
    }


def test_calibration_audio_has_two_silent_beats_before_countdown() -> None:
    exercise = calibration_exercise()
    audio = render_exercise(
        exercise,
        60,
        count_in_beats=0,
        include_notes=False,
        sample_rate=1_000,
        silent_click_steps=calibration_silent_click_steps(exercise),
    )

    assert not np.any(audio[1_000:2_000])
    assert not np.any(audio[2_000:3_000])
    assert np.any(audio[3_000:4_000])
    assert np.any(audio[7_000:8_000])


def test_playback_range_stops_at_last_remaining_note() -> None:
    exercise = Exercise(steps_per_beat=4, bars=8, notes=[
        TabNote(step=4, string=5, fret=0),
        TabNote(step=20, string=5, fret=2, duration_steps=2),
    ])

    assert playback_end_step(exercise) == 22
    assert playback_end_step(exercise, start_step=8) == 22
    assert playback_end_step(exercise, start_step=21) is None


def test_render_exercise_can_start_from_middle_and_trims_empty_tail() -> None:
    exercise = Exercise(steps_per_beat=4, bars=8, notes=[
        TabNote(step=4, string=5, fret=0),
        TabNote(step=20, string=5, fret=2),
    ])

    audio = render_exercise(
        exercise, 60, count_in_beats=0, sample_rate=1_000, start_step=8,
    )

    assert len(audio) == 3_750
    assert np.any(audio != 0)


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


def test_pitch_detector_rejects_runaway_peak_interpolation(monkeypatch) -> None:
    """A search-boundary peak must not produce a negative frequency."""
    samples = np.sin(2 * np.pi * 110 * np.arange(2048) / 48_000).astype(np.float32)
    correlation = np.zeros(4096, dtype=np.float64)
    correlation[0] = 1.0
    # max_lag is 738 at 48 kHz.  The last in-range value is the selected
    # maximum, while the first out-of-range value makes an unconstrained
    # parabolic correction jump to a negative lag.
    correlation[736] = 0.499
    correlation[737] = 0.5
    correlation[738] = 0.501001
    monkeypatch.setattr(np.fft, "irfft", lambda *args, **kwargs: correlation.copy())

    detected, confidence = detect_pitch(samples, 48_000)

    assert detected is not None
    assert np.isfinite(detected)
    assert 65.0 <= detected <= 1200.0
    assert confidence == pytest.approx(0.5)

