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
from gt_trainer.widgets import EditorPage, TabGrid


def test_tab_grid_advances_right_after_edit() -> None:
    application = QApplication.instance() or QApplication([])
    grid = TabGrid()
    grid.setCurrentCell(2, 3)

    grid._advance_after_edit(2, 3)

    assert grid.currentRow() == 2
    assert grid.currentColumn() == 4
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


def test_copy_and_paste_selected_rectangle_as_one_undo_step() -> None:
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
    grid.setCurrentCell(3, 6)

    grid.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier,
    ))

    assert grid.item(3, 6).text() == "5h"
    assert grid.item(3, 7).text() == "7"
    assert grid.item(4, 6).text() == "9"
    assert grid.item(4, 7).text() == ""

    grid.undo_edit()

    assert grid.item(3, 6).text() == ""
    assert grid.item(3, 7).text() == ""
    assert grid.item(4, 6).text() == ""
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
    staff.close()
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

