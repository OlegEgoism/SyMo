from pathlib import Path


def test_tray_alert_thresholds_and_red_markup_are_applied():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')

    assert 'cpu_alert = cpu_usage > 80' in app_code
    assert 'temp_alert = cpu_temp > 80' in app_code
    assert 'ram_alert = ram_percent > 90' in app_code
    assert "return f\"<span foreground='red'>{safe_text}</span>\"" in app_code
    assert 'cpu_temp_text = tray_value(f"🌡{cpu_temp}°C", temp_alert)' in app_code
