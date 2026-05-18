import ast
from pathlib import Path


def _load_decimate_samples():
    source = Path("app_core/app.py").read_text(encoding="utf-8")
    mod = ast.parse(source)
    fn_src = None
    for node in mod.body:
        if isinstance(node, ast.ClassDef) and node.name == "SystemTrayApp":
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == "_decimate_samples":
                    fn_src = ast.get_source_segment(source, sub)
                    break
    assert fn_src is not None
    namespace = {}
    exec(fn_src.replace("@staticmethod\n", ""), namespace)
    return namespace["_decimate_samples"]


def test_decimate_samples_returns_original_when_under_limit():
    fn = _load_decimate_samples()
    samples = [(i, float(i)) for i in range(10)]
    out = fn(samples, 20)
    assert out == samples


def test_decimate_samples_respects_single_point_limit():
    fn = _load_decimate_samples()
    samples = [(1, 10.0), (2, 20.0), (3, 30.0)]
    out = fn(samples, 1)
    assert out == [samples[-1]]


def test_decimate_samples_keeps_first_and_last_and_target_len():
    fn = _load_decimate_samples()
    samples = [(i, float(i)) for i in range(100)]
    out = fn(samples, 25)

    assert len(out) == 25
    assert out[0] == samples[0]
    assert out[-1] == samples[-1]


def test_decimate_samples_is_monotonic_over_ordered_input():
    fn = _load_decimate_samples()
    samples = [(i, float(i)) for i in range(200)]
    out = fn(samples, 40)

    xs = [point[0] for point in out]
    assert xs == sorted(xs)
