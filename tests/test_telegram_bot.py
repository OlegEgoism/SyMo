import json
import time
import types

import pytest

from app_core.localization import tr
from app_core.power_control import Action
from notifications import telegram as tg


def test_helpers():
    assert tg.is_valid_chat_id("123") and tg.is_valid_chat_id("-1001234567890") and tg.is_valid_chat_id("@my_channel")
    assert not tg.is_valid_chat_id("@ab") and not tg.is_valid_chat_id("１２３") and not tg.is_valid_chat_id("")
    assert tg.parse_user_ids("1, 2;3  4,1") == [1, 2, 3, 4] and tg.parse_user_ids("") == []
    assert tg.parse_user_ids("1, @x") is None and tg.parse_user_ids("123²") is None
    assert tg._parse_delay_minutes([]) == 1 and tg._parse_delay_minutes(["10"]) == 10
    assert tg._parse_delay_minutes(["0"]) is None and tg._parse_delay_minutes(["1441"]) is None


class FakePower:
    def __init__(self):
        self.calls = []
        self.scheduled = None

    def schedule(self, act, minutes, notify_remote=None):
        self.calls.append(("schedule", act, minutes))
        self.scheduled = act

    def cancel_schedule(self):
        act, self.scheduled = self.scheduled, None
        self.calls.append(("cancel", act))
        return act

    def run_action(self, act, notify_remote=None):
        self.calls.append(("run", act))


@pytest.fixture
def bot(monkeypatch):
    notifier = tg.TelegramNotifier(autoload=False)
    notifier.configure("T", "100", True, 60)
    notifier.sent = []
    notifier.slow = []
    notifier.send_message_async = notifier.sent.append
    notifier.set_power_control(FakePower())
    idle = []
    monkeypatch.setattr(tg.GLib, "idle_add", lambda fn, *a: idle.append((fn, a)) or 1)
    notifier.run_state = tg._BotRun(time.time() - 1000, lambda text, html_markup=False: notifier.sent.append(text),
                                    lambda job: notifier.slow.append(job) or True)
    notifier.run_state.bot_username = "symo_bot"

    def send(text, chat_type="private", from_id=100, age=0, extra=None):
        notifier.sent.clear()
        notifier.slow.clear()
        notifier.run_state.last_denial.clear()
        message = {"date": time.time() - age, "text": text, "chat": {"id": 100, "type": chat_type},
                   "from": {"id": from_id}}
        message.update(extra or {})
        notifier._process_update({"update_id": 1, "message": message}, notifier.run_state)
        while idle:
            fn, args = idle.pop(0)
            fn(*args)
        return notifier.sent

    notifier.send = send
    return notifier


def test_power_needs_opt_in_and_goes_through_the_timer(bot):
    assert bot.send("/poweroff") == [tr("bot_command_disabled")]
    bot.allow_remote_power = True
    assert "/cancel" in bot.send("/poweroff")[0]
    assert bot.power_control_ref.calls[-1] == ("schedule", Action.POWER_OFF, 1)
    bot.send("/reboot@SyMo_Bot 15")
    assert bot.power_control_ref.calls[-1] == ("schedule", Action.REBOOT, 15)
    bot.send("/cancel")
    assert bot.power_control_ref.calls[-1] == ("cancel", Action.REBOOT)
    assert bot.send("/cancel")[-1] == tr("bot_nothing_to_cancel")


def test_group_members_need_to_be_allowed(bot):
    bot.allow_remote_power = True
    calls = bot.power_control_ref.calls
    assert "555" in bot.send("/poweroff", chat_type="supergroup", from_id=555)[0] and calls == []
    bot.send("/cpu_graph", chat_type="group", from_id=555)
    assert len(bot.slow) == 1                                   # чтение доступно всем
    bot.allowed_user_ids = [555]
    bot.send("/lock", chat_type="group", from_id=555)
    assert calls[-1] == ("run", Action.LOCK)


def test_untrusted_and_stale_messages(bot):
    bot.allow_remote_power = True
    bot.allowed_user_ids = [555]
    assert bot.send("/lock", chat_type="group", from_id=555, extra={"sender_chat": {"id": -1}}) == []
    assert bot.send("/poweroff", chat_type="supergroup", from_id=1087968824) == []
    assert bot.send("/poweroff", age=600) == [tr("bot_command_stale")]
    assert bot.power_control_ref.calls == []
    assert bot.send("hello") == [] and bot.send("/status@other_bot") == []
    assert bot.send("/whatever", chat_type="group", from_id=555) == []
    assert bot.send("/whatever")                                 # в личном чате — подсказка


def test_config_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "tg.json"
    monkeypatch.setattr(tg, "TELEGRAM_CONFIG_FILE", path)
    notifier = tg.TelegramNotifier(autoload=False)
    assert notifier.save_config("T", "-100", True, 60, allowed_user_ids=[5, 6], allow_remote_power=True)
    data = json.loads(path.read_text())
    assert data["allowed_user_ids"] == [5, 6] and data["allow_remote_power"] and not data["allow_remote_screenshot"]
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_text(json.dumps({"TELEGRAM_BOT_TOKEN": "T", "TELEGRAM_CHAT_ID": "1", "enabled": True}))
    old = tg.TelegramNotifier()
    assert old.allowed_user_ids == [] and not old.allow_remote_power


def test_response_errors_and_retry_after():
    r = types.SimpleNamespace
    assert tg.TelegramNotifier._extract_retry_after(r(json=lambda: {"parameters": {"retry_after": 7}})) == 7
    assert tg.TelegramNotifier._extract_retry_after(r(json=lambda: {"parameters": {"retry_after": 999}})) == 30
    ok = r(status_code=200, json=lambda: {"ok": True})
    bad = r(status_code=400, json=lambda: {"ok": False, "description": "Bad Request: chat not found"})
    assert tg.TelegramNotifier._response_error(ok) is None
    assert tg.TelegramNotifier._response_error(bad) == "HTTP 400: Bad Request: chat not found"
    text, mode = tg.TelegramNotifier._prepare_text("a < b & c", False)
    assert mode is None and text == "a < b & c"
