from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .models import Exercise, TabNote


@dataclass(slots=True)
class DetectedNote:
    expected_index: int
    time: float
    midi: float
    timing_error_ms: float
    pitch_error_cents: float


class StaffWidget(QWidget):
    """Compact treble staff for expected and live-detected monophonic notes."""

    def __init__(self) -> None:
        super().__init__()
        self.exercise = Exercise()
        self.bpm = 90
        self.count_in_beats = 0
        self.detected: dict[int, DetectedNote] = {}
        self.scroll_offset = 0.0
        self.pixels_per_step = 38.0
        self.timeline_left = 32.0
        self.playhead_step = -1
        self.setMinimumHeight(148)
        self.setMaximumHeight(172)

    def set_exercise(
        self,
        exercise: Exercise,
        bpm: int | None = None,
        count_in_beats: int = 0,
        *,
        clear_detected: bool = True,
    ) -> None:
        self.exercise = exercise
        if bpm is not None:
            self.bpm = bpm
        self.count_in_beats = count_in_beats
        if clear_detected:
            self.detected.clear()
            self.playhead_step = -1
        self.update()

    def set_timeline_view(self, scroll_offset: float, pixels_per_step: float, left: float) -> None:
        """Match the TAB viewport's pixel scroll and column geometry."""
        self.scroll_offset = float(scroll_offset)
        self.pixels_per_step = max(1.0, float(pixels_per_step))
        self.timeline_left = float(left)
        self.update()

    def set_playhead(self, step: int) -> None:
        self.playhead_step = step
        self.update()

    def clear_detections(self) -> None:
        self.detected.clear()
        self.update()

    def add_observation(self, observed_time: float, midi: float) -> None:
        if not self.exercise.notes:
            return
        step_seconds = 60.0 / self.bpm / self.exercise.steps_per_beat
        body_offset = self.count_in_beats * 60.0 / self.bpm
        expected = sorted(self.exercise.notes, key=lambda note: (note.step, note.string))
        expected_times = [body_offset + note.step * step_seconds for note in expected]
        index = min(range(len(expected)), key=lambda i: abs(expected_times[i] - observed_time))
        timing_error_ms = (observed_time - expected_times[index]) * 1000.0
        pitch_error_cents = (midi - expected[index].midi_note) * 100.0
        candidate = DetectedNote(index, observed_time, midi, timing_error_ms, pitch_error_cents)
        previous = self.detected.get(index)
        # Sustained tones yield multiple observations.  Keep the one closest
        # to the expected attack so the overlay remains readable.
        if previous is None or abs(candidate.timing_error_ms) < abs(previous.timing_error_ms):
            self.detected[index] = candidate
            self.update()

    def _step_x(self, step: float) -> float:
        return self.timeline_left + (step + 0.5) * self.pixels_per_step - self.scroll_offset

    def _step_boundary_x(self, step: float) -> float:
        """Return the TAB column boundary for a step on the shared timeline."""
        return self.timeline_left + step * self.pixels_per_step - self.scroll_offset

    @staticmethod
    def _staff_position(midi: float) -> tuple[float, bool]:
        # Guitar treble notation is written one octave above sounding pitch.
        rounded = round(midi) + 12
        pitch_class = rounded % 12
        octave = rounded // 12 - 1
        natural_index = (0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6)[pitch_class]
        absolute_diatonic = octave * 7 + natural_index
        # Bottom line of a treble staff is E4.
        position = absolute_diatonic - (4 * 7 + 2)
        accidental = pitch_class in (1, 3, 6, 8, 10)
        return float(position), accidental

    def _note_y(self, midi: float, bottom: float, half_space: float) -> tuple[float, bool, float]:
        position, accidental = self._staff_position(midi)
        return bottom - position * half_space, accidental, position

    def _draw_note(
        self,
        painter: QPainter,
        x: float,
        midi: float,
        bottom: float,
        half_space: float,
        color: QColor,
        *,
        filled: bool,
    ) -> None:
        y, accidental, position = self._note_y(midi, bottom, half_space)
        painter.setPen(QPen(color, 1.6))
        painter.setBrush(color if filled else Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(x - 6, y - 4, 12, 8))
        painter.drawLine(int(x + 5), int(y), int(x + 5), int(y - 25))
        if accidental:
            painter.setFont(QFont("Noto Sans", 9))
            painter.drawText(QRectF(x - 17, y - 9, 10, 18), Qt.AlignmentFlag.AlignCenter, "♯")
        # Ledger lines outside the five-line staff.
        ledger = int(position // 2 * 2)
        if position < 0:
            for pos in range(ledger, 1, 2):
                line_y = bottom - pos * half_space
                painter.drawLine(int(x - 9), int(line_y), int(x + 9), int(line_y))
        elif position > 8:
            for pos in range(10, ledger + 1, 2):
                line_y = bottom - pos * half_space
                painter.drawLine(int(x - 9), int(line_y), int(x + 9), int(line_y))

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#121923"))
        painter.setPen(QPen(QColor("#303b50"), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)

        left = self.timeline_left
        right = max(left + 40.0, self.width() - 18.0)
        line_space = 11.0
        top = 38.0
        bottom = top + line_space * 4
        half_space = line_space / 2.0

        painter.setFont(QFont("Noto Sans CJK JP", 9))
        painter.setPen(QColor("#8f9caf"))
        painter.drawText(12, 20, "五線譜")
        painter.setFont(QFont("Segoe UI Symbol", 30))
        painter.setPen(QColor("#c3cedd"))
        painter.drawText(max(2, int(left - 39)), int(bottom + 8), "𝄞")

        painter.setPen(QPen(QColor("#718096"), 1))
        for line in range(5):
            y = top + line * line_space
            painter.drawLine(int(left), int(y), int(right), int(y))

        painter.save()
        painter.setClipRect(QRectF(left, top - 18, right - left, self.height() - top + 9))

        # Beat and bar guides. Their x positions use exactly the same pixel
        # width and scroll offset as the TAB columns above.  Guides sit on
        # column boundaries so they do not run through notes on the beat.
        steps_per_beat = max(1, self.exercise.steps_per_beat)
        steps_per_bar = steps_per_beat * max(1, self.exercise.beats_per_bar)
        for step in range(0, self.exercise.total_steps + 1, steps_per_beat):
            x = self._step_boundary_x(step)
            strong = step % steps_per_bar == 0
            if strong:
                painter.setPen(QPen(QColor("#64748b"), 2.0))
                painter.drawLine(int(x), int(top - 5), int(x), int(bottom + 7))
            elif step < self.exercise.total_steps:
                painter.setPen(QPen(QColor("#3b495e"), 1.0, Qt.PenStyle.DashLine))
                painter.drawLine(int(x), int(top), int(x), int(bottom))

        painter.setFont(QFont("Noto Sans CJK JP", 7, QFont.Weight.Bold))
        for bar_start in range(0, self.exercise.total_steps, steps_per_bar):
            x = self._step_boundary_x(bar_start)
            label_rect = QRectF(x + 4, top - 16, 18, 12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#334155"))
            painter.drawRoundedRect(label_rect, 3, 3)
            painter.setPen(QColor("#cbd5e1"))
            painter.drawText(
                label_rect,
                Qt.AlignmentFlag.AlignCenter,
                str(bar_start // steps_per_bar + 1),
            )

        expected = sorted(self.exercise.notes, key=lambda note: (note.step, note.string))
        for index, note in enumerate(expected):
            x = self._step_x(note.step)
            self._draw_note(painter, x, note.midi_note, bottom, half_space, QColor("#6ba7ff"), filled=False)
            if note.technique:
                labels = {"h": "H", "p": "P", "s": "S", "/": "S↗", "\\": "S↘"}
                next_step = expected[index + 1].step if index + 1 < len(expected) else note.step + 1
                next_x = self._step_x(next_step)
                painter.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
                painter.setPen(QColor("#c4b5fd"))
                label = labels.get(note.technique, note.technique.upper())
                painter.drawText(QRectF(x + 5, bottom + 10, max(20.0, next_x - x - 6), 17), label)

        step_seconds = 60.0 / self.bpm / max(1, self.exercise.steps_per_beat)
        body_offset = self.count_in_beats * 60.0 / self.bpm
        for index, detected in self.detected.items():
            body_step = (detected.time - body_offset) / step_seconds
            if not -0.5 <= body_step <= self.exercise.total_steps - 0.5:
                continue
            expected_note = expected[index]
            expected_x = self._step_x(expected_note.step)
            actual_x = self._step_x(body_step)
            good_pitch = abs(detected.pitch_error_cents) <= 60
            good_timing = abs(detected.timing_error_ms) <= 80
            color = QColor("#63d7b5" if good_pitch and good_timing else "#ffb35c" if good_pitch else "#ff6b6b")
            painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(expected_x), int(top - 9), int(actual_x), int(top - 9))
            self._draw_note(painter, actual_x, detected.midi, bottom, half_space, color, filled=True)
            painter.setFont(QFont("Noto Sans", 7))
            painter.setPen(color)
            sign = "+" if detected.timing_error_ms >= 0 else ""
            painter.drawText(QRectF(actual_x - 28, bottom + 27, 56, 15), Qt.AlignmentFlag.AlignCenter, f"{sign}{detected.timing_error_ms:.0f}ms")

        if 0 <= self.playhead_step < self.exercise.total_steps:
            playhead_x = self._step_x(self.playhead_step)
            painter.setPen(QPen(QColor("#63d7b5"), 2))
            painter.drawLine(int(playhead_x), int(top - 12), int(playhead_x), int(bottom + 44))

        painter.restore()

        painter.setFont(QFont("Noto Sans CJK JP", 8))
        painter.setPen(QColor("#718096"))
        painter.drawText(12, self.height() - 9, "青: 譜面　緑: 正確　橙: リズム差　赤: 音程差")

