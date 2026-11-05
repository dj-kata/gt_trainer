from __future__ import annotations

import json

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QMimeData, QModelIndex, QRect, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QStyledItemDelegate,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import (
    Exercise,
    PracticeMenu,
    PracticeMenuItem,
    STRING_NAMES,
    TabNote,
    format_tab_cell,
    parse_tab_cell,
)
from .fretboard import FretboardWidget
from .music import exercise_duration_seconds, format_duration
from .staff import StaffWidget
from .storage import Storage


TAB_CLIPBOARD_MIME = "application/x-gt-trainer-tab"


class CalibrationDialog(QDialog):
    def __init__(self, exercise: Exercise, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.exercise = exercise
        self.notes = sorted(exercise.notes, key=lambda note: note.step)
        self.setWindowTitle("タイミング校正")
        self.setModal(True)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        title = QLabel("開放弦タイミング校正")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        help_text = QLabel(
            "4・3・2・1の次の強いクリックで、表示された開放弦を1回だけ弾いてください。\n"
            "演奏後はクリックが2拍止まり、次のカウントが始まります。全6音です。"
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        self.current = QLabel("次は6弦開放です\nカウント 4")
        self.current.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.current.setStyleSheet("font-size: 24px; font-weight: 700; padding: 18px;")
        layout.addWidget(self.current)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(self.notes))
        layout.addWidget(self.progress)
        cancel = QPushButton("中止")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel, alignment=Qt.AlignmentFlag.AlignRight)

    def set_step(self, step: int) -> None:
        if step < 0:
            first_string = self.notes[0].string + 1
            self.current.setText(
                f"次は{first_string}弦開放です\nカウント {abs(step)}"
            )
            return
        completed = sum(note.step <= step for note in self.notes)
        self.progress.setValue(completed)
        upcoming = next((note for note in self.notes if note.step >= step), None)
        if upcoming is None:
            self.current.setText("測定結果を計算しています…")
            self.progress.setValue(len(self.notes))
            return
        if upcoming.step == step:
            self.current.setText(
                f"今：{upcoming.string + 1}弦開放を鳴らしてください"
            )
            return
        previous = next((note for note in reversed(self.notes) if note.step < step), None)
        distance = step - previous.step if previous is not None else step + 1
        if distance <= 2:
            remaining = 3 - distance
            self.current.setText(
                f"次は{upcoming.string + 1}弦開放です\n休止中（あと{remaining}拍）"
            )
            return
        count = 7 - distance
        self.current.setText(
            f"次は{upcoming.string + 1}弦開放です\nカウント {count}"
        )


def card(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(18, 22, 18, 18)
    layout.setSpacing(12)
    return box, layout


class TabCellDelegate(QStyledItemDelegate):
    advance_requested = Signal(int, int)
    edit_committed = Signal(int, int)
    undo_requested = Signal()
    redo_requested = Signal()
    grid_shortcut_requested = Signal(int)

    def createEditor(self, parent, option, index):  # noqa: ANN001, N802
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setTextMargins(2, 0, 2, 0)
        editor.setValidator(QRegularExpressionValidator(
            QRegularExpression(r"(?:[0-9]|1[0-9]|2[0-4])(?:[hHpPsS/\\])?"), editor
        ))
        editor.installEventFilter(self)
        return editor

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: ANN001, N802
        rect = option.rect
        width = max(64, rect.width())
        x = min(rect.x(), max(0, editor.parent().width() - width))
        editor.setGeometry(QRect(x, rect.y(), width, rect.height()))

    def setModelData(self, editor, model, index) -> None:  # noqa: ANN001, N802
        super().setModelData(editor, model, index)
        if parse_tab_cell(str(model.data(index) or "")) is not None:
            self.edit_committed.emit(index.row(), index.column())

    def eventFilter(self, editor, event) -> bool:  # noqa: ANN001, N802
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            index = self._editing_index(editor)
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
            if index.isValid():
                QTimer.singleShot(0, lambda: self.advance_requested.emit(index.row(), index.column()))
            return True
        if event.type() == QEvent.Type.KeyPress and not editor.isModified():
            if event.matches(QKeySequence.StandardKey.Undo):
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                QTimer.singleShot(0, self.undo_requested.emit)
                return True
            if event.matches(QKeySequence.StandardKey.Redo):
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                QTimer.singleShot(0, self.redo_requested.emit)
                return True
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() in (
                Qt.Key.Key_C, Qt.Key.Key_X, Qt.Key.Key_V, Qt.Key.Key_Left, Qt.Key.Key_Right,
                Qt.Key.Key_Up, Qt.Key.Key_Down,
            ):
                key = event.key()
                self.closeEditor.emit(editor, QStyledItemDelegate.EndEditHint.NoHint)
                QTimer.singleShot(0, lambda: self.grid_shortcut_requested.emit(key))
                return True
        return super().eventFilter(editor, event)

    @staticmethod
    def _editing_index(editor: QWidget) -> QModelIndex:
        table = editor.parent()
        while table is not None and not isinstance(table, QTableWidget):
            table = table.parent()
        return table.currentIndex() if table is not None else QModelIndex()


class TimelineHeader(QHeaderView):
    row_height = 23

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.steps_per_beat = 4
        self.beats_per_bar = 4
        self.setSectionsClickable(False)
        self.setHighlightSections(False)
        self.setFixedHeight(self.row_height * 2)

    def configure(self, steps_per_beat: int, beats_per_bar: int) -> None:
        self.steps_per_beat = max(1, steps_per_beat)
        self.beats_per_bar = max(1, beats_per_bar)
        self.viewport().update()

    def sizeHint(self) -> QSize:  # noqa: N802
        hint = super().sizeHint()
        return QSize(hint.width(), self.row_height * 2)

    def bar_geometry(self, bar: int) -> QRect:
        steps_per_bar = self.steps_per_beat * self.beats_per_bar
        first_section = bar * steps_per_bar
        if first_section >= self.count():
            return QRect()
        last_section = min(self.count(), first_section + steps_per_bar)
        x = self.sectionViewportPosition(first_section)
        width = sum(self.sectionSize(section) for section in range(first_section, last_section))
        return QRect(x, 0, width, self.row_height)

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), QColor("#1b2432"))
        border = QPen(QColor("#334155"), 1)
        text_color = QColor("#cbd5e1")
        painter.setPen(border)

        for section in range(self.count()):
            x = self.sectionViewportPosition(section)
            width = self.sectionSize(section)
            rect = QRect(x, self.row_height, width, self.row_height)
            if not rect.intersects(self.viewport().rect()):
                continue
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            subdivision = section % self.steps_per_beat
            label = str(section // self.steps_per_beat % self.beats_per_bar + 1) if subdivision == 0 else "·"
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
            painter.setPen(border)

        steps_per_bar = self.steps_per_beat * self.beats_per_bar
        bar_count = (self.count() + steps_per_bar - 1) // steps_per_bar
        for bar in range(bar_count):
            rect = self.bar_geometry(bar)
            if not rect.intersects(self.viewport().rect()):
                continue
            painter.fillRect(rect.adjusted(0, 0, -1, -1), QColor("#243249"))
            painter.setPen(border)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(bar + 1))
        painter.end()


class TabGrid(QTableWidget):
    timeline_geometry_changed = Signal()
    audition_requested = Signal(list)

    def __init__(self) -> None:
        super().__init__(6, 16)
        self.steps_per_beat = 4
        self.beats_per_bar = 4
        self._edit_history: list[list[tuple[int, int, str, str]]] = []
        self._history_index = 0
        self._applying_history = False
        self._cell_values: dict[tuple[int, int], str] = {}
        self._playhead_step = -1
        self.setHorizontalHeader(TimelineHeader(self))
        self.setVerticalHeaderLabels(STRING_NAMES)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setMinimumSectionSize(18)
        self.verticalHeader().setDefaultSectionSize(22)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAlternatingRowColors(False)
        for row in range(self.rowCount()):
            self.setRowHeight(row, 22)
        delegate = TabCellDelegate(self)
        delegate.advance_requested.connect(self._advance_after_edit)
        delegate.edit_committed.connect(self._audition_column)
        delegate.undo_requested.connect(self.undo_edit)
        delegate.redo_requested.connect(self.redo_edit)
        delegate.grid_shortcut_requested.connect(self._handle_control_shortcut)
        self.setItemDelegate(delegate)
        self.configure(16, 4)
        self.itemChanged.connect(self._record_item_change)
        QTimer.singleShot(0, self._update_fixed_height)

    def _record_item_change(self, item: QTableWidgetItem) -> None:
        key = (item.row(), item.column())
        new_value = item.text()
        old_value = self._cell_values.get(key, "")
        self._cell_values[key] = new_value
        if self._applying_history or new_value == old_value:
            return
        del self._edit_history[self._history_index:]
        self._edit_history.append([(item.row(), item.column(), old_value, new_value)])
        self._history_index += 1

    def _reset_edit_history(self) -> None:
        self._edit_history.clear()
        self._history_index = 0
        self._cell_values = {
            (row, column): self.item(row, column).text()
            for row in range(self.rowCount())
            for column in range(self.columnCount())
            if self.item(row, column) is not None
        }

    def undo_edit(self) -> None:
        if self._history_index == 0:
            return
        self._history_index -= 1
        self._apply_history_changes(self._edit_history[self._history_index], use_new_values=False)

    def redo_edit(self) -> None:
        if self._history_index >= len(self._edit_history):
            return
        changes = self._edit_history[self._history_index]
        self._history_index += 1
        self._apply_history_changes(changes, use_new_values=True)

    def _apply_history_changes(
        self, changes: list[tuple[int, int, str, str]], *, use_new_values: bool,
    ) -> None:
        positions: list[tuple[int, int]] = []
        self._applying_history = True
        try:
            for row, column, old_value, new_value in changes:
                item = self.item(row, column)
                if item is None:
                    continue
                value = new_value if use_new_values else old_value
                item.setText(value)
                self._cell_values[(row, column)] = value
                positions.append((row, column))
        finally:
            self._applying_history = False
        self._select_positions(positions)

    def _apply_batch_edit(self, updates: dict[tuple[int, int], str]) -> None:
        changes: list[tuple[int, int, str, str]] = []
        for (row, column), new_value in updates.items():
            item = self.item(row, column)
            if item is not None and item.text() != new_value:
                changes.append((row, column, item.text(), new_value))
        if not changes:
            return
        del self._edit_history[self._history_index:]
        self._edit_history.append(changes)
        self._history_index += 1
        self._apply_history_changes(changes, use_new_values=True)

    def _select_positions(self, positions: list[tuple[int, int]]) -> None:
        if not positions:
            return
        self.clearSelection()
        first_row, first_column = positions[0]
        self.setCurrentCell(first_row, first_column)
        for row, column in positions:
            item = self.item(row, column)
            if item is not None:
                item.setSelected(True)
        self.scrollToItem(self.item(first_row, first_column), QAbstractItemView.ScrollHint.EnsureVisible)

    def _selected_note_items(self) -> list[QTableWidgetItem]:
        return [item for item in self.selectedItems() if parse_tab_cell(item.text().strip()) is not None]

    def copy_selection(self) -> None:
        selected = self.selectedItems()
        if not selected:
            return
        min_row = min(item.row() for item in selected)
        max_row = max(item.row() for item in selected)
        min_column = min(item.column() for item in selected)
        max_column = max(item.column() for item in selected)
        rows = []
        for row in range(min_row, max_row + 1):
            rows.append("\t".join(
                self.item(row, column).text() if self.item(row, column) is not None else ""
                for column in range(min_column, max_column + 1)
            ))
        tab_cells = [
            [row, column - min_column, self.item(row, column).text()]
            for row in range(min_row, max_row + 1)
            for column in range(min_column, max_column + 1)
            if self.item(row, column) is not None
        ]
        mime_data = QMimeData()
        mime_data.setText("\n".join(rows))
        mime_data.setData(
            TAB_CLIPBOARD_MIME,
            json.dumps({"cells": tab_cells}, ensure_ascii=False).encode("utf-8"),
        )
        QApplication.clipboard().setMimeData(mime_data)

    def cut_selection(self) -> None:
        selected = self.selectedItems()
        if not selected:
            return
        self.copy_selection()
        self._apply_batch_edit({(item.row(), item.column()): "" for item in selected})

    def paste_selection(self) -> None:
        anchor_column = max(0, self.currentColumn())
        mime_data = QApplication.clipboard().mimeData()
        if mime_data.hasFormat(TAB_CLIPBOARD_MIME):
            try:
                payload = json.loads(bytes(mime_data.data(TAB_CLIPBOARD_MIME)).decode("utf-8"))
                cells = payload["cells"]
            except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
                cells = []
            updates: dict[tuple[int, int], str] = {}
            for cell in cells:
                if not isinstance(cell, list) or len(cell) != 3:
                    continue
                row, column_offset, value = cell
                if not isinstance(row, int) or not isinstance(column_offset, int):
                    continue
                column = anchor_column + column_offset
                value = value.strip() if isinstance(value, str) else ""
                if (
                    0 <= row < self.rowCount()
                    and 0 <= column < self.columnCount()
                    and (not value or parse_tab_cell(value) is not None)
                ):
                    updates[(row, column)] = value
            self._apply_batch_edit(updates)
            return

        anchor_row = max(0, self.currentRow())
        clipboard_rows = QApplication.clipboard().text().splitlines()
        updates: dict[tuple[int, int], str] = {}
        for row_offset, clipboard_row in enumerate(clipboard_rows):
            row = anchor_row + row_offset
            if row >= self.rowCount():
                break
            for column_offset, value in enumerate(clipboard_row.split("\t")):
                column = anchor_column + column_offset
                if column >= self.columnCount():
                    break
                value = value.strip()
                if not value or parse_tab_cell(value) is not None:
                    updates[(row, column)] = value
        self._apply_batch_edit(updates)

    def move_selected_frets(self, delta: int) -> None:
        notes = self._selected_note_items()
        parsed_notes = [(item, parse_tab_cell(item.text().strip())) for item in notes]
        out_of_range = [
            item for item, parsed in parsed_notes
            if parsed is not None and not 0 <= parsed[0] + delta <= 24
        ]
        if out_of_range and QMessageBox.question(
            self,
            "フレット範囲の確認",
            "0〜24フレットの範囲外になる音符があります。\n"
            "範囲内の音符だけ移動しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        updates: dict[tuple[int, int], str] = {}
        for item, parsed in parsed_notes:
            if parsed is None or not 0 <= parsed[0] + delta <= 24:
                continue
            fret, technique = parsed
            updates[(item.row(), item.column())] = f"{fret + delta}{technique or ''}"
        self._apply_batch_edit(updates)

    def move_selected_strings(self, delta: int) -> None:
        notes = self._selected_note_items()
        if not notes or any(not 0 <= item.row() + delta < self.rowCount() for item in notes):
            return
        updates = {(item.row(), item.column()): "" for item in notes}
        destinations: list[tuple[int, int]] = []
        for item in notes:
            destination = (item.row() + delta, item.column())
            updates[destination] = item.text()
            destinations.append(destination)
        self._apply_batch_edit(updates)
        self._select_positions(destinations)

    def _handle_control_shortcut(self, key: int) -> bool:
        if key == Qt.Key.Key_C:
            self.copy_selection()
        elif key == Qt.Key.Key_X:
            self.cut_selection()
        elif key == Qt.Key.Key_V:
            self.paste_selection()
        elif key == Qt.Key.Key_Right:
            self.move_selected_frets(1)
        elif key == Qt.Key.Key_Left:
            self.move_selected_frets(-1)
        elif key == Qt.Key.Key_Up:
            self.move_selected_strings(-1)
        elif key == Qt.Key.Key_Down:
            self.move_selected_strings(1)
        else:
            return False
        return True

    def _update_fixed_height(self) -> None:
        header_height = max(self.horizontalHeader().height(), self.horizontalHeader().sizeHint().height())
        rows_height = sum(self.rowHeight(row) for row in range(self.rowCount()))
        scrollbar_height = self.horizontalScrollBar().sizeHint().height()
        self.setFixedHeight(header_height + rows_height + scrollbar_height + self.frameWidth() * 2 + 4)

    def showEvent(self, event) -> None:  # noqa: ANN001, N802
        super().showEvent(event)
        self._update_fixed_height()

    def resizeEvent(self, event) -> None:  # noqa: ANN001, N802
        super().resizeEvent(event)
        self.timeline_geometry_changed.emit()

    def _advance_after_edit(self, row: int, column: int) -> None:
        if column + 1 >= self.columnCount():
            return
        self.setCurrentCell(row, column + 1)
        next_item = self.item(row, column + 1)
        if next_item and self.editTriggers() != QAbstractItemView.EditTrigger.NoEditTriggers:
            self.editItem(next_item)

    def _audition_column(self, row: int, column: int) -> None:
        del row
        midi_notes = [
            note.midi_note
            for note in self.notes()
            if note.step == column
        ]
        if midi_notes:
            self.audition_requested.emit(midi_notes)

    def keyPressEvent(self, event) -> None:  # noqa: ANN001, N802
        if self.editTriggers() != QAbstractItemView.EditTrigger.NoEditTriggers:
            if event.matches(QKeySequence.StandardKey.Undo):
                self.undo_edit()
                event.accept()
                return
            if (
                event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and self._handle_control_shortcut(event.key())
            ):
                event.accept()
                return
            if event.matches(QKeySequence.StandardKey.Redo):
                self.redo_edit()
                event.accept()
                return
        if (
            event.key() == Qt.Key.Key_Delete
            and self.editTriggers() != QAbstractItemView.EditTrigger.NoEditTriggers
        ):
            items = self.selectedItems() or ([self.currentItem()] if self.currentItem() is not None else [])
            self._apply_batch_edit({(item.row(), item.column()): "" for item in items})
            event.accept()
            return
        super().keyPressEvent(event)

    def configure(self, total_steps: int, steps_per_beat: int, beats_per_bar: int = 4) -> None:
        values = self.notes()
        blocked = self.blockSignals(True)
        self.steps_per_beat = steps_per_beat
        self.beats_per_bar = beats_per_bar
        self.horizontalHeader().configure(steps_per_beat, beats_per_bar)
        self.setColumnCount(total_steps)
        labels = []
        for step in range(total_steps):
            beat = step // steps_per_beat + 1
            subdivision = step % steps_per_beat
            labels.append(str(beat) if subdivision == 0 else "·")
            self.setColumnWidth(step, 38)
        self.setHorizontalHeaderLabels(labels)
        for row in range(6):
            for column in range(total_steps):
                if not self.item(row, column):
                    item = QTableWidgetItem("")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.setItem(row, column, item)
                shade = QColor("#202735") if column % steps_per_beat == 0 else QColor("#181e29")
                self.item(row, column).setBackground(shade)
        for note in values:
            if note.step < total_steps:
                self.item(note.string, note.step).setText(format_tab_cell(note))
        self.blockSignals(blocked)
        self._playhead_step = -1
        self._reset_edit_history()
        self.timeline_geometry_changed.emit()
        QTimer.singleShot(0, self._update_fixed_height)

    def notes(self) -> list[TabNote]:
        notes: list[TabNote] = []
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                item = self.item(row, column)
                value = item.text().strip() if item else ""
                parsed = parse_tab_cell(value)
                if parsed is not None:
                    fret, technique = parsed
                    notes.append(TabNote(column, row, fret, technique=technique))
        return notes

    def load_exercise(self, exercise: Exercise) -> None:
        blocked = self.blockSignals(True)
        self.clearContents()
        self.configure(exercise.total_steps, exercise.steps_per_beat, exercise.beats_per_bar)
        for note in exercise.notes:
            if note.step < self.columnCount() and 0 <= note.string < 6:
                item = self.item(note.string, note.step)
                item.setText(format_tab_cell(note))
        self.blockSignals(blocked)
        self._reset_edit_history()

    def set_playhead(self, step: int) -> None:
        previous_step = self._playhead_step
        self._playhead_step = step if 0 <= step < self.columnCount() else -1
        for column in {previous_step, self._playhead_step}:
            if not 0 <= column < self.columnCount():
                continue
            shade = (
                QColor("#3b5564")
                if column == self._playhead_step
                else QColor("#202735") if column % self.steps_per_beat == 0 else QColor("#181e29")
            )
            for row in range(self.rowCount()):
                item = self.item(row, column)
                if item:
                    item.setBackground(shade)
        if 0 <= step < self.columnCount():
            self._scroll_to_playhead_bar(step)

    def _scroll_to_playhead_bar(self, step: int) -> None:
        """Page the timeline at bar boundaries instead of scrolling every step."""
        steps_per_bar = max(1, self.steps_per_beat * self.beats_per_bar)
        bar_start = step // steps_per_bar * steps_per_bar
        self.horizontalScrollBar().setValue(
            self.horizontalHeader().sectionPosition(bar_start)
        )


class EditorPage(QWidget):
    saved = Signal()
    preview_requested = Signal(Exercise, int)
    notes_audition_requested = Signal(list)
    stop_requested = Signal()

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        self.preview_bpm = 90
        self.exercise_id: int | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)

        heading = QLabel("TAB エディター")
        heading.setObjectName("pageTitle")
        root.addWidget(heading)
        description = QLabel(
            "0〜24のフレット番号を入力し Enter で右へ移動します。奏法は 5h（ハンマリング）、"
            "7p（プリング）、9/・9\\（スライド）です。ドラッグで複数選択し、Ctrl+C / Ctrl+V でコピー・"
            "貼り付け、Ctrl+X で切り取り、Ctrl+矢印でフレット・弦を移動できます。"
        )
        description.setObjectName("muted")
        root.addWidget(description)

        selector_row = QHBoxLayout()
        self.exercise_selector = QComboBox()
        self.exercise_selector.setMinimumWidth(280)
        self.exercise_selector.setToolTip("保存済みの譜面を選択して編集します。")
        self.exercise_selector.currentIndexChanged.connect(self._exercise_selected)
        selector_row.addWidget(QLabel("作成済み譜面"))
        selector_row.addWidget(self.exercise_selector, 1)
        root.addLayout(selector_row)

        controls = QHBoxLayout()
        self.name = QLineEdit("クロマチック練習")
        self.name.setPlaceholderText("練習名")
        self.bars = QSpinBox()
        self.bars.setRange(1, 256)
        self.bars.setValue(1)
        self.bars.setKeyboardTracking(False)
        self.bars.setAccelerated(True)
        self.bars.setToolTip(
            "1〜256小節。数値を直接入力するか、矢印を長押しして変更できます。"
        )
        self.subdivision = QComboBox()
        self.subdivision.addItem("4分音符", 1)
        self.subdivision.addItem("8分音符", 2)
        self.subdivision.addItem("12分音符", 3)
        self.subdivision.addItem("16分音符", 4)
        self.subdivision.addItem("24分音符", 6)
        self.subdivision.setCurrentIndex(self.subdivision.findData(4))
        self.key_root = QComboBox()
        self.key_root.addItem("未設定", None)
        for pitch_class, label in enumerate((
            "C", "C♯ / D♭", "D", "D♯ / E♭", "E", "F",
            "F♯ / G♭", "G", "G♯ / A♭", "A", "A♯ / B♭", "B",
        )):
            self.key_root.addItem(label, pitch_class)
        self.key_root.setToolTip("メジャーキー。3度は長3度、5度は完全5度として指板へ表示します。")
        controls.addWidget(QLabel("名前"))
        controls.addWidget(self.name, 2)
        controls.addWidget(QLabel("小節数"))
        controls.addWidget(self.bars)
        controls.addWidget(QLabel("分割"))
        controls.addWidget(self.subdivision)
        controls.addWidget(QLabel("Key"))
        controls.addWidget(self.key_root)
        self.duration_label = QLabel()
        self.duration_label.setObjectName("muted")
        controls.addWidget(self.duration_label)
        root.addLayout(controls)

        self.grid = TabGrid()
        root.addWidget(self.grid)
        self.staff = StaffWidget()
        root.addWidget(self.staff)
        self.fretboard = FretboardWidget()
        root.addWidget(self.fretboard)
        self.grid.horizontalScrollBar().valueChanged.connect(self._sync_staff_timeline)
        self.grid.timeline_geometry_changed.connect(self._sync_staff_timeline)
        self.grid.audition_requested.connect(self.notes_audition_requested.emit)
        buttons = QHBoxLayout()
        new_button = QPushButton("新規")
        new_button.clicked.connect(self.new_exercise)
        self.play_from_start_button = QPushButton("▶  先頭から")
        self.play_from_start_button.clicked.connect(lambda: self._request_preview(0))
        self.play_from_cursor_button = QPushButton("▶  カーソルから")
        self.play_from_cursor_button.setToolTip("選択中のTAB列から再生します。")
        self.play_from_cursor_button.clicked.connect(self._request_preview_from_cursor)
        self.stop_button = QPushButton("■  停止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        save = QPushButton("保存")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        buttons.addWidget(new_button)
        buttons.addStretch()
        buttons.addWidget(self.play_from_start_button)
        buttons.addWidget(self.play_from_cursor_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self.bars.valueChanged.connect(self._resize)
        self.subdivision.currentIndexChanged.connect(self._resize)
        self.key_root.currentIndexChanged.connect(self._update_staff)
        self.grid.itemChanged.connect(self._update_staff)
        self.reload_exercise_list()
        self._update_staff()
        QTimer.singleShot(0, self._sync_staff_timeline)

    def _sync_staff_timeline(self, *args) -> None:  # noqa: ANN002
        self.staff.set_timeline_view(
            self.grid.horizontalScrollBar().value(),
            self.grid.columnWidth(0) if self.grid.columnCount() else 38,
            self.grid.viewport().x(),
        )

    def _resize(self) -> None:
        steps = self.subdivision.currentData()
        self.grid.configure(self.bars.value() * 4 * steps, steps)
        self._update_staff()

    def _update_staff(self) -> None:
        exercise = self.build_exercise()
        self.staff.set_exercise(exercise)
        self.fretboard.set_exercise(exercise)
        self.duration_label.setText(
            f"演奏時間 {format_duration(exercise_duration_seconds(exercise, self.preview_bpm))}"
            f"（{self.preview_bpm} BPM）"
        )

    def set_bpm(self, bpm: int) -> None:
        self.preview_bpm = bpm
        self._update_staff()

    def _request_preview(self, start_step: int) -> None:
        self.preview_requested.emit(self.build_exercise(), start_step)

    def _request_preview_from_cursor(self) -> None:
        self._request_preview(max(0, self.grid.currentColumn()))

    def set_running(self, running: bool) -> None:
        self.exercise_selector.setEnabled(not running)
        self.play_from_start_button.setEnabled(not running)
        self.play_from_cursor_button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def build_exercise(self) -> Exercise:
        return Exercise(
            id=self.exercise_id,
            name=self.name.text().strip() or "名称未設定",
            steps_per_beat=self.subdivision.currentData(),
            beats_per_bar=4,
            bars=self.bars.value(),
            key_root=self.key_root.currentData(),
            notes=self.grid.notes(),
        )

    def save(self) -> None:
        exercise = self.build_exercise()
        if not exercise.notes:
            QMessageBox.warning(self, "入力を確認", "TABに1音以上入力してください。")
            return
        saved = self.storage.save_exercise(exercise)
        self.exercise_id = saved.id
        self.reload_exercise_list(saved.id)
        self.saved.emit()
        QMessageBox.information(self, "保存しました", f"「{saved.name}」を保存しました。")

    def load_exercise(self, exercise: Exercise) -> None:
        self.exercise_id = exercise.id
        self.name.setText(exercise.name)
        self.bars.setValue(exercise.bars)
        index = self.subdivision.findData(exercise.steps_per_beat)
        self.subdivision.setCurrentIndex(max(0, index))
        key_index = self.key_root.findData(exercise.key_root)
        self.key_root.setCurrentIndex(max(0, key_index))
        self.grid.load_exercise(exercise)
        self._update_staff()
        self._select_exercise(exercise.id)

    def reload_exercise_list(self, selected_id: int | None = None) -> None:
        target_id = self.exercise_id if selected_id is None else selected_id
        self.exercise_selector.blockSignals(True)
        self.exercise_selector.clear()
        self.exercise_selector.addItem("＋ 新規作成", None)
        for exercise in self.storage.list_exercises():
            self.exercise_selector.addItem(exercise.name, exercise.id)
        self.exercise_selector.blockSignals(False)
        self._select_exercise(target_id)

    def _select_exercise(self, exercise_id: int | None) -> None:
        self.exercise_selector.blockSignals(True)
        index = self.exercise_selector.findData(exercise_id)
        self.exercise_selector.setCurrentIndex(max(0, index))
        self.exercise_selector.blockSignals(False)

    def _exercise_selected(self, *args) -> None:  # noqa: ANN002
        exercise_id = self.exercise_selector.currentData()
        if exercise_id is None:
            self.new_exercise()
            return
        exercise = self.storage.get_exercise(exercise_id)
        if exercise is not None:
            self.load_exercise(exercise)

    def new_exercise(self) -> None:
        self.exercise_id = None
        self.name.setText("新しい練習")
        self.bars.setValue(1)
        self.key_root.setCurrentIndex(0)
        self.grid.clearContents()
        self._resize()
        self._select_exercise(None)


class PracticePage(QWidget):
    start_menu_requested = Signal(object, bool)
    preview_item_requested = Signal(Exercise, int)
    stop_requested = Signal()
    edit_requested = Signal(Exercise)

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        self._status_context = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)
        title = QLabel("今日の練習")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        selection, selection_layout = card("練習メニュー")
        self.practice_tabs = QTabWidget()
        menu_editor = QWidget()
        menu_layout = QVBoxLayout(menu_editor)
        menu_layout.setContentsMargins(4, 6, 4, 4)
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(4, 6, 4, 4)
        menu_row = QHBoxLayout()
        self.menu_combo = QComboBox()
        self.menu_combo.currentIndexChanged.connect(self._menu_selected)
        self.new_menu_button = QPushButton("新規")
        self.new_menu_button.clicked.connect(self._new_menu)
        self.menu_name = QLineEdit()
        self.menu_name.setPlaceholderText("練習メニュー名")
        self.save_menu_button = QPushButton("メニューを保存")
        self.save_menu_button.clicked.connect(self._save_menu)
        menu_row.addWidget(QLabel("メニュー"))
        menu_row.addWidget(self.menu_combo, 1)
        menu_row.addWidget(self.new_menu_button)
        menu_row.addWidget(self.menu_name, 1)
        menu_row.addWidget(self.save_menu_button)
        menu_layout.addLayout(menu_row)

        add_row = QHBoxLayout()
        self.exercise_picker = QComboBox()
        self.item_bpm = QSpinBox()
        self.item_bpm.setRange(30, 240)
        self.item_bpm.setValue(90)
        self.item_bpm.setSuffix(" BPM")
        self.add_item_button = QPushButton("＋ 追加")
        self.add_item_button.clicked.connect(self._add_item)
        add_row.addWidget(QLabel("追加する譜面"))
        add_row.addWidget(self.exercise_picker, 1)
        add_row.addWidget(self.item_bpm)
        add_row.addWidget(self.add_item_button)
        menu_layout.addLayout(add_row)

        self.menu_items = QTableWidget(0, 4)
        self.menu_items.setHorizontalHeaderLabels(("順番", "譜面", "BPM", "演奏時間"))
        self.menu_items.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.menu_items.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.menu_items.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.menu_items.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.menu_items.setColumnWidth(2, 112)
        self.menu_items.setColumnWidth(3, 92)
        self.menu_items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.menu_items.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.menu_items.setMaximumHeight(132)
        self.menu_items.itemSelectionChanged.connect(self._selection_changed)
        self.menu_items.cellClicked.connect(lambda row, column: self.menu_items.selectRow(row))
        menu_layout.addWidget(self.menu_items, 1)
        self.menu_duration_label = QLabel()
        self.menu_duration_label.setObjectName("muted")
        self.menu_duration_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        menu_layout.addWidget(self.menu_duration_label)

        order_row = QHBoxLayout()
        self.move_up_button = QPushButton("↑ 上へ")
        self.move_down_button = QPushButton("↓ 下へ")
        self.remove_item_button = QPushButton("－ 削除")
        self.move_up_button.clicked.connect(lambda: self._move_item(-1))
        self.move_down_button.clicked.connect(lambda: self._move_item(1))
        self.remove_item_button.clicked.connect(self._remove_item)
        self.edit_item_button = QPushButton("TABを編集")
        self.edit_item_button.clicked.connect(self._edit)
        order_row.addWidget(self.move_up_button)
        order_row.addWidget(self.move_down_button)
        order_row.addWidget(self.remove_item_button)
        order_row.addStretch()
        order_row.addWidget(self.edit_item_button)
        menu_layout.addLayout(order_row)

        self.preview_title_label = QLabel("プレビューするメニュー項目を選択してください")
        self.preview_title_label.setStyleSheet("font-weight: 700; color: #cbd5e1;")
        self.preview_duration_label = QLabel()
        self.preview_duration_label.setObjectName("muted")
        self.preview_duration_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.preview_item_button = QPushButton("▶  選択中の譜面だけ再生")
        self.preview_item_button.setEnabled(False)
        self.preview_item_button.clicked.connect(self._preview_selected_item)
        preview_header = QHBoxLayout()
        preview_header.addWidget(self.preview_title_label)
        preview_header.addStretch()
        preview_header.addWidget(self.preview_duration_label)
        preview_header.addWidget(self.preview_item_button)
        preview_layout.addLayout(preview_header)
        self.preview_grid = TabGrid()
        self.preview_grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        preview_layout.addWidget(self.preview_grid)
        self.staff = StaffWidget()
        preview_layout.addWidget(self.staff)
        self.fretboard = FretboardWidget()
        preview_layout.addWidget(self.fretboard)
        self.practice_tabs.addTab(menu_editor, "メニュー設定")
        self.practice_tabs.addTab(preview, "譜面プレビュー")
        selection_layout.addWidget(self.practice_tabs, 1)
        self.preview_grid.horizontalScrollBar().valueChanged.connect(self._sync_staff_timeline)
        self.preview_grid.timeline_geometry_changed.connect(self._sync_staff_timeline)
        root.addWidget(selection, 1)

        actions = QHBoxLayout()
        self.play_button = QPushButton("▶  メニュー全体を再生")
        self.play_button.clicked.connect(lambda: self._start(False))
        self.practice_button = QPushButton("●  メニュー全体を採点")
        self.practice_button.setObjectName("primaryButton")
        self.practice_button.clicked.connect(lambda: self._start(True))
        self.stop_button = QPushButton("■  停止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        actions.addStretch()
        actions.addWidget(self.play_button)
        actions.addWidget(self.practice_button)
        actions.addWidget(self.stop_button)
        root.addLayout(actions)

        self.status = QLabel("練習を選んで開始してください")
        self.status.setObjectName("statusPill")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.status)
        self.reload()
        QTimer.singleShot(0, self._sync_staff_timeline)

    def _sync_staff_timeline(self, *args) -> None:  # noqa: ANN002
        self.staff.set_timeline_view(
            self.preview_grid.horizontalScrollBar().value(),
            self.preview_grid.columnWidth(0) if self.preview_grid.columnCount() else 38,
            self.preview_grid.viewport().x(),
        )

    def reload(self) -> None:
        current_menu_id = self.menu_combo.currentData()
        exercises = self.storage.list_exercises()
        self._exercises = {
            exercise.id: exercise for exercise in exercises if exercise.id is not None
        }
        self.exercise_picker.clear()
        for exercise in exercises:
            self.exercise_picker.addItem(exercise.name, exercise.id)

        menus = self.storage.list_practice_menus()
        self.menu_combo.blockSignals(True)
        self.menu_combo.clear()
        for menu in menus:
            self.menu_combo.addItem(menu.name, menu.id)
        index = self.menu_combo.findData(current_menu_id)
        self.menu_combo.setCurrentIndex(index if index >= 0 else (0 if menus else -1))
        self.menu_combo.blockSignals(False)
        if menus:
            self._menu_selected()
        else:
            self._new_menu()

    def _menu_selected(self, *args) -> None:  # noqa: ANN002
        menu_id = self.menu_combo.currentData()
        menu = self.storage.get_practice_menu(menu_id) if menu_id is not None else None
        if menu is not None:
            self._load_menu(menu)

    def _new_menu(self) -> None:
        self.menu_id: int | None = None
        self.menu_combo.blockSignals(True)
        self.menu_combo.setCurrentIndex(-1)
        self.menu_combo.blockSignals(False)
        self.menu_name.setText("新しい練習メニュー")
        self._set_items([])
        self.practice_tabs.setCurrentIndex(0)

    def _load_menu(self, menu: PracticeMenu) -> None:
        self.menu_id = menu.id
        self.menu_name.setText(menu.name)
        self._set_items(menu.items)

    def _set_items(self, items: list[PracticeMenuItem], selected_row: int = 0) -> None:
        self.menu_items.setRowCount(0)
        for item in items:
            self._append_item(item.exercise_id, item.bpm)
        if self.menu_items.rowCount():
            row = min(max(0, selected_row), self.menu_items.rowCount() - 1)
            self.menu_items.selectRow(row)
        else:
            self._clear_preview()

    def _append_item(self, exercise_id: int, bpm: int) -> None:
        row = self.menu_items.rowCount()
        self.menu_items.insertRow(row)
        order = QTableWidgetItem(str(row + 1))
        order.setFlags(order.flags() & ~Qt.ItemFlag.ItemIsEditable)
        exercise = self._exercises.get(exercise_id)
        exercise_item = QTableWidgetItem(exercise.name if exercise else "（削除済みの譜面）")
        exercise_item.setData(Qt.ItemDataRole.UserRole, exercise_id)
        exercise_item.setFlags(exercise_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        bpm_item = QTableWidgetItem()
        bpm_item.setFlags(bpm_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        bpm_editor = QSpinBox()
        bpm_editor.setRange(30, 240)
        bpm_editor.setValue(min(240, max(30, bpm)))
        bpm_editor.setSuffix(" BPM")
        bpm_editor.valueChanged.connect(self._update_menu_durations)
        bpm_editor.valueChanged.connect(
            lambda value, editor=bpm_editor: self._select_row_for_bpm(editor)
        )
        duration_item = QTableWidgetItem()
        duration_item.setFlags(duration_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        duration_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.menu_items.setItem(row, 0, order)
        self.menu_items.setItem(row, 1, exercise_item)
        self.menu_items.setItem(row, 2, bpm_item)
        self.menu_items.setCellWidget(row, 2, bpm_editor)
        self.menu_items.setItem(row, 3, duration_item)
        self._update_menu_durations()

    def _add_item(self) -> None:
        exercise_id = self.exercise_picker.currentData()
        if exercise_id is None:
            QMessageBox.information(self, "譜面がありません", "先にTAB譜面を作成してください。")
            return
        self._append_item(exercise_id, self.item_bpm.value())
        self.menu_items.selectRow(self.menu_items.rowCount() - 1)

    def _remove_item(self) -> None:
        row = self.menu_items.currentRow()
        if row < 0:
            return
        self.menu_items.removeRow(row)
        self._renumber_items()
        if self.menu_items.rowCount():
            self.menu_items.selectRow(min(row, self.menu_items.rowCount() - 1))
        else:
            self._clear_preview()
        self._update_menu_durations()

    def _move_item(self, delta: int) -> None:
        row = self.menu_items.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.menu_items.rowCount():
            return
        items = self.build_menu().items
        items[row], items[target] = items[target], items[row]
        self._set_items(items, target)

    def _renumber_items(self) -> None:
        for row in range(self.menu_items.rowCount()):
            self.menu_items.item(row, 0).setText(str(row + 1))

    def _select_row_for_bpm(self, editor: QSpinBox) -> None:
        for row in range(self.menu_items.rowCount()):
            if self.menu_items.cellWidget(row, 2) is editor:
                self.menu_items.selectRow(row)
                return

    def _update_menu_durations(self, *args) -> None:  # noqa: ANN002
        performance_total = 0.0
        menu_total = 0.0
        for row in range(self.menu_items.rowCount()):
            exercise_id = self.menu_items.item(row, 1).data(Qt.ItemDataRole.UserRole)
            exercise = self._exercises.get(exercise_id)
            bpm_editor = self.menu_items.cellWidget(row, 2)
            bpm = bpm_editor.value() if isinstance(bpm_editor, QSpinBox) else 90
            seconds = exercise_duration_seconds(exercise, bpm) if exercise else 0.0
            performance_total += seconds
            menu_total += seconds
            duration_item = self.menu_items.item(row, 3)
            if duration_item is not None:
                duration_item.setText(format_duration(seconds) if exercise else "—")
            if exercise is not None:
                if row == 0:
                    menu_total += exercise.beats_per_bar * 60.0 / bpm
                else:
                    menu_total += 3 * exercise.beats_per_bar * 60.0 / bpm
        self.menu_duration_label.setText(
            f"演奏合計 {format_duration(performance_total)}　"
            f"所要時間 {format_duration(menu_total)}（開始カウント・インターバル込み）"
        )
        selected_row = self.menu_items.currentRow()
        if selected_row >= 0:
            exercise_id = self.menu_items.item(selected_row, 1).data(Qt.ItemDataRole.UserRole)
            exercise = self._exercises.get(exercise_id)
            bpm_editor = self.menu_items.cellWidget(selected_row, 2)
            if exercise is not None and isinstance(bpm_editor, QSpinBox):
                self._set_preview_duration(exercise, bpm_editor.value())

    def build_menu(self) -> PracticeMenu:
        items = []
        for row in range(self.menu_items.rowCount()):
            exercise_id = self.menu_items.item(row, 1).data(Qt.ItemDataRole.UserRole)
            bpm_editor = self.menu_items.cellWidget(row, 2)
            bpm = bpm_editor.value() if isinstance(bpm_editor, QSpinBox) else 90
            if exercise_id is not None:
                items.append(PracticeMenuItem(int(exercise_id), min(240, max(30, bpm))))
        return PracticeMenu(
            id=self.menu_id,
            name=self.menu_name.text().strip() or "名称未設定の練習メニュー",
            items=items,
        )

    def _save_menu(self) -> None:
        menu = self.storage.save_practice_menu(self.build_menu())
        self.menu_id = menu.id
        self.reload()
        index = self.menu_combo.findData(menu.id)
        self.menu_combo.setCurrentIndex(max(0, index))
        QMessageBox.information(self, "保存しました", f"「{menu.name}」を保存しました。")

    def current_exercise(self) -> Exercise | None:
        row = self.menu_items.currentRow()
        if row < 0 or self.menu_items.item(row, 1) is None:
            return None
        exercise_id = self.menu_items.item(row, 1).data(Qt.ItemDataRole.UserRole)
        return self._exercises.get(exercise_id)

    def _selection_changed(self) -> None:
        exercise = self.current_exercise()
        if exercise:
            row = self.menu_items.currentRow()
            bpm_editor = self.menu_items.cellWidget(row, 2)
            bpm = bpm_editor.value() if isinstance(bpm_editor, QSpinBox) else 90
            self.show_exercise(exercise, bpm, context="選択中")
            self.preview_item_button.setEnabled(True)

    def _preview_selected_item(self) -> None:
        exercise = self.current_exercise()
        row = self.menu_items.currentRow()
        if exercise is None or row < 0:
            return
        bpm_editor = self.menu_items.cellWidget(row, 2)
        bpm = bpm_editor.value() if isinstance(bpm_editor, QSpinBox) else 90
        self.practice_tabs.setCurrentIndex(1)
        self.preview_item_requested.emit(exercise, bpm)

    def show_selected_exercise(self) -> None:
        self._selection_changed()

    def show_exercise(
        self,
        exercise: Exercise,
        bpm: int | None = None,
        *,
        context: str = "表示中",
    ) -> None:
        self.preview_grid.load_exercise(exercise)
        self.staff.set_exercise(exercise)
        self.fretboard.set_exercise(exercise)
        if bpm is not None:
            self.preview_title_label.setText(
                f"{context}: {exercise.name} / {bpm} BPM"
            )
            self._set_preview_duration(exercise, bpm)

    def _set_preview_duration(self, exercise: Exercise, bpm: int) -> None:
        self.preview_duration_label.setText(
            f"演奏時間 {format_duration(exercise_duration_seconds(exercise, bpm))}"
            f"（{bpm} BPM）"
        )

    def _clear_preview(self) -> None:
        empty = Exercise()
        self.preview_grid.load_exercise(empty)
        self.staff.set_exercise(empty)
        self.fretboard.set_exercise(empty)
        self.preview_title_label.setText("プレビューするメニュー項目を選択してください")
        self.preview_duration_label.clear()
        self.preview_item_button.setEnabled(False)

    def _start(self, assess: bool) -> None:
        menu = self.build_menu()
        if not menu.items:
            QMessageBox.information(self, "練習がありません", "メニューへ譜面を追加してください。")
            return
        missing = [item for item in menu.items if item.exercise_id not in self._exercises]
        if missing:
            QMessageBox.warning(self, "譜面が見つかりません", "削除済みの譜面をメニューから外してください。")
            return
        self.practice_tabs.setCurrentIndex(1)
        self.start_menu_requested.emit(menu, assess)

    def _edit(self) -> None:
        exercise = self.current_exercise()
        if exercise:
            self.edit_requested.emit(exercise)

    def set_running(self, running: bool, assess: bool = False) -> None:
        self.play_button.setEnabled(not running)
        self.practice_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        for widget in (
            self.menu_combo, self.new_menu_button, self.menu_name, self.save_menu_button,
            self.exercise_picker, self.item_bpm, self.add_item_button, self.menu_items,
            self.move_up_button, self.move_down_button, self.remove_item_button,
            self.edit_item_button, self.preview_item_button,
        ):
            widget.setEnabled(not running)
        self.preview_item_button.setEnabled(not running and self.current_exercise() is not None)
        if not running:
            self._status_context = ""
        self.status.setText("入力音を採点しています…" if running and assess else "再生中…" if running else "練習を選んで開始してください")

    def set_menu_progress(
        self,
        index: int,
        total: int,
        exercise_name: str,
        bpm: int,
        *,
        interval: bool = False,
        assess: bool = False,
    ) -> None:
        if interval:
            self._status_context = (
                f"次: {index + 1}/{total}「{exercise_name}」 {bpm} BPM　"
                "インターバル（無音2小節 → クリック1小節）"
            )
        else:
            self._status_context = (
                f"{index + 1}/{total}「{exercise_name}」 {bpm} BPM"
                + ("　採点中" if assess else "　再生中")
            )
        self.status.setText(self._status_context)

    def prepare_staff(self, exercise: Exercise, bpm: int, count_in_beats: int) -> None:
        self.staff.set_exercise(exercise, bpm, count_in_beats)
        self.fretboard.set_exercise(exercise)
        self._set_preview_duration(exercise, bpm)

    def add_detected_note(self, observed_time: float, midi: float) -> None:
        self.staff.add_observation(observed_time, midi)

    def set_input_latency(self, latency_seconds: float, timing_offset: float = 0.0) -> None:
        self.status.setText(
            (self._status_context or "入力音を採点しています…")
            + f"（入力 {latency_seconds * 1000:.1f} ms / 校正 {timing_offset * 1000:+.0f} ms）"
        )


class ProgressPage(QWidget):
    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        title = QLabel("成長レポート")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        self.summary = QLabel("まだ採点結果がありません")
        self.summary.setObjectName("summaryCard")
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.summary)

        self.chart = pg.PlotWidget()
        self.chart.setBackground("#111722")
        self.chart.showGrid(x=True, y=True, alpha=0.16)
        self.chart.setYRange(0, 100)
        self.chart.setLabel("left", "スコア")
        self.chart.setLabel("bottom", "練習回")
        self.chart.addLegend()
        root.addWidget(self.chart, 1)

        self.history = QTableWidget(0, 5)
        self.history.setHorizontalHeaderLabels(("日時", "練習", "BPM", "音程", "リズム"))
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history.setMaximumHeight(220)
        root.addWidget(self.history)
        self.reload()

    def reload(self) -> None:
        sessions = self.storage.list_sessions()
        self.chart.clear()
        self.history.setRowCount(len(sessions))
        if not sessions:
            self.summary.setText("採点をすると、ここに成長の推移が表示されます")
            return
        x = list(range(1, len(sessions) + 1))
        pitch = [row["pitch_score"] for row in sessions]
        timing = [row["timing_score"] for row in sessions]
        total = [row["total_score"] for row in sessions]
        self.chart.plot(x, total, pen=pg.mkPen("#63d7b5", width=3), symbol="o", name="総合")
        self.chart.plot(x, pitch, pen=pg.mkPen("#6ba7ff", width=2), name="音程")
        self.chart.plot(x, timing, pen=pg.mkPen("#ffb35c", width=2), name="リズム")
        latest = sessions[-1]
        self.summary.setText(
            f"最新スコア  {latest['total_score']:.0f}   ｜   "
            f"音程 {latest['pitch_score']:.0f}   リズム {latest['timing_score']:.0f}   ｜   練習 {len(sessions)}回"
        )
        for table_row, session in enumerate(reversed(sessions)):
            values = (
                session["started_at"].replace("T", " ")[:16], session["exercise_name"],
                str(session["bpm"]), f"{session['pitch_score']:.0f}", f"{session['timing_score']:.0f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.history.setItem(table_row, column, item)

