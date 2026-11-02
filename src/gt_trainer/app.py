from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow
from .models import Exercise, TabNote
from .storage import Storage


STYLESHEET = """
* { font-family: "Noto Sans CJK JP", "Yu Gothic UI", sans-serif; font-size: 13px; }
QMainWindow, QWidget { background: #111722; color: #e7edf6; }
#sidebar { background: #0b1018; border-right: 1px solid #263043; }
#toolbar { background: #151c28; border-bottom: 1px solid #293347; }
#logo { color: #63d7b5; font-size: 21px; font-weight: 800; letter-spacing: 2px; }
#pageTitle { font-size: 26px; font-weight: 700; }
#muted { color: #8692a7; }
#navButton { text-align: left; padding: 12px 14px; border: 0; border-radius: 7px; color: #aab5c6; }
#navButton:hover { background: #171f2d; color: white; }
#navButton:checked { background: #203a39; color: #72e2bf; font-weight: 700; }
QPushButton { background: #222b3a; border: 1px solid #344158; padding: 8px 14px; border-radius: 6px; }
QPushButton:hover { background: #2b3648; }
QPushButton:disabled { color: #5f697a; background: #191f2a; }
#primaryButton { background: #40b994; color: #07130f; border-color: #58d1ac; font-weight: 700; }
#primaryButton:hover { background: #59cfaa; }
QLineEdit, QSpinBox, QComboBox { background: #171e2a; border: 1px solid #344158; padding: 7px; border-radius: 5px; }
QComboBox::drop-down { border: 0; width: 22px; }
QGroupBox { background: #151c28; border: 1px solid #293449; border-radius: 9px; margin-top: 9px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #b9c4d5; }
QTableWidget { background: #181e29; alternate-background-color: #1c2330; border: 1px solid #303b50; gridline-color: #30394b; selection-background-color: #3b5564; }
QHeaderView::section { background: #202735; color: #9eabc0; border: 0; border-right: 1px solid #30394b; padding: 6px; }
#statusPill { background: #171f2b; border: 1px solid #2f3c51; border-radius: 7px; padding: 10px; color: #9facc0; }
#summaryCard { background: #17252a; border: 1px solid #2b5b53; border-radius: 8px; padding: 16px; color: #79dfc1; font-size: 16px; font-weight: 700; }
QToolTip { background: #293449; color: white; border: 1px solid #52617a; }
"""


def seed_data(storage: Storage) -> None:
    if storage.list_exercises():
        return
    notes = [TabNote(step=i, string=5 - (i // 4), fret=i % 4) for i in range(16)]
    storage.save_exercise(Exercise(name="クロマチック基礎", notes=notes))


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("Guitar Trainer")
    application.setOrganizationName("gt-trainer")
    application.setStyle("Fusion")
    application.setFont(QFont("Noto Sans CJK JP", 10))
    application.setStyleSheet(STYLESHEET)
    storage = Storage()
    seed_data(storage)
    window = MainWindow(storage)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())

