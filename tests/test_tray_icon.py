import cairo

from app_core.settings import normalize_settings
from app_core.tray_icon import MeterIcon, quantize

BLUE, GREEN = (0.1, 0.8, 1.0), (0.3, 1.0, 0.3)


def test_quantize_steps_and_bounds():
    assert quantize(0) == 0 and quantize(2.4) == 0 and quantize(2.6) == 5
    assert quantize(-3) == 0 and quantize(120) == 100


def test_icon_changes_path_only_when_the_picture_changes(tmp_path):
    icon = MeterIcon(tmp_path)
    first = icon.update(41.0, 60.0, BLUE, GREEN)
    assert first is not None and first.exists()
    assert icon.update(39.0, 61.0, BLUE, GREEN) is None          # те же ступени 40 % и 60 %
    second = icon.update(70.0, 60.0, BLUE, GREEN)
    assert second is not None and second != first
    assert icon.update(70.0, 60.0, GREEN, BLUE) not in (None, second)
    surface = cairo.ImageSurface.create_from_png(str(second))
    assert (surface.get_width(), surface.get_height()) == (64, 64)
    icon.reset()
    assert icon.update(70.0, 60.0, BLUE, GREEN) == second


def test_tray_icon_setting():
    assert normalize_settings({})["tray_icon"] == "logo"
    assert normalize_settings({"tray_icon": "meter"})["tray_icon"] == "meter"
    assert normalize_settings({"tray_icon": "rainbow"})["tray_icon"] == "logo"
