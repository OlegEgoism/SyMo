from pathlib import Path


def test_telegram_graph_commands_are_supported():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")
    assert "command = raw_command.split('@', 1)[0]" in code
    assert "elif command == '/graph':" not in code
    assert "elif command in {'/disk', '/top', '/cpu', '/ram', '/swap', '/net', '/keyboard', '/mouse', '/temp', '/temperature'}:" not in code
    assert "'/cpu_graph'" in code
    assert "'/temp_graph'" in code
    assert "'/ram_graph'" in code
    assert "'/net_graph'" in code
    assert "'/disk_graph'" in code
    assert "'/swap_graph'" in code
    assert "'/keyboard_graph'" in code
    assert "'/mouse_graph'" in code
    assert "tr('graph_commands_title')" in code
    assert "/graph [metric]" not in code
    assert "tr('graph_unavailable')" in code
    assert "tr('graph_send_failed')" in code
    assert "tr('unknown_command')" in code
    assert "tr('unknown_command_help')" in code


def test_telegram_notifier_has_graph_render_pipeline():
    code = Path("notifications/telegram.py").read_text(encoding="utf-8")
    assert "def _metric_samples_for_graph(self, metric: str)" in code
    assert "def _render_metric_graph_to_temp(self, metric: str)" in code
    assert "def _format_graph_time(timestamp: float) -> str:" in code
    assert "import cairo" in code
    assert "def _send_metric_graph(self, metric: str) -> None:" in code
    assert '"temperature": (f"{tr(\'cpu\')} {tr(\'temperature\')}"' in code
    assert 'time.strftime("%H:%M:%S", time.localtime(float(timestamp)))' in code
    assert "time_start_label = self._format_graph_time(points[0][0])" in code
    assert "time_end_label = self._format_graph_time(points[-1][0])" in code
    assert '"uptime"' not in code.split("mapping = {", 1)[1].split("}", 1)[0]
