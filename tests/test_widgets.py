from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLineEdit,
    QMessageBox,
    QStyleOptionViewItem,
)

from gt_trainer.staff import StaffWidget
from gt_trainer.storage import Storage
from gt_trainer.music import calibration_exercise
from gt_trainer.widgets import CalibrationDialog, EditorPage, TabGrid


def test_calibration_dialog_prompts_open_strings_in_order() -> None:
    application = QApplication.instance() or QApplication([])
    dialog = CalibrationDialog(calibration_exercise())

    dialog.set_step(-4)
    assert "次は6弦開放" in dialog.current.text()
    assert "カウント 4" in dialog.current.text()
    dialog.set_step(-1)
    assert "カウント 1" in dialog.current.text()
    dialog.set_step(0)
    assert "今：6弦開放" in dialog.current.text()
    dialog.set_step(1)
    assert "次は5弦開放" in dialog.current.text()
    assert "休止中（あと2拍）" in dialog.current.text()
    dialog.set_step(2)
    assert "休止中（あと1拍）" in dialog.current.text()
    dialog.set_step(3)
    assert "カウント 4" in dialog.current.text()
    dialog.set_step(6)
    assert "カウント 1" in dialog.current.text()
    dialog.set_step(7)
    assert "今：5弦開放" in dialog.current.text()

    dialog.close()
    application.processEvents()


def test_tab_grid_advances_right_after_edit() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.setCurrentCell(2, 3)

    grid._advance_after_edit(2, 3)

    assert grid.currentRow() == 2
    assert grid.currentColumn() == 4
    grid.close()
    application.processEvents()


def test_tab_edit_auditions_all_notes_at_same_position() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(5, 3).setText("3")
    heard = []
    grid.audition_requested.connect(heard.append)
    index = grid.model().index(2, 3)
    option = QStyleOptionViewItem()
    editor = grid.itemDelegate().createEditor(grid.viewport(), option, index)
    editor.setText("7")

    grid.itemDelegate().setModelData(editor, grid.model(), index)

    assert heard == [[62, 43]]
    editor.close()
    grid.close()
    application.processEvents()


def test_tab_grid_has_pixel_horizontal_scroll_and_no_vertical_scroll() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()

    assert grid.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert grid.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
    grid.close()
    application.processEvents()


def test_tab_grid_allows_drag_range_selection() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()

    assert grid.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    assert grid.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectItems
    grid.close()
    application.processEvents()


def test_tab_editor_expands_so_full_fret_input_is_visible() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, grid.columnWidth(0), grid.rowHeight(0))
    editor = grid.itemDelegate().createEditor(grid.viewport(), option, grid.model().index(0, 0))

    grid.itemDelegate().updateEditorGeometry(editor, option, grid.model().index(0, 0))

    assert editor.width() >= 64
    assert editor.width() > grid.columnWidth(0)
    editor.close()
    grid.close()
    application.processEvents()


def test_tab_header_has_bar_and_beat_rows() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.configure(total_steps=24, steps_per_beat=3)
    header = grid.horizontalHeader()

    assert header.height() == header.row_height * 2
    assert header.steps_per_beat == 3
    assert header.beats_per_bar == 4
    assert header.bar_geometry(0).width() == 12 * grid.columnWidth(0)
    assert header.bar_geometry(1).width() == 12 * grid.columnWidth(0)
    grid.close()
    application.processEvents()


def test_tab_grid_height_keeps_all_six_rows_visible() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.resize(400, grid.height())
    grid.show()
    application.processEvents()

    assert grid.viewport().height() >= sum(grid.rowHeight(row) for row in range(grid.rowCount()))
    assert not grid.verticalScrollBar().isVisible()
    grid.close()
    application.processEvents()


def test_delete_key_clears_selected_tab_cell() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(2, 3).setText("7h")
    grid.setCurrentCell(2, 3)

    grid.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))

    assert grid.item(2, 3).text() == ""
    grid.close()
    application.processEvents()


def test_delete_key_does_not_change_read_only_preview() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(1, 2).setText("5")
    grid.setCurrentCell(1, 2)
    grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    grid.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))

    assert grid.item(1, 2).text() == "5"
    grid.close()
    application.processEvents()


def test_ctrl_z_and_ctrl_y_undo_and_redo_tab_input() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(2, 3).setText("7h")
    grid.item(2, 4).setText("9")

    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier,
    ))

    assert grid.item(2, 3).text() == "7h"
    assert grid.item(2, 4).text() == ""
    assert (grid.currentRow(), grid.currentColumn()) == (2, 4)

    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier,
    ))

    assert grid.item(2, 4).text() == "9"
    grid.close()
    application.processEvents()


def test_new_tab_input_after_undo_discards_redo_history() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(1, 1).setText("3")
    grid.item(1, 2).setText("5")
    grid.undo_edit()
    grid.item(1, 3).setText("7")

    grid.redo_edit()

    assert grid.item(1, 2).text() == ""
    assert grid.item(1, 3).text() == "7"
    grid.close()
    application.processEvents()


def test_ctrl_z_reaches_tab_history_from_unchanged_cell_editor() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(3, 5).setText("12")
    editor = QLineEdit(grid)
    editor.setModified(False)

    handled = grid.itemDelegate().eventFilter(editor, QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier,
    ))
    application.processEvents()

    assert handled
    assert grid.item(3, 5).text() == ""
    editor.close()
    grid.close()
    application.processEvents()


def test_copy_and_paste_preserves_strings_regardless_of_paste_row() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(1, 2).setText("5h")
    grid.item(1, 3).setText("7")
    grid.item(2, 2).setText("9")
    grid.item(2, 3).setText("")
    grid.clearSelection()
    for row in (1, 2):
        for column in (2, 3):
            grid.item(row, column).setSelected(True)
    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier,
    ))
    for paste_row in (0, 5):
        grid.setCurrentCell(paste_row, 6)
        grid.keyPressEvent(QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier,
        ))

        assert grid.item(1, 6).text() == "5h"
        assert grid.item(1, 7).text() == "7"
        assert grid.item(2, 6).text() == "9"
        assert grid.item(2, 7).text() == ""
        assert grid.item(paste_row, 6).text() == ("" if paste_row != 1 else "5h")

        grid.undo_edit()

        assert grid.item(1, 6).text() == ""
        assert grid.item(1, 7).text() == ""
        assert grid.item(2, 6).text() == ""
    QApplication.clipboard().clear()
    grid.close()
    application.processEvents()


def test_ctrl_x_cuts_selection_and_can_be_undone() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(1, 2).setText("5h")
    grid.item(2, 2).setText("9")
    grid.clearSelection()
    grid.item(1, 2).setSelected(True)
    grid.item(2, 2).setSelected(True)

    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier,
    ))

    assert grid.item(1, 2).text() == ""
    assert grid.item(2, 2).text() == ""
    assert QApplication.clipboard().text() == "5h\n9"

    grid.undo_edit()

    assert grid.item(1, 2).text() == "5h"
    assert grid.item(2, 2).text() == "9"
    QApplication.clipboard().clear()
    grid.close()
    application.processEvents()


def test_ctrl_arrow_moves_selected_frets_and_preserves_technique() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(2, 3).setText("7h")
    grid.item(2, 4).setText("9")
    grid.clearSelection()
    grid.item(2, 3).setSelected(True)
    grid.item(2, 4).setSelected(True)

    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier,
    ))

    assert grid.item(2, 3).text() == "8h"
    assert grid.item(2, 4).text() == "10"

    grid.undo_edit()

    assert grid.item(2, 3).text() == "7h"
    assert grid.item(2, 4).text() == "9"
    grid.close()
    application.processEvents()


def test_out_of_range_fret_move_confirms_and_moves_only_valid_notes(monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(1, 1).setText("24")
    grid.item(1, 2).setText("12")
    grid.clearSelection()
    grid.item(1, 1).setSelected(True)
    grid.item(1, 2).setSelected(True)
    questions = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: questions.append(args) or QMessageBox.StandardButton.Yes,
    )

    grid.move_selected_frets(1)

    assert questions
    assert grid.item(1, 1).text() == "24"
    assert grid.item(1, 2).text() == "13"
    grid.close()
    application.processEvents()


def test_ctrl_down_moves_selected_notes_to_next_string() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.item(1, 3).setText("5")
    grid.item(2, 4).setText("7p")
    grid.clearSelection()
    grid.item(1, 3).setSelected(True)
    grid.item(2, 4).setSelected(True)

    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier,
    ))

    assert grid.item(1, 3).text() == ""
    assert grid.item(2, 3).text() == "5"
    assert grid.item(2, 4).text() == ""
    assert grid.item(3, 4).text() == "7p"
    assert grid.item(2, 3).isSelected()
    assert grid.item(3, 4).isSelected()
    grid.close()
    application.processEvents()


def test_staff_uses_same_pixel_timeline_as_tab() -> None:
    application = QApplication.instance() or QApplication([])
    staff = StaffWidget()
    staff.set_timeline_view(scroll_offset=76, pixels_per_step=38, left=31)

    assert staff._step_x(2) == 50.0
    assert staff._step_boundary_x(2) == 31.0
    staff.close()
    application.processEvents()


def test_playhead_scroll_keeps_one_bar_ahead_visible() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.configure(total_steps=96, steps_per_beat=4, beats_per_bar=4)
    grid.resize(760, grid.height())
    grid.show()
    application.processEvents()

    grid.set_playhead(24)
    application.processEvents()

    header = grid.horizontalHeader()
    current_left = header.sectionViewportPosition(24)
    bar_last = 24 + 4 * 4 - 1
    bar_right = (
        header.sectionViewportPosition(bar_last) + header.sectionSize(bar_last)
    )
    assert grid.horizontalScrollBar().value() > 0
    assert current_left >= 0
    assert bar_right <= grid.viewport().width()
    grid.close()
    application.processEvents()


def test_editor_staff_follows_tab_horizontal_scroll(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    storage = Storage(tmp_path / "timeline.db")
    page = EditorPage(storage)
    page.resize(600, 600)
    page.bars.setValue(8)
    page.show()
    application.processEvents()

    page.grid.horizontalScrollBar().setValue(240)
    application.processEvents()

    assert page.staff.scroll_offset == page.grid.horizontalScrollBar().value()
    assert page.staff.pixels_per_step == page.grid.columnWidth(0)
    assert page.staff.timeline_left == page.grid.viewport().x()
    page.close()
    storage.close()
    application.processEvents()


def test_editor_offers_triplet_subdivisions(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    storage = Storage(tmp_path / "subdivisions.db")
    page = EditorPage(storage)

    values = [page.subdivision.itemData(index) for index in range(page.subdivision.count())]
    labels = [page.subdivision.itemText(index) for index in range(page.subdivision.count())]

    assert values == [1, 2, 3, 4, 6]
    assert labels == ["4分音符", "8分音符", "12分音符", "16分音符", "24分音符"]
    assert page.subdivision.currentData() == 4
    page.close()
    storage.close()
    application.processEvents()


def test_editor_allows_up_to_256_bars_without_resizing_during_typing(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    storage = Storage(tmp_path / "bar_count.db")
    page = EditorPage(storage)

    assert page.bars.minimum() == 1
    assert page.bars.maximum() == 256
    assert not page.bars.keyboardTracking()
    assert page.bars.isAccelerated()
    assert "256" in page.bars.toolTip()

    page.bars.setValue(256)

    assert page.grid.columnCount() == 256 * 4 * page.subdivision.currentData()
    assert page.build_exercise().bars == 256

    page.close()
    storage.close()
    application.processEvents()


def test_editor_can_preview_from_start_or_cursor_and_stop(tmp_path) -> None:
    application = QApplication.instance() or QApplication([])
    storage = Storage(tmp_path / "editor_preview.db")
    page = EditorPage(storage)
    previews = []
    stops = []
    page.preview_requested.connect(
        lambda exercise, start_step: previews.append((exercise, start_step))
    )
    page.stop_requested.connect(lambda: stops.append(True))
    page.grid.item(2, 9).setText("7")

    page.play_from_start_button.click()
    page.grid.setCurrentCell(5, 6)
    page.play_from_cursor_button.click()

    assert [start_step for _, start_step in previews] == [0, 6]
    assert previews[1][0].notes[0].step == 9

    page.set_running(True)
    assert not page.play_from_start_button.isEnabled()
    assert not page.play_from_cursor_button.isEnabled()
    assert page.stop_button.isEnabled()
    page.stop_button.click()
    assert stops == [True]

    page.close()
    storage.close()
    application.processEvents()

