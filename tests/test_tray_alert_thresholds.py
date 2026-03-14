from pathlib import Path


def test_tray_alert_thresholds_and_menu_red_markup_are_applied():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')

    assert 'cpu_alert = cpu_usage > 80' in app_code
    assert 'temp_alert = cpu_temp > 80' in app_code
    assert 'ram_alert = ram_percent > 90' in app_code
    assert "cpu_or_temp_alert = cpu_alert or temp_alert" in app_code
    assert "child.set_markup(f\"<span foreground='red'>{escape(text)}</span>\")" in app_code
    assert 'self._set_menu_item_text(self.cpu_temp_item, cpu_text, cpu_or_temp_alert)' in app_code
    assert 'self._set_menu_item_text(self.ram_item, ram_text, ram_alert)' in app_code
