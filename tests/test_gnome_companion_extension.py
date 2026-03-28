from pathlib import Path


def test_extension_exposes_companion_actions():
    code = Path("gnome_extension/extension.js").read_text(encoding="utf-8")
    assert "Pause notifications" in code
    assert "action: 'open_graph'" in code
    assert "toggle_notifications_pause" in code
    assert "dialog-warning-symbolic" in code


def test_app_consumes_external_commands():
    code = Path("app_core/app.py").read_text(encoding="utf-8")
    assert "def _consume_external_command" in code
    assert "COMMAND_FILE" in code
    assert "toggle_notifications_pause" in code
    assert "open_graph" in code
