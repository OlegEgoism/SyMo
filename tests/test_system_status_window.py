from pathlib import Path


def test_system_status_window_contains_all_graph_panels_and_transparent_setup():
    app_code = Path('app_core/app.py').read_text(encoding='utf-8')

    assert 'def show_system_status_window(self, _w=None):' in app_code
    assert "window = Gtk.Window(title=tr('system_status'))" in app_code
    assert 'self._configure_transparent_window(window)' in app_code

    for key in [
        '("cpu", tr(\'cpu_info\'), self._draw_cpu_graph)',
        '("ram", tr(\'ram_loading\'), self._draw_ram_graph)',
        '("swap", tr(\'swap_loading\'), self._draw_swap_graph)',
        '("disk", tr(\'disk_loading\'), self._draw_disk_graph)',
        '("net", tr(\'lan_speed\'), self._draw_net_graph)',
        '("keyboard", tr(\'keyboard_clicks\'), self._draw_keyboard_graph)',
        '("mouse", tr(\'mouse_clicks\'), self._draw_mouse_graph)',
    ]:
        assert key in app_code

    assert 'window.set_app_paintable(True)' in app_code
    assert 'cr.set_source_rgba(0.05, 0.05, 0.05, 0.78)' in app_code
