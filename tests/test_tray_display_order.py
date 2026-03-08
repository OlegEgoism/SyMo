from app_core.tray_display import (
    normalize_tray_order,
    ordered_tray_parts,
    parse_tray_order_text,
)


def test_normalize_tray_order_removes_invalid_and_duplicates():
    assert normalize_tray_order(["ram", "cpu", "ram", "bad"]) == ["ram", "cpu"]


def test_normalize_tray_order_falls_back_to_default():
    assert normalize_tray_order([]) == ["cpu", "ram"]


def test_parse_tray_order_text_supports_semicolon_separator():
    assert parse_tray_order_text("ram; cpu") == ["ram", "cpu"]


def test_ordered_tray_parts_uses_requested_order():
    parts = ordered_tray_parts({"cpu": "CPU: 20%", "ram": "RAM: 3.1GB"}, ["ram", "cpu"])
    assert parts == ["RAM: 3.1GB", "CPU: 20%"]
