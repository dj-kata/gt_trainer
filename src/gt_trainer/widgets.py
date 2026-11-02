from __future__ import annotations

from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .models import Exercise, STRING_NAMES, SessionResult, TabNote
from .music import evaluate_performance, midi_name, score_attempts
from .storage import Storage


def card(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(18, 22, 18, 18)
    layout.setSpacing(12)
    return box, layout


class TabGrid(QTableWidget):
    def __init__(self) -> None:
        super().__init__(6, 16)
        self.steps_per_beat = 4
        self.setVerticalHeaderLabels(STRING_NAMES)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAlternatingRowColors(False)
        self.setMinimumHeight(270)
        self.configure(16, 4)

    def configure(self, total_steps: int, steps_per_beat: int) -> None:
        values = self.notes()
        self.steps_per_beat = steps_per_beat
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
                self.item(note.string, note.step).setText(str(note.fret))

    def notes(self) -> list[TabNote]:
        notes: list[TabNote] = []
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                item = self.item(row, column)
                value = item.text().strip() if item else ""
                if value.isdigit() and 0 <= int(value) <= 24:
                    notes.append(TabNote(column, row, int(value)))
        return notes

    def load_exercise(self, exercise: Exercise) -> None:
        self.clearContents()
        self.configure(exercise.total_steps, exercise.steps_per_beat)
        for note in exercise.notes:
            if note.step < self.columnCount() and 0 <= note.string < 6:
                item = self.item(note.string, note.step)
                item.setText(str(note.fret))

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
        description = QLabel("セルをダブルクリックし、0〜24のフレット番号を入力します。空欄は休符です。")
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
        self.subdivision.addItem("16分音符", 4)
        self.subdivision.setCurrentIndex(2)
        controls.addWidget(QLabel("名前"))
        controls.addWidget(self.name, 2)
        controls.addWidget(QLabel("小節"))
        controls.addWidget(self.bars)
        controls.addWidget(QLabel("分割"))
        controls.addWidget(self.subdivision)
        root.addLayout(controls)

        self.grid = TabGrid()
        root.addWidget(self.grid, 1)
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

    def _resize(self) -> None:
        steps = self.subdivision.currentData()
        self.grid.configure(self.bars.value() * 4 * steps, steps)

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

