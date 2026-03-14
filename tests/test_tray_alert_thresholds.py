from pathlib import Path


def test_only_exceeding_values_are_colored_red_in_menu_items():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')

    assert 'cpu_alert = cpu_usage > 80' in app_code
    assert 'temp_alert = cpu_temp > 80' in app_code
    assert 'ram_alert = ram_percent > 90' in app_code
    assert 'def _alert_markup_value(text: str, is_alert: bool) -> str:' in app_code
    assert "return f\"<span foreground='red'>{safe_text}</span>\"" in app_code
    assert 'self._alert_markup_value(cpu_usage_text, cpu_alert)' in app_code
    assert 'self._alert_markup_value(cpu_temp_text, temp_alert)' in app_code
    assert 'self._alert_markup_value(ram_usage_text, ram_alert)' in app_code
