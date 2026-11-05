from __future__ import annotations

from gt_trainer.models import Exercise, PracticeMenu, PracticeMenuItem, TabNote
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

