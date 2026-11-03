from __future__ import annotations

from gt_trainer.models import Exercise, TabNote
from gt_trainer.storage import Storage


def test_exercise_round_trip(tmp_path) -> None:
    storage = Storage(tmp_path / "test.db")
    exercise = storage.save_exercise(Exercise(name="test", notes=[TabNote(2, 5, 3, technique="h")]))
    loaded = storage.get_exercise(exercise.id)
    assert loaded is not None
    assert loaded.name == "test"
    assert loaded.notes[0].midi_note == 43
    assert loaded.notes[0].technique == "h"
    storage.close()

