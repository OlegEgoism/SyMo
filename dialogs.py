from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from gi.repository import Gtk

from click_tracker import get_counts
from constants import LOG_FILE, TELEGRAM_CONFIG_FILE, DISCORD_CONFIG_FILE
from localization import tr
from notifications import TelegramNotifier, DiscordNotifier


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent: Optional[Gtk.Widget], visibility: Dict):
        super().__init__(title=tr('settings_label'),
                         transient_for=parent if (parent and parent.get_mapped()) else None,
                         flags=0)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL,
                         tr('apply_label'), Gtk.ResponseType.OK)
        self.visibility_settings = visibility

        box = self.get_content_area()
        box.set_border_width(10)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_halign(Gtk.Align.END)
        link = Gtk.LinkButton(uri="https://github.com/OlegEgoism/SyMo", label="SyMo Ⓡ")
        header.pack_start(link, False, False, 0)
        box.add(header)

        def add_check(label_key: str, key: str):
            chk = Gtk.CheckButton(label=tr(label_key))
            chk.set_active(self.visibility_settings.get(key, True))
            box.add(chk)
            return chk

        self.tray_cpu_check = add_check('cpu_tray', 'tray_cpu')
        self.tray_ram_check = add_check('ram_tray', 'tray_ram')
        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self.cpu_check = add_check('cpu_info', 'cpu')
        self.ram_check = add_check('ram_loading', 'ram')
        self.swap_check = add_check('swap_loading', 'swap')
        self.disk_check = add_check('disk_loading', 'disk')
        self.net_check = add_check('lan_speed', 'net')
        self.uptime_check = add_check('uptime_label', 'uptime')
        self.keyboard_check = add_check('keyboard_clicks', 'keyboard_clicks')
        self.mouse_check = add_check('mouse_clicks', 'mouse_clicks')

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.power_off_check = add_check('power_off', 'show_power_off')
        self.reboot_check = add_check('reboot', 'show_reboot')
        self.lock_check = add_check('lock', 'show_lock')
        self.timer_check = add_check('settings', 'show_timer')

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.ping_check = add_check('ping_network', 'ping_network')

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        logging_box = Gtk.Box(spacing=6)
        self.logging_check = Gtk.CheckButton(label=tr('enable_logging'))
        self.logging_check.set_active(self.visibility_settings.get('logging_enabled', True))
        self.logging_check.set_margin_bottom(3)
        logging_box.pack_start(self.logging_check, False, False, 0)

        self.download_button = Gtk.Button(label=tr('download_log'))
        self.download_button.connect("clicked", self.download_log_file)
        self.download_button.set_margin_bottom(3)
        logging_box.pack_end(self.download_button, False, False, 0)
        box.add(logging_box)

        logsize_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        logsize_label = Gtk.Label(label=tr('max_log_size_mb'))
        logsize_label.set_xalign(0)
        self.logsize_spin = Gtk.SpinButton.new_with_range(1, 1024, 1)
        self.logsize_spin.set_value(int(self.visibility_settings.get('max_log_mb', 5)))
        logsize_box.pack_start(logsize_label, False, False, 0)
        logsize_box.pack_start(self.logsize_spin, False, False, 0)
        box.add(logsize_box)

        box.add(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        telegram_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.telegram_enable_check = Gtk.CheckButton(label=tr('telegram_notification'))
        telegram_box.pack_start(self.telegram_enable_check, False, False, 0)
        test_button = Gtk.Button(label=tr('check_telegram'))
        test_button.set_halign(Gtk.Align.END)
        test_button.connect("clicked", self.test_telegram)
        telegram_box.pack_end(test_button, False, False, 0)
        box.add(telegram_box)

        token_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        token_label = Gtk.Label(label=tr('token_bot'))
        token_label.set_xalign(0)
        self.token_entry = Gtk.Entry()
        self.token_entry.set_placeholder_text("123...:ABC...")
        self.token_entry.set_visibility(False)
        token_box.pack_start(token_label, False, False, 0)
        token_box.pack_start(self.token_entry, True, True, 0)
        token_toggle = Gtk.ToggleButton(label="👁")
        token_toggle.set_relief(Gtk.ReliefStyle.NONE)
        token_toggle.connect("toggled", lambda btn: self.token_entry.set_visibility(btn.get_active()))
        token_box.pack_end(token_toggle, False, False, 0)
        box.add(token_box)

        chat_id_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chat_id_label = Gtk.Label(label=tr('id_chat'))
        chat_id_label.set_xalign(0)
        self.chat_id_entry = Gtk.Entry()
        self.chat_id_entry.set_placeholder_text("123456789")
        self.chat_id_entry.set_visibility(False)
        chat_id_box.pack_start(chat_id_label, False, False, 0)
        chat_id_box.pack_start(self.chat_id_entry, True, True, 0)
        chat_id_toggle = Gtk.ToggleButton(label="👁")
        chat_id_toggle.set_relief(Gtk.ReliefStyle.NONE)
        chat_id_toggle.connect("toggled", lambda btn: self.chat_id_entry.set_visibility(btn.get_active()))
        chat_id_box.pack_end(chat_id_toggle, False, False, 0)
        box.add(chat_id_box)

        interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        interval_label = Gtk.Label(label=tr('time_send'))
        interval_label.set_xalign(0)
        self.interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1)
        self.interval_spin.set_value(3600)
        interval_box.pack_start(interval_label, False, False, 0)
        interval_box.pack_start(self.interval_spin, True, True, 0)
        interval_box.set_margin_top(3)
        interval_box.set_margin_bottom(3)
        interval_box.set_margin_end(50)
        box.add(interval_box)

        discord_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.discord_enable_check = Gtk.CheckButton(label=tr('discord_notification'))
        discord_box.pack_start(self.discord_enable_check, False, False, 0)
        discord_test_button = Gtk.Button(label=tr('check_discord'))
        discord_test_button.set_halign(Gtk.Align.END)
        discord_test_button.connect("clicked", self.test_discord)
        discord_box.pack_end(discord_test_button, False, False, 0)
        box.add(discord_box)

        webhook_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        webhook_label = Gtk.Label(label=tr('webhook_url'))
        webhook_label.set_xalign(0)
        self.webhook_entry = Gtk.Entry()
        self.webhook_entry.set_placeholder_text("https://discord.com/api/webhooks/...")
        self.webhook_entry.set_visibility(False)
        webhook_box.pack_start(webhook_label, False, False, 0)
        webhook_box.pack_start(self.webhook_entry, True, True, 0)
        webhook_toggle = Gtk.ToggleButton(label="👁")
        webhook_toggle.set_relief(Gtk.ReliefStyle.NONE)
        webhook_toggle.connect("toggled", lambda btn: self.webhook_entry.set_visibility(btn.get_active()))
        webhook_box.pack_end(webhook_toggle, False, False, 0)
        box.add(webhook_box)

        discord_interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        discord_interval_label = Gtk.Label(label=tr('time_send'))
        discord_interval_label.set_xalign(0)
        self.discord_interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1)
        self.discord_interval_spin.set_value(3600)
        discord_interval_box.pack_start(discord_interval_label, False, False, 0)
        discord_interval_box.pack_start(self.discord_interval_spin, True, True, 0)
        discord_interval_box.set_margin_top(3)
        discord_interval_box.set_margin_bottom(30)
        discord_interval_box.set_margin_end(50)
        box.add(discord_interval_box)

        self._prefill_configs()
        self.show_all()

    def _prefill_configs(self):
        try:
            if TELEGRAM_CONFIG_FILE.exists():
                config = json.loads(TELEGRAM_CONFIG_FILE.read_text(encoding="utf-8"))
                self.token_entry.set_text(config.get('TELEGRAM_BOT_TOKEN', '') or '')
                self.chat_id_entry.set_text(str(config.get('TELEGRAM_CHAT_ID', '') or ''))
                self.telegram_enable_check.set_active(bool(config.get('enabled', False)))
                self.interval_spin.set_value(int(config.get('notification_interval', 3600)))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Telegram: {e}")

        try:
            if DISCORD_CONFIG_FILE.exists():
                config = json.loads(DISCORD_CONFIG_FILE.read_text(encoding="utf-8"))
                self.webhook_entry.set_text(config.get('DISCORD_WEBHOOK_URL', '') or '')
                self.discord_enable_check.set_active(bool(config.get('enabled', False)))
                self.discord_interval_spin.set_value(int(config.get('notification_interval', 3600)))
        except Exception as e:
            print(f"Ошибка загрузки конфигурации Discord: {e}")

    def _message(self, title: str, message: str):
        d = Gtk.MessageDialog(transient_for=self, flags=0,
                              message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK,
                              text=message)
        d.set_title(title)
        d.run()
        d.destroy()

    def test_telegram(self, _w):
        token = self.token_entry.get_text().strip()
        chat_id = self.chat_id_entry.get_text().strip()
        enabled = self.telegram_enable_check.get_active()
        interval = int(self.interval_spin.get_value())
        if not token or not chat_id:
            self._message(tr('error'), tr('bot_message'))
            return
        notifier = TelegramNotifier()
        if notifier.save_config(token, chat_id, enabled, interval):
            ok = notifier.send_message(tr('test_message'))
            self._message(tr('ok') if ok else tr('error'),
                          tr('test_message_ok') if ok else tr('test_message_error'))
        else:
            self._message(tr('error'), tr('setting_telegram_error'))

    def test_discord(self, _w):
        webhook_url = self.webhook_entry.get_text().strip()
        enabled = self.discord_enable_check.get_active()
        interval = int(self.discord_interval_spin.get_value())
        if not webhook_url:
            self._message(tr('error'), tr('webhook_required'))
            return
        notifier = DiscordNotifier()
        if notifier.save_config(webhook_url, enabled, interval):
            ok = notifier.send_message(tr('test_message'))
            self._message(tr('ok') if ok else tr('error'),
                          tr('test_message_ok') if ok else tr('test_message_error'))
        else:
            self._message(tr('error'), tr('setting_discord_error'))

    def download_log_file(self, _w):
        dialog = Gtk.FileChooserDialog(
            title=tr('download_log'),
            parent=self if (self.get_mapped()) else None,
            action=Gtk.FileChooserAction.SAVE
        )
        dialog.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL,
                           tr('apply_label'), Gtk.ResponseType.OK)
        dialog.set_current_name("info_log.txt")
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            dest = Path(dialog.get_filename())
            try:
                if not LOG_FILE.exists():
                    raise FileNotFoundError(LOG_FILE)
                dest.write_text(LOG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as e:
                print("Ошибка сохранения лога:", e)
        dialog.destroy()

    def refresh_clicks(self) -> None:
        kbd, ms = get_counts()
        self.keyboard_check.set_label(f"{tr('keyboard_clicks')}: {kbd}")
        self.mouse_check.set_label(f"{tr('mouse_clicks')}: {ms}")
