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

        self.set_default_size(620, 700)

        box = self.get_content_area()
        box.set_border_width(12)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add(root)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.get_style_context().add_class("linked")
        header.set_halign(Gtk.Align.FILL)
        title = Gtk.Label()
        title.set_markup(f"<b>{tr('settings_label')}</b>")
        title.set_xalign(0)
        link = Gtk.LinkButton(uri="https://github.com/OlegEgoism/SyMo", label="SyMo Ⓡ")
        header.pack_start(title, True, True, 0)
        header.pack_end(link, False, False, 0)
        root.pack_start(header, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.set_propagate_natural_width(True)
        root.pack_start(scroller, True, True, 0)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_start(4)
        content.set_margin_end(4)
        content.set_margin_bottom(4)
        scroller.add(content)

        def make_section(title_text: str) -> Gtk.Box:
            frame = Gtk.Frame()
            frame.set_shadow_type(Gtk.ShadowType.IN)
            section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            section_box.set_margin_top(8)
            section_box.set_margin_bottom(8)
            section_box.set_margin_start(10)
            section_box.set_margin_end(10)
            frame.add(section_box)
            label = Gtk.Label()
            label.set_markup(f"<b>{title_text}</b>")
            label.set_xalign(0)
            frame.set_label_widget(label)
            content.pack_start(frame, False, False, 0)
            return section_box

        visibility_section = make_section(tr('settings_label'))

        tray_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        visibility_section.pack_start(tray_row, False, False, 0)

        def add_check(container: Gtk.Box, label_key: str, key: str):
            chk = Gtk.CheckButton(label=tr(label_key))
            chk.set_active(self.visibility_settings.get(key, True))
            container.pack_start(chk, True, True, 0)
            return chk

        self.tray_cpu_check = add_check(tray_row, 'cpu_tray', 'tray_cpu')
        self.tray_ram_check = add_check(tray_row, 'ram_tray', 'tray_ram')

        info_grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        visibility_section.pack_start(info_grid, False, False, 0)

        def add_info_check(label_key: str, key: str, row: int, col: int):
            chk = Gtk.CheckButton(label=tr(label_key))
            chk.set_active(self.visibility_settings.get(key, True))
            info_grid.attach(chk, col, row, 1, 1)
            return chk

        self.cpu_check = add_info_check('cpu_info', 'cpu', 0, 0)
        self.ram_check = add_info_check('ram_loading', 'ram', 0, 1)
        self.swap_check = add_info_check('swap_loading', 'swap', 1, 0)
        self.disk_check = add_info_check('disk_loading', 'disk', 1, 1)
        self.net_check = add_info_check('lan_speed', 'net', 2, 0)
        self.uptime_check = add_info_check('uptime_label', 'uptime', 2, 1)
        self.keyboard_check = add_info_check('keyboard_clicks', 'keyboard_clicks', 3, 0)
        self.mouse_check = add_info_check('mouse_clicks', 'mouse_clicks', 3, 1)

        power_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        visibility_section.pack_start(power_row, False, False, 0)
        self.power_off_check = add_check(power_row, 'power_off', 'show_power_off')
        self.reboot_check = add_check(power_row, 'reboot', 'show_reboot')
        self.lock_check = add_check(power_row, 'lock', 'show_lock')
        self.timer_check = add_check(power_row, 'settings', 'show_timer')

        system_section = make_section(tr('system_status'))
        self.ping_check = Gtk.CheckButton(label=tr('ping_network'))
        self.ping_check.set_active(self.visibility_settings.get('ping_network', True))
        system_section.pack_start(self.ping_check, False, False, 0)

        logging_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.logging_check = Gtk.CheckButton(label=tr('enable_logging'))
        self.logging_check.set_active(self.visibility_settings.get('logging_enabled', True))
        logging_row.pack_start(self.logging_check, True, True, 0)

        self.download_button = Gtk.Button(label=tr('download_log'))
        self.download_button.connect("clicked", self.download_log_file)
        logging_row.pack_end(self.download_button, False, False, 0)
        system_section.pack_start(logging_row, False, False, 0)

        logsize_grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        logsize_label = Gtk.Label(label=tr('max_log_size_mb'))
        logsize_label.set_xalign(0)
        self.logsize_spin = Gtk.SpinButton.new_with_range(1, 1024, 1)
        self.logsize_spin.set_value(int(self.visibility_settings.get('max_log_mb', 5)))
        logsize_grid.attach(logsize_label, 0, 0, 1, 1)
        logsize_grid.attach(self.logsize_spin, 1, 0, 1, 1)
        system_section.pack_start(logsize_grid, False, False, 0)

        def build_secret_row(label_key: str, entry: Gtk.Entry, placeholder: str):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            label = Gtk.Label(label=tr(label_key))
            label.set_xalign(0)
            label.set_width_chars(20)
            entry.set_placeholder_text(placeholder)
            entry.set_visibility(False)
            toggle = Gtk.ToggleButton(label="👁")
            toggle.set_relief(Gtk.ReliefStyle.NONE)
            toggle.connect("toggled", lambda btn: entry.set_visibility(btn.get_active()))
            row.pack_start(label, False, False, 0)
            row.pack_start(entry, True, True, 0)
            row.pack_end(toggle, False, False, 0)
            return row

        telegram_section = make_section("Telegram")
        telegram_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.telegram_enable_check = Gtk.CheckButton(label=tr('telegram_notification'))
        telegram_header.pack_start(self.telegram_enable_check, True, True, 0)
        test_button = Gtk.Button(label=tr('check_telegram'))
        test_button.connect("clicked", self.test_telegram)
        telegram_header.pack_end(test_button, False, False, 0)
        telegram_section.pack_start(telegram_header, False, False, 0)

        self.token_entry = Gtk.Entry()
        telegram_section.pack_start(build_secret_row('token_bot', self.token_entry, "123...:ABC..."), False, False, 0)

        self.chat_id_entry = Gtk.Entry()
        telegram_section.pack_start(build_secret_row('id_chat', self.chat_id_entry, "123456789"), False, False, 0)

        interval_grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        interval_label = Gtk.Label(label=tr('time_send'))
        interval_label.set_xalign(0)
        self.interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1)
        self.interval_spin.set_value(3600)
        interval_grid.attach(interval_label, 0, 0, 1, 1)
        interval_grid.attach(self.interval_spin, 1, 0, 1, 1)
        telegram_section.pack_start(interval_grid, False, False, 0)

        discord_section = make_section("Discord")
        discord_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.discord_enable_check = Gtk.CheckButton(label=tr('discord_notification'))
        discord_header.pack_start(self.discord_enable_check, True, True, 0)
        discord_test_button = Gtk.Button(label=tr('check_discord'))
        discord_test_button.connect("clicked", self.test_discord)
        discord_header.pack_end(discord_test_button, False, False, 0)
        discord_section.pack_start(discord_header, False, False, 0)

        self.webhook_entry = Gtk.Entry()
        discord_section.pack_start(build_secret_row('webhook_url', self.webhook_entry, "https://discord.com/api/webhooks/..."), False, False, 0)

        discord_interval_grid = Gtk.Grid(column_spacing=8, row_spacing=4)
        discord_interval_label = Gtk.Label(label=tr('time_send'))
        discord_interval_label.set_xalign(0)
        self.discord_interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1)
        self.discord_interval_spin.set_value(3600)
        discord_interval_grid.attach(discord_interval_label, 0, 0, 1, 1)
        discord_interval_grid.attach(self.discord_interval_spin, 1, 0, 1, 1)
        discord_section.pack_start(discord_interval_grid, False, False, 0)

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
