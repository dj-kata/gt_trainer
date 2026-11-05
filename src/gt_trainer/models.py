from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import re
from typing import Any


STRING_NAMES = ("e", "B", "G", "D", "A", "E")
# MIDI notes for standard tuning, displayed from the first/high string.
OPEN_STRING_MIDI = (64, 59, 55, 50, 45, 40)
TAB_CELL_PATTERN = re.compile(r"^(?P<fret>[0-9]|1[0-9]|2[0-4])(?P<technique>[hHpPsS/\\]?)$")


def parse_tab_cell(value: str) -> tuple[int, str] | None:
    """Parse a fret and optional transition marker from one TAB cell."""
    match = TAB_CELL_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    return int(match.group("fret")), match.group("technique").lower()


def format_tab_cell(note: "TabNote") -> str:
    return f"{note.fret}{note.technique}"


@dataclass(slots=True)
class TabNote:
    step: int
    string: int
    fret: int
    duration_steps: int = 1
    # Transition from this note to the next: h, p, s, /, or \.
    technique: str = ""

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
    key_root: int | None = None
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
class PracticeMenuItem:
    exercise_id: int
    bpm: int = 90


@dataclass(slots=True)
class PracticeMenu:
    id: int | None = None
    name: str = "新しい練習メニュー"
    items: list[PracticeMenuItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PracticeMenu":
        data = dict(value)
        data["items"] = [PracticeMenuItem(**item) for item in data.get("items", [])]
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

