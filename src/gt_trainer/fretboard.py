from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .models import Exercise, STRING_NAMES, TabNote


class FretboardWidget(QWidget):
    """Fixed 0..24 fretboard that highlights notes at the playhead."""

    fret_count = 25
    note_names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

    def __init__(self) -> None:
        super().__init__()
        self.exercise = Exercise()
        self.playhead_step = -1
        self.setMinimumHeight(132)
        self.setMaximumHeight(152)

    def set_exercise(self, exercise: Exercise) -> None:
        self.exercise = exercise
        self.playhead_step = -1
        self.update()

    def set_playhead(self, step: int) -> None:
        self.playhead_step = step
        self.update()

    def active_notes(self) -> list[TabNote]:
        if self.playhead_step < 0:
            return []
        return sorted(
            (
                note
                for note in self.exercise.notes
                if note.step <= self.playhead_step < note.step + max(1, note.duration_steps)
            ),
            key=lambda note: (note.string, note.fret),
        )

    def position_markers(self) -> dict[tuple[int, int], str]:
        """Return every string/fret used by the score and its pitch class."""
        return {
            (note.string, note.fret): self.note_names[note.midi_note % 12]
            for note in self.exercise.notes
            if 0 <= note.string < 6 and 0 <= note.fret < self.fret_count
        }

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#121923"))
        painter.setPen(QPen(QColor("#303b50"), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)

        left = 44.0
        right = max(left + self.fret_count * 8.0, self.width() - 12.0)
        top = 31.0
        bottom = self.height() - 12.0
        fret_width = (right - left) / self.fret_count
        string_height = (bottom - top) / 6.0
        active = self.active_notes()
        active_positions = {(note.string, note.fret) for note in active}
        markers = self.position_markers()

        painter.setFont(QFont("Noto Sans CJK JP", 9))
        painter.setPen(QColor("#8f9caf"))
        painter.drawText(12, 19, "指板")

        for note in active:
            cell = QRectF(
                left + note.fret * fret_width,
                top + note.string * string_height,
                fret_width,
                string_height,
            )
            painter.fillRect(
                QRectF(left, cell.top(), right - left, string_height),
                QColor(99, 215, 181, 24),
            )
            painter.fillRect(
                QRectF(cell.left(), top, fret_width, bottom - top),
                QColor(107, 167, 255, 22),
            )

        painter.setFont(QFont("Noto Sans", 7))
        painter.setPen(QColor("#718096"))
        for fret in range(self.fret_count):
            x = left + fret * fret_width
            painter.drawText(
                QRectF(x, 17, fret_width, 13),
                Qt.AlignmentFlag.AlignCenter,
                str(fret),
            )

        for fret in range(self.fret_count + 1):
            x = left + fret * fret_width
            width = 2.0 if fret == 1 else 1.0
            painter.setPen(QPen(QColor("#8b94a5"), width))
            painter.drawLine(int(x), int(top), int(x), int(bottom))

        painter.setFont(QFont("Noto Sans", 8, QFont.Weight.Bold))
        for string, name in enumerate(STRING_NAMES):
            y = top + (string + 0.5) * string_height
            painter.setPen(QColor("#c3cedd"))
            painter.drawText(
                QRectF(10, y - string_height / 2, left - 15, string_height),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{string + 1} {name}",
            )
            thickness = 1.0 + string * 0.16
            painter.setPen(QPen(QColor("#8f9caf"), thickness))
            painter.drawLine(int(left), int(y), int(right), int(y))

        for (string, fret), note_name in sorted(markers.items()):
            center = QRectF(
                left + fret * fret_width,
                top + string * string_height,
                fret_width,
                string_height,
            ).center()
            radius = max(4.0, min(7.0, fret_width * 0.32, string_height * 0.38))
            is_active = (string, fret) in active_positions
            painter.setPen(QPen(QColor("#d8fff3" if is_active else "#6ba7ff"), 1.5))
            painter.setBrush(QColor("#29b890" if is_active else "#18263a"))
            painter.drawEllipse(center, radius, radius)
            painter.setPen(QColor("#ffffff" if is_active else "#b9d5ff"))
            painter.setFont(QFont("Noto Sans", 7, QFont.Weight.Bold))
            painter.drawText(
                QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
                Qt.AlignmentFlag.AlignCenter,
                note_name,
            )

        painter.end()
