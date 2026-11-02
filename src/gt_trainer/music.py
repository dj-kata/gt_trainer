from __future__ import annotations

import math
from dataclasses import dataclass

from .models import Exercise, NoteAttempt


def midi_to_frequency(note: float) -> float:
    return 440.0 * (2.0 ** ((note - 69.0) / 12.0))


def frequency_to_midi(frequency: float) -> float:
    if frequency <= 0:
        raise ValueError("frequency must be positive")
    return 69.0 + 12.0 * math.log2(frequency / 440.0)


def midi_name(note: float | int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    rounded = round(note)
    return f"{names[rounded % 12]}{rounded // 12 - 1}"


@dataclass(slots=True)
class PitchObservation:
    time: float
    midi: float
    confidence: float
    rms: float


def expected_events(exercise: Exercise, bpm: int, count_in_beats: int = 0) -> list[tuple[float, int]]:
    seconds_per_step = 60.0 / bpm / exercise.steps_per_beat
    offset = count_in_beats * 60.0 / bpm
    return sorted((offset + n.step * seconds_per_step, n.midi_note) for n in exercise.notes)


def evaluate_performance(
    exercise: Exercise,
    bpm: int,
    observations: list[PitchObservation],
    *,
    count_in_beats: int = 0,
    timing_window: float = 0.22,
    pitch_tolerance_cents: float = 60.0,
) -> list[NoteAttempt]:
    """Match each expected note to one nearby observation.

    A greedy match is intentional: scale exercises are monophonic and chronological,
    and each detected attack must be consumed only once.
    """
    attempts: list[NoteAttempt] = []
    unused = set(range(len(observations)))
    for expected_time, expected_midi in expected_events(exercise, bpm, count_in_beats):
        candidates = [
            i for i in unused
            if abs(observations[i].time - expected_time) <= timing_window
        ]
        if not candidates:
            attempts.append(NoteAttempt(expected_midi, expected_time, None, None, None, None, False, False))
            continue
        best = min(
            candidates,
            key=lambda i: abs(observations[i].time - expected_time)
            + abs(observations[i].midi - expected_midi) * 0.025,
        )
        unused.remove(best)
        obs = observations[best]
        cents = (obs.midi - expected_midi) * 100.0
        timing_ms = (obs.time - expected_time) * 1000.0
        attempts.append(NoteAttempt(
            expected_midi=expected_midi,
            expected_time=expected_time,
            detected_midi=obs.midi,
            detected_time=obs.time,
            pitch_error_cents=cents,
            timing_error_ms=timing_ms,
            correct_pitch=abs(cents) <= pitch_tolerance_cents,
            correct_timing=abs(timing_ms) <= timing_window * 1000.0,
        ))
    return attempts


def score_attempts(attempts: list[NoteAttempt]) -> tuple[float, float, float]:
    if not attempts:
        return 0.0, 0.0, 0.0
    pitch = sum(a.correct_pitch for a in attempts) / len(attempts) * 100.0
    timing_values = []
    for attempt in attempts:
        if attempt.timing_error_ms is None:
            timing_values.append(0.0)
        else:
            timing_values.append(max(0.0, 1.0 - abs(attempt.timing_error_ms) / 220.0) * 100.0)
    timing = sum(timing_values) / len(timing_values)
    return pitch, timing, pitch * 0.55 + timing * 0.45

