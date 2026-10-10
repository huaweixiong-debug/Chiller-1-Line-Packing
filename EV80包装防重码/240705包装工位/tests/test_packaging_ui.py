import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from python_app.models import PACKAGE_SIZE
from python_app.ui import slot_grid_positions


def test_fixed_slot_grid_has_twelve_unique_positions():
    positions = slot_grid_positions()
    assert len(positions) == PACKAGE_SIZE
    assert len(set(positions)) == PACKAGE_SIZE
    assert positions[0] == (0, 0)
    assert positions[-1] == (11, 0)


def test_slot_grid_positions_support_variable_quantity():
    from python_app.ui import slot_grid_positions

    one_column = slot_grid_positions(12)
    assert one_column[0] == (0, 0) and one_column[-1] == (11, 0)

    two_columns = slot_grid_positions(30)
    assert len(two_columns) == 30
    assert two_columns[0] == (0, 0)
    assert two_columns[11] == (11, 0)
    assert two_columns[12] == (0, 1)
    assert two_columns[-1] == (5, 2)
    assert max(row for row, _ in two_columns) == 11


def test_classify_scan_routes_by_length():
    from python_app.models import StationConfig
    from python_app.ui import classify_scan

    config = StationConfig()
    assert classify_scan("1" * config.serial_length, config) == "serial"
    assert classify_scan("1" * (config.serial_length - 1), config) == "serial"
    assert classify_scan("C" * config.pack_min_length, config) == "customer"
    assert classify_scan("C" * (config.pack_min_length + 3), config) == "customer"

    site_config = StationConfig(pack_min_length=22)
    assert classify_scan("E130025100202610100990", site_config) == "customer"


def test_product_slot_turns_green_when_filled():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from python_app.ui import ProductSlot

    app = QApplication.instance() or QApplication([])
    slot = ProductSlot(1)
    slot.set_product("LASER-001")
    assert slot.product_code == "LASER-001"
    assert "#dcfce7" in slot.styleSheet()
    slot.clear_product()
    assert slot.product_code == ""
    app.processEvents()
