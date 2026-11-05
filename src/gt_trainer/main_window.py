from __future__ import annotations

from datetime import datetime
import hashlib
from statistics import median

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .audio import AudioEngine, list_audio_devices, playback_end_step
from .models import Exercise, PracticeMenu, SessionResult
from .music import (
    CALIBRATION_COUNT_IN_BEATS,
    calibration_exercise,
    calibration_silent_click_steps,
    estimate_timing_calibration,
    evaluate_performance,
    score_attempts,
)
from .storage import Storage
from .widgets import CalibrationDialog, EditorPage, PracticePage, ProgressPage


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        self.audio = AudioEngine()
        self.settings = QSettings("gt-trainer", "Guitar Trainer")
        self.active_exercise: Exercise | None = None
        self.active_assessment = False
        self.active_bpm = 90
        self.active_count_in_beats = 0
        self.active_menu_items: list[tuple[Exercise, int]] = []
        self.active_menu_index = -1
        self.active_menu_name = ""
        self.active_menu_assessment = False
        self.active_menu_phase: str | None = None
        self.active_menu_attempts = []
        self.active_menu_details: list[tuple[str, int, float]] = []
        self._menu_cancelled = False
        self.active_calibration = False
        self.calibration_dialog: CalibrationDialog | None = None
        self.calibration_exercise: Exercise | None = None
        self._closing = False
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
        self.input_level = QProgressBar()
        self.input_level.setRange(0, 100)
        self.input_level.setValue(0)
        self.input_level.setTextVisible(False)
        self.input_level.setFixedSize(72, 12)
        self.input_level.setToolTip("選択中の入力デバイスの信号レベル")
        self.input_level.setStyleSheet(
            "QProgressBar { background: #1b2432; border: 1px solid #344158; }"
            "QProgressBar::chunk { background: #63d7b5; }"
        )
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
        self.calibrate = QPushButton("タイミング校正")
        self.calibrate.clicked.connect(self.start_calibration)
        tools.addWidget(QLabel("IN"))
        tools.addWidget(self.input_device)
        tools.addWidget(QLabel("LEVEL"))
        tools.addWidget(self.input_level)
        tools.addWidget(QLabel("OUT"))
        tools.addWidget(self.output_device)
        tools.addWidget(refresh)
        tools.addStretch()
        tools.addWidget(self.bpm)
        tools.addWidget(self.meter)
        tools.addWidget(self.metronome)
        tools.addWidget(self.calibrate)
        content.addWidget(toolbar)

        self.pages = QStackedWidget()
        self.practice = PracticePage(storage)
        self.editor = EditorPage(storage)
        self.editor.set_bpm(self.bpm.value())
        self.progress = ProgressPage(storage)
        self.pages.addWidget(self.practice)
        self.pages.addWidget(self.editor)
        self.pages.addWidget(self.progress)
        content.addWidget(self.pages, 1)
        main.addLayout(content, 1)

        self.practice.start_menu_requested.connect(self.start_practice_menu)
        self.practice.stop_requested.connect(self._stop_practice)
        self.practice.edit_requested.connect(self.edit_exercise)
        self.editor.saved.connect(self._exercise_saved)
        self.editor.preview_requested.connect(
            lambda exercise, start_step: self.start_practice(exercise, False, start_step)
        )
        self.editor.notes_audition_requested.connect(self._preview_editor_notes)
        self.editor.stop_requested.connect(self._stop_practice)
        self.audio.position_changed.connect(self._position_changed)
        self.audio.playback_finished.connect(self._playback_finished)
        self.audio.error.connect(self._audio_error)
        self.audio.metronome_changed.connect(self.metronome.setChecked)
        self.audio.observation_detected.connect(self._observation_detected)
        self.audio.input_latency_changed.connect(self._input_latency_changed)
        self.audio.input_level_changed.connect(
            lambda level: self.input_level.setValue(round(level * 100))
        )
        self.audio.input_monitor_error.connect(self._input_monitor_error)
        self.input_device.currentIndexChanged.connect(self._input_device_changed)
        self.output_device.currentIndexChanged.connect(self._update_calibration_label)
        self.bpm.valueChanged.connect(self.editor.set_bpm)
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
        self.input_device.blockSignals(True)
        self.output_device.blockSignals(True)
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
        finally:
            self.input_device.blockSignals(False)
            self.output_device.blockSignals(False)
        self._input_device_changed()

    def _input_device_changed(self, *args) -> None:  # noqa: ANN002
        self._update_calibration_label()
        self._restart_input_monitor()

    def _restart_input_monitor(self) -> None:
        if self._closing:
            return
        if self.audio.busy:
            QTimer.singleShot(100, self._restart_input_monitor)
            return
        self.audio.start_input_monitor(self.input_device.currentData())

    def _input_monitor_error(self, message: str) -> None:
        self.input_level.setValue(0)
        self.statusBar().showMessage(f"入力レベルを確認できません: {message}", 8000)

    def _device_pair_key(self) -> str:
        identity = "\n".join((
            f"{self.input_device.currentData()}:{self.input_device.currentText()}",
            f"{self.output_device.currentData()}:{self.output_device.currentText()}",
        ))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]

    def _timing_offset(self) -> float:
        value = self.settings.value(
            f"timing_calibration/{self._device_pair_key()}/offset_seconds", 0.0
        )
        try:
            return max(-0.45, min(0.45, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def _update_calibration_label(self, *args) -> None:  # noqa: ANN002
        offset_ms = self._timing_offset() * 1000.0
        if abs(offset_ms) >= 0.5:
            self.calibrate.setText(f"タイミング校正 ({offset_ms:+.0f} ms)")
        else:
            self.calibrate.setText("タイミング校正")

    def toggle_metronome(self, checked: bool) -> None:
        if checked:
            self.audio.start_metronome(self.bpm.value(), self.meter.currentData(), self.output_device.currentData())
        else:
            self.audio.stop_metronome()

    def _preview_editor_notes(self, midi_notes: list[int]) -> None:
        self.audio.preview_notes(midi_notes, self.output_device.currentData())

    def start_calibration(self) -> None:
        if self.audio.busy:
            return
        exercise = calibration_exercise()
        dialog = CalibrationDialog(exercise, self)
        dialog.rejected.connect(self._cancel_calibration)
        self.active_calibration = True
        self.active_assessment = False
        self.active_exercise = None
        self.calibration_exercise = exercise
        self.calibration_dialog = dialog
        self.calibrate.setEnabled(False)
        dialog.show()
        self.audio.play(
            exercise,
            self.bpm.value(),
            self.output_device.currentData(),
            input_device=self.input_device.currentData(),
            assess=True,
            include_notes=False,
            count_in_beats=CALIBRATION_COUNT_IN_BEATS,
            timing_offset=0.0,
            silent_click_steps=calibration_silent_click_steps(exercise),
        )

    def _cancel_calibration(self) -> None:
        if self.active_calibration:
            self.audio.stop()

    def start_practice(self, exercise: Exercise, assess: bool, start_step: int = 0) -> None:
        if self.audio.busy:
            return
        self._reset_menu_state()
        start_step = min(max(0, start_step), exercise.total_steps)
        if playback_end_step(exercise, start_step) is None:
            message = (
                "カーソル位置以降に再生する音符がありません。"
                if start_step > 0
                else "再生する音符がありません。"
            )
            QMessageBox.warning(self, "譜面が空です", message)
            return
        self.practice.set_running(True, assess)
        self.editor.set_running(True)
        self._play_exercise(
            exercise,
            self.bpm.value(),
            assess,
            count_in_beats=exercise.beats_per_bar,
            start_step=start_step,
        )

    def _play_exercise(
        self,
        exercise: Exercise,
        bpm: int,
        assess: bool,
        *,
        count_in_beats: int,
        start_step: int = 0,
    ) -> None:
        self.active_exercise = exercise
        self.active_assessment = assess
        self.active_bpm = bpm
        self.active_count_in_beats = count_in_beats
        self.practice.show_exercise(exercise)
        self.practice.prepare_staff(exercise, bpm, count_in_beats)
        # During assessment, the guide notes are muted so they cannot leak into pitch detection.
        self.audio.play(
            exercise, bpm, self.output_device.currentData(),
            input_device=self.input_device.currentData(), assess=assess,
            include_notes=not assess, count_in_beats=count_in_beats,
            start_step=start_step,
            timing_offset=self._timing_offset() if assess else 0.0,
        )

    def start_practice_menu(self, menu: PracticeMenu, assess: bool) -> None:
        if self.audio.busy:
            return
        items = []
        for item in menu.items:
            exercise = self.storage.get_exercise(item.exercise_id)
            if exercise is None or playback_end_step(exercise) is None:
                QMessageBox.warning(
                    self,
                    "練習メニューを開始できません",
                    "削除済み、または音符のない譜面が含まれています。",
                )
                return
            items.append((exercise, item.bpm))
        if not items:
            return
        self.active_menu_items = items
        self.active_menu_index = 0
        self.active_menu_name = menu.name
        self.active_menu_assessment = assess
        self.active_menu_phase = "exercise"
        self.active_menu_attempts = []
        self.active_menu_details = []
        self._menu_cancelled = False
        self.practice.set_running(True, assess)
        self.editor.set_running(True)
        self._start_menu_item(0)

    def _start_menu_item(self, index: int) -> None:
        if self._menu_cancelled or not 0 <= index < len(self.active_menu_items):
            self._finish_practice_menu(cancelled=True)
            return
        self.active_menu_index = index
        self.active_menu_phase = "exercise"
        exercise, bpm = self.active_menu_items[index]
        count_in = exercise.beats_per_bar if index == 0 else 0
        self.practice.set_menu_progress(
            index, len(self.active_menu_items), exercise.name, bpm,
            assess=self.active_menu_assessment,
        )
        self._play_exercise(
            exercise,
            bpm,
            self.active_menu_assessment,
            count_in_beats=count_in,
        )

    def _start_menu_interval(self) -> None:
        next_index = self.active_menu_index + 1
        if self._menu_cancelled or next_index >= len(self.active_menu_items):
            self._finish_practice_menu(cancelled=self._menu_cancelled)
            return
        exercise, bpm = self.active_menu_items[next_index]
        self.active_menu_phase = "interval"
        self.practice.set_menu_progress(
            next_index, len(self.active_menu_items), exercise.name, bpm, interval=True,
        )
        self.audio.play_interval(
            bpm, exercise.beats_per_bar, self.output_device.currentData()
        )

    def _stop_practice(self) -> None:
        if self.active_menu_phase is not None:
            self._menu_cancelled = True
        self.audio.stop()

    def _observation_detected(self, observed_time: float, midi: float, confidence: float) -> None:
        if self.active_assessment and not self.active_calibration:
            self.practice.add_detected_note(observed_time, midi)

    def _input_latency_changed(self, latency_seconds: float) -> None:
        if self.active_assessment:
            self.practice.set_input_latency(latency_seconds, self._timing_offset())

    def _position_changed(self, step: int) -> None:
        if self.active_calibration and self.calibration_dialog is not None:
            self.calibration_dialog.set_step(step)
        self.practice.preview_grid.set_playhead(step)
        self.practice.staff.set_playhead(step)
        self.practice.fretboard.set_playhead(step)
        self.editor.grid.set_playhead(step)
        self.editor.staff.set_playhead(step)
        self.editor.fretboard.set_playhead(step)

    def _playback_finished(self, observations: list, cancelled: bool) -> None:
        if self.active_calibration:
            QTimer.singleShot(100, self._restart_input_monitor)
            self._finish_calibration(observations, cancelled)
            return
        if self.active_menu_phase == "interval":
            if cancelled or self._menu_cancelled:
                self._finish_practice_menu(cancelled=True)
            else:
                QTimer.singleShot(50, lambda: self._start_menu_item(self.active_menu_index + 1))
            return
        if self.active_menu_phase == "exercise":
            if cancelled or self._menu_cancelled:
                self._finish_practice_menu(cancelled=True)
                return
            if self.active_menu_assessment:
                attempts, total = self._save_active_assessment(observations)
                self.active_menu_attempts.extend(attempts)
                self.active_menu_details.append(
                    (self.active_exercise.name, self.active_bpm, total)
                )
            if self.active_menu_index + 1 < len(self.active_menu_items):
                QTimer.singleShot(50, self._start_menu_interval)
            else:
                self._finish_practice_menu(cancelled=False)
            return

        QTimer.singleShot(100, self._restart_input_monitor)
        self.practice.set_running(False)
        self.editor.set_running(False)
        if cancelled or not self.active_assessment or not self.active_exercise:
            return
        attempts, total = self._save_active_assessment(observations)
        pitch, timing, _ = score_attempts(attempts)
        detected = sum(a.detected_midi is not None for a in attempts)
        QMessageBox.information(
            self, "採点結果",
            f"総合  {total:.0f}点\n\n音程  {pitch:.0f}点　　リズム  {timing:.0f}点\n"
            f"検出 {detected} / {len(attempts)} 音",
        )

    def _save_active_assessment(self, observations: list) -> tuple[list, float]:
        if self.active_exercise is None:
            return [], 0.0
        attempts = evaluate_performance(
            self.active_exercise, self.active_bpm, observations,
            count_in_beats=self.active_count_in_beats,
        )
        pitch, timing, total = score_attempts(attempts)
        result = SessionResult(
            exercise_id=self.active_exercise.id,
            exercise_name=self.active_exercise.name,
            bpm=self.active_bpm,
            started_at=datetime.now().isoformat(timespec="seconds"),
            pitch_score=pitch,
            timing_score=timing,
            total_score=total,
            attempts=attempts,
        )
        self.storage.save_session(result)
        self.progress.reload()
        return attempts, total

    def _finish_practice_menu(self, *, cancelled: bool) -> None:
        QTimer.singleShot(100, self._restart_input_monitor)
        self.practice.set_running(False)
        self.editor.set_running(False)
        if not cancelled and self.active_menu_assessment and self.active_menu_attempts:
            pitch, timing, total = score_attempts(self.active_menu_attempts)
            details = "\n".join(
                f"{index + 1}. {name}  {bpm} BPM: {score:.0f}点"
                for index, (name, bpm, score) in enumerate(self.active_menu_details)
            )
            detected = sum(
                attempt.detected_midi is not None for attempt in self.active_menu_attempts
            )
            QMessageBox.information(
                self,
                f"「{self.active_menu_name}」採点結果",
                f"総合  {total:.0f}点\n\n音程  {pitch:.0f}点　　リズム  {timing:.0f}点\n"
                f"検出 {detected} / {len(self.active_menu_attempts)} 音\n\n{details}",
            )
        self._reset_menu_state()

    def _reset_menu_state(self) -> None:
        self.active_menu_items = []
        self.active_menu_index = -1
        self.active_menu_name = ""
        self.active_menu_assessment = False
        self.active_menu_phase = None
        self.active_menu_attempts = []
        self.active_menu_details = []
        self._menu_cancelled = False

    def _finish_calibration(self, observations: list, cancelled: bool) -> None:
        dialog = self.calibration_dialog
        exercise = self.calibration_exercise
        self.active_calibration = False
        self.calibration_dialog = None
        self.calibration_exercise = None
        self.calibrate.setEnabled(True)
        if dialog is not None:
            dialog.accept()
        if cancelled or exercise is None:
            self._update_calibration_label()
            return
        estimate = estimate_timing_calibration(
            exercise,
            self.bpm.value(),
            observations,
            count_in_beats=CALIBRATION_COUNT_IN_BEATS,
        )
        if estimate is None:
            QMessageBox.warning(
                self,
                "校正できませんでした",
                "各弦の正しい開放弦を検出できませんでした。\n"
                "入力レベルとチューニングを確認して、もう一度お試しください。",
            )
            self._update_calibration_label()
            return
        key = f"timing_calibration/{self._device_pair_key()}"
        self.settings.setValue(f"{key}/offset_seconds", estimate.offset_seconds)
        self.settings.setValue(f"{key}/input", self.input_device.currentText())
        self.settings.setValue(f"{key}/output", self.output_device.currentText())
        self.settings.sync()
        self._update_calibration_label()
        lines = []
        names = {40: "6弦", 45: "5弦", 50: "4弦", 55: "3弦", 59: "2弦", 64: "1弦"}
        for midi in (40, 45, 50, 55, 59, 64):
            values = estimate.errors_by_midi[midi]
            lines.append(f"{names[midi]}: {median(values) * 1000:+.0f} ms")
        QMessageBox.information(
            self,
            "タイミング校正が完了しました",
            f"適用する補正: {estimate.offset_seconds * 1000:+.0f} ms\n\n"
            + "\n".join(lines),
        )

    def _audio_error(self, message: str) -> None:
        if self.active_calibration:
            self._finish_calibration([], True)
        self.practice.set_running(False)
        self.editor.set_running(False)
        self._menu_cancelled = True
        QMessageBox.critical(self, "音声エラー", message)

    def edit_exercise(self, exercise: Exercise) -> None:
        self.editor.load_exercise(exercise)
        self.show_page(1)

    def _exercise_saved(self) -> None:
        self.practice.reload()

    def closeEvent(self, event) -> None:  # noqa: ANN001, N802
        self._closing = True
        self.audio.stop()
        self.audio.stop_metronome()
        self.audio.stop_input_monitor()
        self.settings.setValue("bpm", self.bpm.value())
        if self.input_device.currentData() is not None:
            self.settings.setValue("input_device", self.input_device.currentData())
        if self.output_device.currentData() is not None:
            self.settings.setValue("output_device", self.output_device.currentData())
        self.storage.close()
        super().closeEvent(event)

