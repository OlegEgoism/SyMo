from pathlib import Path


def test_telegram_graph_commands_are_supported():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")
    assert "elif text.startswith('/graph'):" in code
    assert "elif text in {'/uptime', '/disk', '/top'}:" in code
    assert "self._send_metric_graph(metric)" in code


def test_telegram_notifier_has_graph_render_pipeline():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")
    assert "def _metric_samples_for_graph(self, metric: str)" in code
    assert "def _render_metric_graph_to_temp(self, metric: str)" in code
    assert "import cairo" in code
    assert "def _send_metric_graph(self, metric: str) -> None:" in code
