from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, Signal

from .models import Exercise
from .music import PitchObservation, expected_events, frequency_to_midi, midi_to_frequency


SAMPLE_RATE = 48_000


def list_audio_devices() -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    import sounddevice as sd

    inputs: list[tuple[int, str]] = []
    outputs: list[tuple[int, str]] = []
    for index, device in enumerate(sd.query_devices()):
        label = f"{device['name']} ({device['hostapi']})"
        if device["max_input_channels"] > 0:
            inputs.append((index, label))
        if device["max_output_channels"] > 0:
            outputs.append((index, label))
    return inputs, outputs


def _pluck(frequency: float, duration: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    count = max(1, int(duration * sample_rate))
    t = np.arange(count, dtype=np.float32) / sample_rate
    # A compact guitar-like additive synth, deliberately dependency-free.
    wave = (
        np.sin(2 * np.pi * frequency * t)
        + 0.42 * np.sin(2 * np.pi * frequency * 2 * t + 0.2)
        + 0.18 * np.sin(2 * np.pi * frequency * 3 * t + 0.5)
    )
    attack = np.minimum(1.0, t / 0.006)
    envelope = attack * np.exp(-4.3 * t / max(duration, 0.1))
    return (wave * envelope * 0.18).astype(np.float32)


def _click(accent: bool, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    duration = 0.055 if accent else 0.035
    t = np.arange(int(duration * sample_rate), dtype=np.float32) / sample_rate
    frequency = 1760.0 if accent else 1180.0
    return (np.sin(2 * np.pi * frequency * t) * np.exp(-70 * t) * (0.65 if accent else 0.45)).astype(np.float32)


def render_exercise(
    exercise: Exercise,
    bpm: int,
    *,
    count_in_beats: int = 4,
    include_notes: bool = True,
    sample_rate: int = SAMPLE_RATE,
) -> np.ndarray:
    beat_seconds = 60.0 / bpm
    body_seconds = exercise.total_steps / exercise.steps_per_beat * beat_seconds
    total_seconds = count_in_beats * beat_seconds + body_seconds + 0.5
    audio = np.zeros(int(total_seconds * sample_rate), dtype=np.float32)

    total_beats = count_in_beats + exercise.beats_per_bar * exercise.bars
    for beat in range(total_beats):
        start = int(beat * beat_seconds * sample_rate)
        in_body = beat >= count_in_beats
        bar_beat = (beat - count_in_beats) % exercise.beats_per_bar if in_body else beat % exercise.beats_per_bar
        sound = _click(bar_beat == 0, sample_rate)
        audio[start:start + len(sound)] += sound

    if include_notes:
        step_seconds = beat_seconds / exercise.steps_per_beat
        offset = count_in_beats * beat_seconds
        for note in exercise.notes:
            start = int((offset + note.step * step_seconds) * sample_rate)
            duration = max(0.12, note.duration_steps * step_seconds * 0.88)
            sound = _pluck(midi_to_frequency(note.midi_note), duration, sample_rate)
            end = min(len(audio), start + len(sound))
            audio[start:end] += sound[:end - start]
    peak = float(np.max(np.abs(audio)))
    if peak > 0.95:
        audio *= 0.95 / peak
    return audio


def detect_pitch(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> tuple[float | None, float]:
    """Return fundamental frequency and a normalized autocorrelation confidence."""
    signal = np.asarray(samples, dtype=np.float32).reshape(-1)
    signal = signal - float(np.mean(signal))
    rms = float(np.sqrt(np.mean(signal * signal)))
    if len(signal) < 512 or rms < 0.006:
        return None, 0.0
    signal *= np.hanning(len(signal)).astype(np.float32)
    size = 1 << (len(signal) * 2 - 1).bit_length()
    spectrum = np.fft.rfft(signal, size)
    corr = np.fft.irfft(spectrum * np.conj(spectrum))[:len(signal)]
    corr /= max(float(corr[0]), 1e-9)
    min_lag = max(1, int(sample_rate / 1200.0))
    max_lag = min(len(corr) - 1, int(sample_rate / 65.0))
    region = corr[min_lag:max_lag]
    if not len(region):
        return None, 0.0
    # Choose the first strong local maximum to reduce octave errors.
    peak_value = float(np.max(region))
    threshold = max(0.35, peak_value * 0.86)
    candidates = np.where((region[1:-1] > region[:-2]) & (region[1:-1] >= region[2:]) & (region[1:-1] >= threshold))[0] + 1
    peak = int(candidates[0]) if len(candidates) else int(np.argmax(region))
    lag = peak + min_lag
    confidence = float(corr[lag])
    if confidence < 0.25:
        return None, confidence
    if 1 <= lag < len(corr) - 1:
        left, center, right = corr[lag - 1], corr[lag], corr[lag + 1]
        denominator = left - 2 * center + right
        if abs(denominator) > 1e-9:
            lag += float(0.5 * (left - right) / denominator)
    return sample_rate / lag, confidence


class AudioEngine(QObject):
    position_changed = Signal(int)
    playback_finished = Signal(list, bool)
    error = Signal(str)
    metronome_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._metronome_thread: threading.Thread | None = None
        self._metronome_stop = threading.Event()

    @property
    def busy(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def play(
        self,
        exercise: Exercise,
        bpm: int,
        output_device: int | None,
        *,
        input_device: int | None = None,
        assess: bool = False,
        include_notes: bool = True,
        count_in_beats: int = 4,
    ) -> None:
        if self.busy:
            return
        self.stop_metronome()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._play_worker,
            args=(exercise, bpm, output_device, input_device, assess, include_notes, count_in_beats),
            daemon=True,
        )
        self._thread.start()

    def _play_worker(
        self,
        exercise: Exercise,
        bpm: int,
        output_device: int | None,
        input_device: int | None,
        assess: bool,
        include_notes: bool,
        count_in_beats: int,
    ) -> None:
        import sounddevice as sd

        observations: list[PitchObservation] = []
        failed = False
        stream = None
        started = time.monotonic()
        previous_rms = 0.0
        last_observation = -1.0
        analysis_buffer = np.empty(0, dtype=np.float32)

        def input_callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
            nonlocal previous_rms, last_observation, analysis_buffer
            if status:
                return
            chunk = np.asarray(indata[:, 0], dtype=np.float32).copy()
            analysis_buffer = np.concatenate((analysis_buffer, chunk))[-4096:]
            rms = float(np.sqrt(np.mean(chunk * chunk)))
            now = time.monotonic() - started
            attack = rms > max(0.009, previous_rms * 1.35)
            periodic = rms > 0.012 and now - last_observation > 0.10
            if len(analysis_buffer) >= 2048 and (attack or periodic):
                frequency, confidence = detect_pitch(analysis_buffer)
                if frequency and confidence >= 0.32:
                    observations.append(PitchObservation(now, frequency_to_midi(frequency), confidence, rms))
                    last_observation = now
            previous_rms = previous_rms * 0.7 + rms * 0.3

        try:
            audio = render_exercise(
                exercise, bpm, count_in_beats=count_in_beats,
                include_notes=include_notes, sample_rate=SAMPLE_RATE,
            )
            if assess:
                stream = sd.InputStream(
                    device=input_device, channels=1, samplerate=SAMPLE_RATE,
                    blocksize=1024, callback=input_callback,
                )
                stream.start()
            started = time.monotonic()
            sd.play(audio, samplerate=SAMPLE_RATE, device=output_device, blocking=False)
            step_seconds = 60.0 / bpm / exercise.steps_per_beat
            body_start = count_in_beats * 60.0 / bpm
            last_step = -2
            while sd.get_stream().active and not self._stop.is_set():
                elapsed = time.monotonic() - started
                step = -1 if elapsed < body_start else int((elapsed - body_start) / step_seconds)
                if step != last_step:
                    self.position_changed.emit(step)
                    last_step = step
                time.sleep(0.015)
            sd.stop()
        except Exception as exc:  # PortAudio errors need to reach the GUI.
            failed = True
            self.error.emit(str(exc))
        finally:
            if stream is not None:
                stream.stop()
                stream.close()
            self.position_changed.emit(-1)
            self.playback_finished.emit(observations, self._stop.is_set() or failed)

    def stop(self) -> None:
        self._stop.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def start_metronome(self, bpm: int, beats_per_bar: int, output_device: int | None) -> None:
        if self._metronome_thread and self._metronome_thread.is_alive():
            return
        self._metronome_stop.clear()

        def worker() -> None:
            import sounddevice as sd
            beat = 0
            next_beat = time.monotonic()
            try:
                while not self._metronome_stop.is_set():
                    now = time.monotonic()
                    if now >= next_beat:
                        sd.play(_click(beat % beats_per_bar == 0), SAMPLE_RATE, device=output_device, blocking=False)
                        beat += 1
                        next_beat += 60.0 / bpm
                    self._metronome_stop.wait(max(0.001, min(0.02, next_beat - now)))
            except Exception as exc:
                self.error.emit(str(exc))
            finally:
                sd.stop()
                self.metronome_changed.emit(False)

        self._metronome_thread = threading.Thread(target=worker, daemon=True)
        self._metronome_thread.start()
        self.metronome_changed.emit(True)

    def stop_metronome(self) -> None:
        self._metronome_stop.set()
        thread = self._metronome_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.25)

