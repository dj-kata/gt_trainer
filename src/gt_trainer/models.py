from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


STRING_NAMES = ("e", "B", "G", "D", "A", "E")
# MIDI notes for standard tuning, displayed from the first/high string.
OPEN_STRING_MIDI = (64, 59, 55, 50, 45, 40)


@dataclass(slots=True)
class TabNote:
    step: int
    string: int
    fret: int
    duration_steps: int = 1

    @property
    def midi_note(self) -> int:
        return OPEN_STRING_MIDI[self.string] + self.fret


@dataclass(slots=True)
class Exercise:
    id: int | None = None
    name: str = "新しい練習"
    steps_per_beat: int = 4
    beats_per_bar: int = 4
    bars: int = 1
    notes: list[TabNote] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def total_steps(self) -> int:
        return self.steps_per_beat * self.beats_per_bar * self.bars

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Exercise":
        data = dict(value)
        data["notes"] = [TabNote(**note) for note in data.get("notes", [])]
        return cls(**data)


@dataclass(slots=True)
class NoteAttempt:
    expected_midi: int
    expected_time: float
    detected_midi: float | None
    detected_time: float | None
    pitch_error_cents: float | None
    timing_error_ms: float | None
    correct_pitch: bool
    correct_timing: bool


@dataclass(slots=True)
class SessionResult:
    exercise_id: int | None
    exercise_name: str
    bpm: int
    started_at: str
    pitch_score: float
    timing_score: float
    total_score: float
    attempts: list[NoteAttempt]

