from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QModelIndex, QRect, QRegularExpression, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import Exercise, STRING_NAMES, TabNote, format_tab_cell, parse_tab_cell
from .staff import StaffWidget
from .storage import Storage


def card(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(18, 22, 18, 18)
    layout.setSpacing(12)
    return box, layout


class TabCellDelegate(QStyledItemDelegate):
    advance_requested = Signal(int, int)
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
                Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_Left, Qt.Key.Key_Right,
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
            painter.setPen(border)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.setPen(text_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(bar + 1))
        painter.end()


class TabGrid(QTableWidget):
    timeline_geometry_changed = Signal()

    def __init__(self) -> None:
        super().__init__(6, 16)
        self.steps_per_beat = 4
        self._edit_history: list[list[tuple[int, int, str, str]]] = []
        self._history_index = 0
        self._applying_history = False
        self._cell_values: dict[tuple[int, int], str] = {}
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
        QApplication.clipboard().setText("\n".join(rows))

    def paste_selection(self) -> None:
        anchor_row = max(0, self.currentRow())
        anchor_column = max(0, self.currentColumn())
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
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                item = self.item(row, column)
                if not item:
                    continue
                if column == step:
                    item.setBackground(QColor("#3b5564"))
                else:
                    item.setBackground(QColor("#202735") if column % self.steps_per_beat == 0 else QColor("#181e29"))
        if 0 <= step < self.columnCount():
            target = self.item(0, step)
            if target:
                self.scrollToItem(target, QAbstractItemView.ScrollHint.EnsureVisible)


class EditorPage(QWidget):
    saved = Signal()
    preview_requested = Signal(Exercise)

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
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
            "貼り付け、Ctrl+矢印でフレット・弦を移動できます。"
        )
        description.setObjectName("muted")
        root.addWidget(description)

        controls = QHBoxLayout()
        self.name = QLineEdit("クロマチック練習")
        self.name.setPlaceholderText("練習名")
        self.bars = QSpinBox()
        self.bars.setRange(1, 8)
        self.bars.setValue(1)
        self.subdivision = QComboBox()
        self.subdivision.addItem("4分音符", 1)
        self.subdivision.addItem("8分音符", 2)
        self.subdivision.addItem("12分音符", 3)
        self.subdivision.addItem("16分音符", 4)
        self.subdivision.addItem("24分音符", 6)
        self.subdivision.setCurrentIndex(self.subdivision.findData(4))
        controls.addWidget(QLabel("名前"))
        controls.addWidget(self.name, 2)
        controls.addWidget(QLabel("小節"))
        controls.addWidget(self.bars)
        controls.addWidget(QLabel("分割"))
        controls.addWidget(self.subdivision)
        root.addLayout(controls)

        self.grid = TabGrid()
        root.addWidget(self.grid)
        self.staff = StaffWidget()
        root.addWidget(self.staff)
        self.grid.horizontalScrollBar().valueChanged.connect(self._sync_staff_timeline)
        self.grid.timeline_geometry_changed.connect(self._sync_staff_timeline)
        buttons = QHBoxLayout()
        new_button = QPushButton("新規")
        new_button.clicked.connect(self.new_exercise)
        preview = QPushButton("▶  プレビュー")
        preview.clicked.connect(lambda: self.preview_requested.emit(self.build_exercise()))
        save = QPushButton("保存")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save)
        buttons.addWidget(new_button)
        buttons.addStretch()
        buttons.addWidget(preview)
        buttons.addWidget(save)
        root.addLayout(buttons)

        self.bars.valueChanged.connect(self._resize)
        self.subdivision.currentIndexChanged.connect(self._resize)
        self.grid.itemChanged.connect(self._update_staff)
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
        self.staff.set_exercise(self.build_exercise())

    def build_exercise(self) -> Exercise:
        return Exercise(
            id=self.exercise_id,
            name=self.name.text().strip() or "名称未設定",
            steps_per_beat=self.subdivision.currentData(),
            beats_per_bar=4,
            bars=self.bars.value(),
            notes=self.grid.notes(),
        )

    def save(self) -> None:
        exercise = self.build_exercise()
        if not exercise.notes:
            QMessageBox.warning(self, "入力を確認", "TABに1音以上入力してください。")
            return
        saved = self.storage.save_exercise(exercise)
        self.exercise_id = saved.id
        self.saved.emit()
        QMessageBox.information(self, "保存しました", f"「{saved.name}」を保存しました。")

    def load_exercise(self, exercise: Exercise) -> None:
        self.exercise_id = exercise.id
        self.name.setText(exercise.name)
        self.bars.setValue(exercise.bars)
        index = self.subdivision.findData(exercise.steps_per_beat)
        self.subdivision.setCurrentIndex(max(0, index))
        self.grid.load_exercise(exercise)
        self._update_staff()

    def new_exercise(self) -> None:
        self.exercise_id = None
        self.name.setText("新しい練習")
        self.bars.setValue(1)
        self.grid.clearContents()
        self._resize()


class PracticePage(QWidget):
    start_requested = Signal(Exercise, bool)
    stop_requested = Signal()
    edit_requested = Signal(Exercise)

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(16)
        title = QLabel("今日の練習")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        selection, selection_layout = card("練習メニュー")
        row = QHBoxLayout()
        self.exercise_combo = QComboBox()
        self.exercise_combo.currentIndexChanged.connect(self._selection_changed)
        edit = QPushButton("TABを編集")
        edit.clicked.connect(self._edit)
        row.addWidget(self.exercise_combo, 1)
        row.addWidget(edit)
        selection_layout.addLayout(row)
        self.preview_grid = TabGrid()
        self.preview_grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        selection_layout.addWidget(self.preview_grid)
        self.staff = StaffWidget()
        selection_layout.addWidget(self.staff)
        self.preview_grid.horizontalScrollBar().valueChanged.connect(self._sync_staff_timeline)
        self.preview_grid.timeline_geometry_changed.connect(self._sync_staff_timeline)
        root.addWidget(selection, 1)

        actions = QHBoxLayout()
        self.play_button = QPushButton("▶  お手本を再生")
        self.play_button.clicked.connect(lambda: self._start(False))
        self.practice_button = QPushButton("●  採点を開始")
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
        current = self.exercise_combo.currentData()
        self.exercise_combo.blockSignals(True)
        self.exercise_combo.clear()
        for exercise in self.storage.list_exercises():
            self.exercise_combo.addItem(exercise.name, exercise.id)
        if current is not None:
            index = self.exercise_combo.findData(current)
            self.exercise_combo.setCurrentIndex(max(0, index))
        self.exercise_combo.blockSignals(False)
        self._selection_changed()

    def current_exercise(self) -> Exercise | None:
        exercise_id = self.exercise_combo.currentData()
        return self.storage.get_exercise(exercise_id) if exercise_id is not None else None

    def _selection_changed(self) -> None:
        exercise = self.current_exercise()
        if exercise:
            self.preview_grid.load_exercise(exercise)
            self.staff.set_exercise(exercise)

    def _start(self, assess: bool) -> None:
        exercise = self.current_exercise()
        if exercise:
            self.start_requested.emit(exercise, assess)
        else:
            QMessageBox.information(self, "練習がありません", "TABエディターで練習を作成してください。")

    def _edit(self) -> None:
        exercise = self.current_exercise()
        if exercise:
            self.edit_requested.emit(exercise)

    def set_running(self, running: bool, assess: bool = False) -> None:
        self.play_button.setEnabled(not running)
        self.practice_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.status.setText("入力音を採点しています…" if running and assess else "再生中…" if running else "練習を選んで開始してください")

    def prepare_staff(self, exercise: Exercise, bpm: int, count_in_beats: int) -> None:
        self.staff.set_exercise(exercise, bpm, count_in_beats)

    def add_detected_note(self, observed_time: float, midi: float) -> None:
        self.staff.add_observation(observed_time, midi)

    def set_input_latency(self, latency_seconds: float) -> None:
        self.status.setText(f"入力音を採点しています…（入力遅延 {latency_seconds * 1000:.1f} ms 補正）")


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

