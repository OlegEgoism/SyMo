from pathlib import Path


def test_telegram_graph_commands_are_supported():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")
    assert "command = raw_command.split('@', 1)[0]" in code
    assert "elif command == '/graph':" in code
    assert "elif command in {'/uptime', '/disk', '/top', '/cpu', '/ram', '/swap', '/net', '/keyboard', '/mouse'}:" in code
    assert "Unknown command. Use /help" in code
    assert "/graph [metric] - graph image" in code


def test_telegram_notifier_has_graph_render_pipeline():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")
    assert "def _metric_samples_for_graph(self, metric: str)" in code
    assert "def _render_metric_graph_to_temp(self, metric: str)" in code
    assert "import cairo" in code
    assert "def _send_metric_graph(self, metric: str) -> None:" in code
