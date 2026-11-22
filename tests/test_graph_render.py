import cairo

from app_core.graph_render import _x_positions, build_graph_specs, nearest_index, render_graph


def _render(spec_key, samples, **kw):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 720, 340)
    render_graph(cairo.Context(surface), build_graph_specs()[spec_key], samples, 720, 340,
                 lambda key: (1.0, 0.0, 0.0), **kw)
    return surface


def test_renders_without_temperature_and_with_gaps():
    no_temp = [(1000.0 + i, 10.0 + i, None) for i in range(50)]
    gap = [(1000.0 + i + (100 if i > 25 else 0), 10.0, 50.0 + i) for i in range(50)]
    _render("cpu", no_temp, hover=(300, 150))
    _render("cpu", gap, title="CPU")
    _render("keyboard", [(1000.0, 5, 0.0), (1001.0, 9, 240.0)])
    _render("net", [])
    _render("battery", [(1000.0, 80.0), (1001.0, 79.0)])
    _render("gpu", [(1000.0, 5.0)])


def test_x_axis_follows_time():
    xs = _x_positions([(0.0,), (1.0,), (10.0,)], 0, 100)
    assert xs == [0.0, 10.0, 100.0]
    assert nearest_index(xs, 6) == 1 and nearest_index(xs, 60) == 2 and nearest_index(xs, -5) == 0
