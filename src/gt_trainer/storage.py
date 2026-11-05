from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from .models import Exercise, NoteAttempt, PracticeMenu, SessionResult


def default_database_path() -> Path:
    path = Path.home() / ".gt_trainer"
    path.mkdir(parents=True, exist_ok=True)
    return path / "trainer.db"


class Storage:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else default_database_path()
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS exercises (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exercise_id INTEGER,
                exercise_name TEXT NOT NULL,
                bpm INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                pitch_score REAL NOT NULL,
                timing_score REAL NOT NULL,
                total_score REAL NOT NULL,
                attempts TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS practice_menus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS practice_menu_runs (
                id TEXT PRIMARY KEY,
                menu_id INTEGER,
                menu_name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT
            );
        """)
        session_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(sessions)")
        }
        for name, column_type in (
            ("menu_run_id", "TEXT"),
            ("menu_name", "TEXT"),
            ("menu_item_index", "INTEGER"),
        ):
            if name not in session_columns:
                self.connection.execute(
                    f"ALTER TABLE sessions ADD COLUMN {name} {column_type}"
                )
        self.connection.commit()

    def save_exercise(self, exercise: Exercise) -> Exercise:
        payload = json.dumps(exercise.to_dict(), ensure_ascii=False)
        if exercise.id is None:
            cursor = self.connection.execute(
                "INSERT INTO exercises(name, data) VALUES (?, ?)", (exercise.name, payload)
            )
            exercise.id = int(cursor.lastrowid)
            payload = json.dumps(exercise.to_dict(), ensure_ascii=False)
            self.connection.execute("UPDATE exercises SET data=? WHERE id=?", (payload, exercise.id))
        else:
            self.connection.execute(
                "UPDATE exercises SET name=?, data=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (exercise.name, payload, exercise.id),
            )
        self.connection.commit()
        return exercise

    def list_exercises(self) -> list[Exercise]:
        rows = self.connection.execute("SELECT data FROM exercises ORDER BY updated_at DESC, id DESC")
        return [Exercise.from_dict(json.loads(row["data"])) for row in rows]

    def get_exercise(self, exercise_id: int) -> Exercise | None:
        row = self.connection.execute("SELECT data FROM exercises WHERE id=?", (exercise_id,)).fetchone()
        return Exercise.from_dict(json.loads(row["data"])) if row else None

    def delete_exercise(self, exercise_id: int) -> None:
        self.connection.execute("DELETE FROM exercises WHERE id=?", (exercise_id,))
        self.connection.commit()

    def save_practice_menu(self, menu: PracticeMenu) -> PracticeMenu:
        payload = json.dumps(menu.to_dict(), ensure_ascii=False)
        if menu.id is None:
            cursor = self.connection.execute(
                "INSERT INTO practice_menus(name, data) VALUES (?, ?)",
                (menu.name, payload),
            )
            menu.id = int(cursor.lastrowid)
            payload = json.dumps(menu.to_dict(), ensure_ascii=False)
            self.connection.execute(
                "UPDATE practice_menus SET data=? WHERE id=?", (payload, menu.id)
            )
        else:
            self.connection.execute(
                """UPDATE practice_menus
                   SET name=?, data=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (menu.name, payload, menu.id),
            )
        self.connection.commit()
        return menu

    def list_practice_menus(self) -> list[PracticeMenu]:
        rows = self.connection.execute(
            "SELECT data FROM practice_menus ORDER BY updated_at DESC, id DESC"
        )
        return [PracticeMenu.from_dict(json.loads(row["data"])) for row in rows]

    def get_practice_menu(self, menu_id: int) -> PracticeMenu | None:
        row = self.connection.execute(
            "SELECT data FROM practice_menus WHERE id=?", (menu_id,)
        ).fetchone()
        return PracticeMenu.from_dict(json.loads(row["data"])) if row else None

    def save_session(self, result: SessionResult) -> None:
        attempts = json.dumps([
            {field: getattr(a, field) for field in NoteAttempt.__dataclass_fields__}
            for a in result.attempts
        ], ensure_ascii=False)
        self.connection.execute(
            """INSERT INTO sessions(
                exercise_id, exercise_name, bpm, started_at,
                pitch_score, timing_score, total_score, attempts,
                menu_run_id, menu_name, menu_item_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (result.exercise_id, result.exercise_name, result.bpm, result.started_at,
             result.pitch_score, result.timing_score, result.total_score, attempts,
             result.menu_run_id, result.menu_name, result.menu_item_index),
        )
        self.connection.commit()

    def list_sessions(
        self,
        exercise_id: int | None = None,
        bpm: int | None = None,
        *,
        exercise_name: str | None = None,
    ) -> list[sqlite3.Row]:
        if exercise_id is None and bpm is None:
            return list(self.connection.execute("SELECT * FROM sessions ORDER BY started_at"))
        if exercise_id is None:
            if exercise_name is not None:
                return list(self.connection.execute(
                    """SELECT * FROM sessions
                       WHERE exercise_id IS NULL AND exercise_name=? AND bpm=?
                       ORDER BY started_at, id""",
                    (exercise_name, bpm),
                ))
            return list(self.connection.execute(
                "SELECT * FROM sessions WHERE exercise_id IS NULL AND bpm=? ORDER BY started_at, id",
                (bpm,),
            ))
        if bpm is not None:
            return list(self.connection.execute(
                """SELECT * FROM sessions
                   WHERE exercise_id=? AND bpm=? ORDER BY started_at, id""",
                (exercise_id, bpm),
            ))
        return list(self.connection.execute(
            "SELECT * FROM sessions WHERE exercise_id=? ORDER BY started_at, id", (exercise_id,)
        ))

    def list_session_conditions(self) -> list[sqlite3.Row]:
        return list(self.connection.execute(
            """SELECT exercise_id, exercise_name, bpm, COUNT(*) AS session_count,
                      MAX(started_at) AS latest_at
               FROM sessions
               GROUP BY exercise_id,
                        CASE WHEN exercise_id IS NULL THEN exercise_name ELSE '' END,
                        bpm
               ORDER BY latest_at DESC"""
        ))

    def start_practice_menu_run(
        self, menu_id: int | None, menu_name: str, started_at: str,
    ) -> str:
        run_id = uuid.uuid4().hex
        self.connection.execute(
            """INSERT INTO practice_menu_runs(id, menu_id, menu_name, started_at)
               VALUES (?, ?, ?, ?)""",
            (run_id, menu_id, menu_name, started_at),
        )
        self.connection.commit()
        return run_id

    def complete_practice_menu_run(self, run_id: str, completed_at: str) -> None:
        self.connection.execute(
            "UPDATE practice_menu_runs SET completed_at=? WHERE id=?",
            (completed_at, run_id),
        )
        self.connection.commit()

    def list_completed_menu_names(self) -> list[str]:
        return [row["menu_name"] for row in self.connection.execute(
            """SELECT menu_name, MAX(completed_at) AS latest
               FROM practice_menu_runs
               WHERE completed_at IS NOT NULL
               GROUP BY menu_name ORDER BY latest DESC"""
        )]

    def list_completed_menu_sessions(self, menu_name: str) -> list[sqlite3.Row]:
        return list(self.connection.execute(
            """SELECT s.*, r.started_at AS run_started_at
               FROM practice_menu_runs r
               JOIN sessions s ON s.menu_run_id = r.id
               WHERE r.menu_name=? AND r.completed_at IS NOT NULL
               ORDER BY r.started_at, r.id, s.menu_item_index""",
            (menu_name,),
        ))

    def close(self) -> None:
        self.connection.close()

