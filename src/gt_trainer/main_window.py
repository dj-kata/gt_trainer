from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .audio import AudioEngine, list_audio_devices
from .models import Exercise, SessionResult
from .music import evaluate_performance, score_attempts
from .storage import Storage
from .widgets import EditorPage, PracticePage, ProgressPage


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        self.audio = AudioEngine()
        self.settings = QSettings("gt-trainer", "Guitar Trainer")
        self.active_exercise: Exercise | None = None
        self.active_assessment = False
        self.setWindowTitle("Guitar Trainer")
        self.resize(1180, 780)
        self.setMinimumSize(900, 620)

        shell = QWidget()
        self.setCentralWidget(shell)
        main = QHBoxLayout(shell)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(215)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 24, 18, 20)
        logo = QLabel("GUITAR\nTRAINER")
        logo.setObjectName("logo")
        side.addWidget(logo)
        side.addSpacing(28)
        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(("今日の練習", "TABエディター", "成長レポート")):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setObjectName("navButton")
            button.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            side.addWidget(button)
            self.nav_buttons.append(button)
        side.addStretch()
        version = QLabel("v0.1  MVP")
        version.setObjectName("muted")
        side.addWidget(version)
        main.addWidget(sidebar)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        toolbar = QWidget()
        toolbar.setObjectName("toolbar")
        tools = QHBoxLayout(toolbar)
        tools.setContentsMargins(24, 10, 24, 10)
        self.input_device = QComboBox()
        self.output_device = QComboBox()
        self.input_device.setMinimumWidth(170)
        self.output_device.setMinimumWidth(170)
        refresh = QPushButton("↻")
        refresh.setFixedWidth(38)
        refresh.clicked.connect(self.refresh_devices)
        self.bpm = QSpinBox()
        self.bpm.setRange(30, 240)
        self.bpm.setValue(int(self.settings.value("bpm", 90)))
        self.bpm.setSuffix(" BPM")
        self.meter = QComboBox()
        self.meter.addItem("4/4", 4)
        self.meter.addItem("3/4", 3)
        self.meter.addItem("6/8", 6)
        self.metronome = QPushButton("メトロノーム")
        self.metronome.setCheckable(True)
        self.metronome.clicked.connect(self.toggle_metronome)
        tools.addWidget(QLabel("IN"))
        tools.addWidget(self.input_device)
        tools.addWidget(QLabel("OUT"))
        tools.addWidget(self.output_device)
        tools.addWidget(refresh)
        tools.addStretch()
        tools.addWidget(self.bpm)
        tools.addWidget(self.meter)
        tools.addWidget(self.metronome)
        content.addWidget(toolbar)

        self.pages = QStackedWidget()
        self.practice = PracticePage(storage)
        self.editor = EditorPage(storage)
        self.progress = ProgressPage(storage)
        self.pages.addWidget(self.practice)
        self.pages.addWidget(self.editor)
        self.pages.addWidget(self.progress)
        content.addWidget(self.pages, 1)
        main.addLayout(content, 1)

        self.practice.start_requested.connect(self.start_practice)
        self.practice.stop_requested.connect(self.audio.stop)
        self.practice.edit_requested.connect(self.edit_exercise)
        self.editor.saved.connect(self._exercise_saved)
        self.editor.preview_requested.connect(lambda ex: self.start_practice(ex, False))
        self.audio.position_changed.connect(self._position_changed)
        self.audio.playback_finished.connect(self._playback_finished)
        self.audio.error.connect(self._audio_error)
        self.audio.metronome_changed.connect(self.metronome.setChecked)
        self.refresh_devices()
        self.show_page(0)

    def show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        if index == 2:
            self.progress.reload()

    def refresh_devices(self) -> None:
        remembered_input = self.settings.value("input_device")
        remembered_output = self.settings.value("output_device")
        self.input_device.clear()
        self.output_device.clear()
        self.input_device.addItem("システム既定", None)
        self.output_device.addItem("システム既定", None)
        try:
            inputs, outputs = list_audio_devices()
            for index, name in inputs:
                self.input_device.addItem(name, index)
            for index, name in outputs:
                self.output_device.addItem(name, index)
            for combo, remembered in ((self.input_device, remembered_input), (self.output_device, remembered_output)):
                if remembered is not None:
                    found = combo.findData(int(remembered))
                    combo.setCurrentIndex(max(0, found))
        except Exception as exc:
            self.statusBar().showMessage(f"音声デバイスを取得できません: {exc}", 8000)

    def toggle_metronome(self, checked: bool) -> None:
        if checked:
            self.audio.start_metronome(self.bpm.value(), self.meter.currentData(), self.output_device.currentData())
        else:
            self.audio.stop_metronome()

    def start_practice(self, exercise: Exercise, assess: bool) -> None:
        if self.audio.busy:
            return
        if assess and not exercise.notes:
            QMessageBox.warning(self, "譜面が空です", "採点するノートがありません。")
            return
        self.active_exercise = exercise
        self.active_assessment = assess
        self.practice.set_running(True, assess)
        # During assessment, the guide notes are muted so they cannot leak into pitch detection.
        self.audio.play(
            exercise, self.bpm.value(), self.output_device.currentData(),
            input_device=self.input_device.currentData(), assess=assess,
            include_notes=not assess, count_in_beats=exercise.beats_per_bar,
        )

    def _position_changed(self, step: int) -> None:
        self.practice.preview_grid.set_playhead(step)
        self.editor.grid.set_playhead(step)

    def _playback_finished(self, observations: list, cancelled: bool) -> None:
        self.practice.set_running(False)
        if cancelled or not self.active_assessment or not self.active_exercise:
            return
        attempts = evaluate_performance(
            self.active_exercise, self.bpm.value(), observations,
            count_in_beats=self.active_exercise.beats_per_bar,
        )
        pitch, timing, total = score_attempts(attempts)
        result = SessionResult(
            exercise_id=self.active_exercise.id,
            exercise_name=self.active_exercise.name,
            bpm=self.bpm.value(),
            started_at=datetime.now().isoformat(timespec="seconds"),
            pitch_score=pitch,
            timing_score=timing,
            total_score=total,
            attempts=attempts,
        )
        self.storage.save_session(result)
        self.progress.reload()
        detected = sum(a.detected_midi is not None for a in attempts)
        QMessageBox.information(
            self, "採点結果",
            f"総合  {total:.0f}点\n\n音程  {pitch:.0f}点　　リズム  {timing:.0f}点\n"
            f"検出 {detected} / {len(attempts)} 音",
        )

    def _audio_error(self, message: str) -> None:
        self.practice.set_running(False)
        QMessageBox.critical(self, "音声エラー", message)

    def edit_exercise(self, exercise: Exercise) -> None:
        self.editor.load_exercise(exercise)
        self.show_page(1)

    def _exercise_saved(self) -> None:
        self.practice.reload()

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        self.audio.stop()
        self.audio.stop_metronome()
        self.settings.setValue("bpm", self.bpm.value())
        if self.input_device.currentData() is not None:
            self.settings.setValue("input_device", self.input_device.currentData())
        if self.output_device.currentData() is not None:
            self.settings.setValue("output_device", self.output_device.currentData())
        self.storage.close()
        super().closeEvent(event)

