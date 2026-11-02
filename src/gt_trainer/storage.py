from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import Exercise, NoteAttempt, SessionResult


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
        """)
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

    def save_session(self, result: SessionResult) -> None:
        attempts = json.dumps([
            {field: getattr(a, field) for field in NoteAttempt.__dataclass_fields__}
            for a in result.attempts
        ], ensure_ascii=False)
        self.connection.execute(
            """INSERT INTO sessions(
                exercise_id, exercise_name, bpm, started_at,
                pitch_score, timing_score, total_score, attempts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (result.exercise_id, result.exercise_name, result.bpm, result.started_at,
             result.pitch_score, result.timing_score, result.total_score, attempts),
        )
        self.connection.commit()

    def list_sessions(self, exercise_id: int | None = None) -> list[sqlite3.Row]:
        if exercise_id is None:
            return list(self.connection.execute("SELECT * FROM sessions ORDER BY started_at"))
        return list(self.connection.execute(
            "SELECT * FROM sessions WHERE exercise_id=? ORDER BY started_at", (exercise_id,)
        ))

    def close(self) -> None:
        self.connection.close()

