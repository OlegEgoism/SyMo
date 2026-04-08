from pathlib import Path


def test_display_poll_intervals_are_configured_with_expected_bounds():
    code = Path('app_core/dialogs.py').read_text(encoding='utf-8')
    assert 'POLL_INTERVAL_MIN_SEC = 1' in code
    assert 'POLL_INTERVAL_MAX_SEC = 60' in code
    assert "Gtk.SpinButton.new_with_range(POLL_INTERVAL_MIN_SEC, POLL_INTERVAL_MAX_SEC, 1)" in code


def test_app_uses_per_item_poll_interval_setting_keys():
    code = Path('app_core/app.py').read_text(encoding='utf-8')
    for key in (
        'tray_cpu_interval_sec',
        'tray_ram_interval_sec',
        'cpu_interval_sec',
        'ram_interval_sec',
        'net_interval_sec',
        'disk_interval_sec',
        'swap_interval_sec',
    ):
        assert key in code
