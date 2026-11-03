"""cx_Freeze configuration for the Windows Guitar Trainer release."""

from __future__ import annotations

import sys

from cx_Freeze import Executable, setup


build_exe_options = {
    "build_exe": "dist/gt_trainer",
    "packages": [
        "gt_trainer",
        "numpy",
        "pyqtgraph",
        "sounddevice",
        "cffi",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    "includes": [
        "_cffi_backend",
        "sqlite3",
    ],
    "excludes": [
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtNetwork",
        "PySide6.QtPdf",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "tkinter",
        "unittest",
    ],
    "include_msvcr": True,
    "optimize": 1,
    "zip_include_packages": ["encodings"],
    "zip_exclude_packages": ["*"],
}

base = "gui" if sys.platform == "win32" else None

setup(
    name="GuitarTrainer",
    version="0.1.0",
    description="TAB, metronome, and performance analysis for guitar practice",
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            "guitar_trainer.pyw",
            base=base,
            target_name="GuitarTrainer.exe" if sys.platform == "win32" else "GuitarTrainer",
            shortcut_name="Guitar Trainer",
            shortcut_dir="DesktopFolder",
        )
    ],
)

