from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .models import Exercise, STRING_NAMES, TabNote


class FretboardWidget(QWidget):
    """Fixed 0..24 fretboard that highlights notes at the playhead."""

    fret_count = 25
    note_names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    degree_intervals = {0: 1, 4: 3, 7: 5}
    degree_colors = {
        1: QColor("#df5865"),
        3: QColor("#4f88df"),
        5: QColor("#d5b83f"),
    }

    def __init__(self) -> None:
        super().__init__()
        self.exercise = Exercise()
        self.playhead_step = -1
        self.setMinimumHeight(144)
        self.setMaximumHeight(164)

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

    def degree_for_position(self, string: int, fret: int) -> int | None:
        if self.exercise.key_root is None:
            return None
        interval = (TabNote(0, string, fret).midi_note - self.exercise.key_root) % 12
        return self.degree_intervals.get(interval)

    def display_markers(self) -> dict[tuple[int, int], tuple[str, int | None]]:
        """Return score positions plus all root/third/fifth positions for the key."""
        markers = {
            position: (note_name, None)
            for position, note_name in self.position_markers().items()
        }
        if self.exercise.key_root is None:
            return markers
        for string in range(6):
            for fret in range(self.fret_count):
                degree = self.degree_for_position(string, fret)
                if degree is not None:
                    midi = TabNote(0, string, fret).midi_note
                    markers[(string, fret)] = (self.note_names[midi % 12], degree)
        return markers

    def marker_emphasis(self, string: int, fret: int) -> str:
        position = (string, fret)
        if position in {(note.string, note.fret) for note in self.active_notes()}:
            return "active"
        if position in self.position_markers():
            return "score"
        return "reference"

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#121923"))
        painter.setPen(QPen(QColor("#303b50"), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)

        left = 44.0
        right = max(left + self.fret_count * 8.0, self.width() - 12.0)
        top = 38.0
        bottom = self.height() - 12.0
        fret_width = (right - left) / self.fret_count
        string_height = (bottom - top) / 6.0
        active = self.active_notes()
        active_positions = {(note.string, note.fret) for note in active}
        score_positions = set(self.position_markers())
        markers = self.display_markers()

        painter.setFont(QFont("Noto Sans CJK JP", 9))
        painter.setPen(QColor("#8f9caf"))
        painter.drawText(12, 19, "指板")

        legend_x = left + 8
        painter.setFont(QFont("Noto Sans CJK JP", 7, QFont.Weight.Bold))
        for degree, label in ((1, "1度"), (3, "3度"), (5, "5度")):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self.degree_colors[degree])
            painter.drawEllipse(QRectF(legend_x, 7, 10, 10))
            painter.setPen(QColor("#cbd5e1"))
            painter.drawText(QRectF(legend_x + 13, 3, 28, 18), Qt.AlignmentFlag.AlignVCenter, label)
            legend_x += 48

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
                QRectF(x, 23, fret_width, 13),
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

        for note in active:
            cell = QRectF(
                left + note.fret * fret_width,
                top + note.string * string_height,
                fret_width,
                string_height,
            ).adjusted(1.5, 1.5, -1.5, -1.5)
            painter.setPen(QPen(QColor("#7dffd8"), 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(cell, 3, 3)

        for (string, fret), (note_name, degree) in sorted(markers.items()):
            marker_cell = QRectF(
                left + fret * fret_width,
                top + string * string_height,
                fret_width,
                string_height,
            )
            center = marker_cell.center()
            radius = max(4.0, min(7.0, fret_width * 0.32, string_height * 0.38))
            is_active = (string, fret) in active_positions
            is_score_position = (string, fret) in score_positions
            is_reference = not is_active and not is_score_position
            if is_reference:
                radius *= 0.68

            if degree is not None:
                fill = QColor(self.degree_colors[degree])
                if is_reference:
                    fill.setAlpha(52)
            else:
                fill = QColor("#29b890" if is_active else "#18263a")

            if is_active:
                outline = QColor("#ffffff")
                outline_width = 3.0
            elif is_score_position:
                outline = QColor("#d8fff3")
                outline_width = 2.0
            else:
                outline = QColor(self.degree_colors.get(degree, QColor("#6ba7ff")))
                outline.setAlpha(82)
                outline_width = 0.9
            painter.setPen(QPen(outline, outline_width))
            painter.setBrush(fill)
            painter.drawEllipse(center, radius, radius)
            if is_reference:
                text_color = QColor("#9aa7ba")
                text_color.setAlpha(105)
            else:
                text_color = (
                    QColor("#202020")
                    if degree == 5
                    else QColor("#ffffff" if degree else "#b9d5ff")
                )
            painter.setPen(text_color)
            painter.setFont(QFont(
                "Noto Sans",
                6 if is_reference else 7,
                QFont.Weight.Normal if is_reference else QFont.Weight.Bold,
            ))
            painter.drawText(
                QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2),
                Qt.AlignmentFlag.AlignCenter,
                note_name,
            )

        painter.end()
