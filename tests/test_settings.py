import json

from app_core import localization
from app_core.localization import format_uptime
from app_core.settings import normalize_settings, read_json, sanitize_ping_host


def test_corrupted_json_is_set_aside(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"cpu": false,')
    assert read_json(path) == {}
    assert not path.exists()
    assert [p.read_text() for p in tmp_path.glob("s.json.bad-*")] == ['{"cpu": false,']


def test_non_utf8_and_non_object_are_set_aside(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes(b'{"a": "\xff"}')
    assert read_json(path) == {} and not path.exists()
    path.write_text("[1, 2]")
    assert read_json(path) == {} and not path.exists()


def test_valid_and_missing_files(tmp_path):
    path = tmp_path / "s.json"
    assert read_json(path) == {}
    path.write_text(json.dumps({"cpu": False}))
    assert read_json(path) == {"cpu": False}


def test_normalize_settings_sanitizes_values():
    s = normalize_settings({"language": " RU ", "ping_host": "-f evil", "alert_ram_percent": 500,
                            "disk_path": "home", "log_interval_sec": 0, "graph_line_color": "#ABCDEF"})
    assert s["language"] == "ru"
    assert s["ping_host"] == "8.8.8.8"
    assert s["alert_ram_percent"] == 100
    assert s["disk_path"] == "/"
    assert s["log_interval_sec"] == 1
    assert s["graph_line_color_cpu"] == "#abcdef"
    assert normalize_settings({"language": "xx"})["language"] is None
    assert s["menu_order"][-1] == "show_system_info" and "battery" in s["menu_order"]


def test_ping_host():
    assert sanitize_ping_host("example.org") == "example.org"
    assert sanitize_ping_host("2001:db8::1") == "2001:db8::1"
    assert sanitize_ping_host("a b") == "8.8.8.8"


def test_unknown_language_falls_back_to_english():
    localization.set_language("xx")
    assert localization.get_language() == "en"


def test_format_uptime_plurals():
    localization.set_language("ru")
    try:
        assert format_uptime("1 day, 2:03:04") == "1 день, 2:03:04"
        assert format_uptime("3 days, 2:03:04") == "3 дня, 2:03:04"
        assert format_uptime("11 days, 2:03:04") == "11 дней, 2:03:04"
        assert format_uptime("2:03:04") == "2:03:04"
    finally:
        localization.set_language("en")
