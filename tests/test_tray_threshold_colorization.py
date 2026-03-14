from pathlib import Path


def test_tray_cpu_and_ram_values_are_colorized_above_80_percent():
    code = Path('app_core/app.py').read_text(encoding='utf-8')

    assert "if cpu_usage > 80:" in code
    assert "if ram_percent > 80:" in code
    assert "<span foreground='red'>" in code
