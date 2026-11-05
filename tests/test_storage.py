from __future__ import annotations

from gt_trainer.models import (
    Exercise,
    PracticeMenu,
    PracticeMenuItem,
    SessionResult,
    TabNote,
)
from gt_trainer.storage import Storage


def test_exercise_round_trip(tmp_path) -> None:
    storage = Storage(tmp_path / "test.db")
    exercise = storage.save_exercise(Exercise(
        name="test", key_root=9, notes=[TabNote(2, 5, 3, technique="h")],
    ))
    loaded = storage.get_exercise(exercise.id)
    assert loaded is not None
    assert loaded.name == "test"
    assert loaded.notes[0].midi_note == 43
    assert loaded.notes[0].technique == "h"
    assert loaded.key_root == 9
    storage.close()


def test_legacy_exercise_without_key_remains_compatible() -> None:
    exercise = Exercise.from_dict({
        "name": "legacy",
        "notes": [{"step": 0, "string": 5, "fret": 0}],
    })

    assert exercise.key_root is None


def test_practice_menu_round_trip_preserves_duplicates_and_bpms(tmp_path) -> None:
    storage = Storage(tmp_path / "menus.db")
    exercise = storage.save_exercise(Exercise(name="scale", notes=[TabNote(0, 5, 0)]))
    menu = storage.save_practice_menu(PracticeMenu(
        name="朝の基礎練習",
        items=[
            PracticeMenuItem(exercise.id, 60),
            PracticeMenuItem(exercise.id, 70),
        ],
    ))

    loaded = storage.get_practice_menu(menu.id)

    assert loaded is not None
    assert loaded.name == "朝の基礎練習"
    assert [(item.exercise_id, item.bpm) for item in loaded.items] == [
        (exercise.id, 60),
        (exercise.id, 70),
    ]
    storage.close()


def _save_result(
    storage: Storage,
    exercise: Exercise,
    bpm: int,
    score: float,
    started_at: str,
    *,
    menu_run_id: str | None = None,
    menu_name: str | None = None,
    menu_item_index: int | None = None,
) -> None:
    storage.save_session(SessionResult(
        exercise_id=exercise.id,
        exercise_name=exercise.name,
        bpm=bpm,
        started_at=started_at,
        pitch_score=score,
        timing_score=score,
        total_score=score,
        attempts=[],
        menu_run_id=menu_run_id,
        menu_name=menu_name,
        menu_item_index=menu_item_index,
    ))


def test_sessions_are_listed_by_exact_exercise_and_bpm(tmp_path) -> None:
    storage = Storage(tmp_path / "conditions.db")
    first = storage.save_exercise(Exercise(name="譜面A"))
    second = storage.save_exercise(Exercise(name="譜面B"))
    _save_result(storage, first, 60, 50, "2026-01-01T10:00:00")
    _save_result(storage, first, 70, 60, "2026-01-02T10:00:00")
    _save_result(storage, second, 60, 70, "2026-01-03T10:00:00")

    conditions = storage.list_session_conditions()

    assert {
        (row["exercise_id"], row["bpm"], row["session_count"])
        for row in conditions
    } == {
        (first.id, 60, 1), (first.id, 70, 1), (second.id, 60, 1),
    }
    assert [row["total_score"] for row in storage.list_sessions(first.id, 60)] == [50]
    storage.close()


def test_only_completed_practice_menu_runs_are_reported(tmp_path) -> None:
    storage = Storage(tmp_path / "menu_runs.db")
    exercise = storage.save_exercise(Exercise(name="譜面A"))
    first_run = storage.start_practice_menu_run(
        1, "基礎", "2026-01-01T10:00:00",
    )
    _save_result(
        storage, exercise, 60, 50, "2026-01-01T10:01:00",
        menu_run_id=first_run, menu_name="基礎", menu_item_index=0,
    )
    _save_result(
        storage, exercise, 70, 70, "2026-01-01T10:02:00",
        menu_run_id=first_run, menu_name="基礎", menu_item_index=1,
    )
    storage.complete_practice_menu_run(first_run, "2026-01-01T10:03:00")
    interrupted_run = storage.start_practice_menu_run(
        1, "基礎", "2026-01-02T10:00:00",
    )
    _save_result(
        storage, exercise, 60, 99, "2026-01-02T10:01:00",
        menu_run_id=interrupted_run, menu_name="基礎", menu_item_index=0,
    )

    sessions = storage.list_completed_menu_sessions("基礎")

    assert storage.list_completed_menu_names() == ["基礎"]
    assert [row["menu_run_id"] for row in sessions] == [first_run, first_run]
    assert [row["bpm"] for row in sessions] == [60, 70]
    storage.close()

