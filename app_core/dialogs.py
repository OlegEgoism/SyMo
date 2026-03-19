from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from gi.repository import Gtk

from .click_tracker import get_counts
from .constants import (
    LOG_FILE,
    TELEGRAM_CONFIG_FILE,
    DISCORD_CONFIG_FILE,
    MENU_ORDER_DEFAULT,
    GRAPH_HISTORY_MINUTES_DEFAULT,
    GRAPH_HISTORY_MINUTES_MIN,
    GRAPH_HISTORY_MINUTES_MAX,
)
from .localization import tr
from notifications import TelegramNotifier, DiscordNotifier

MENU_ORDER_ENABLED_COLUMN = 0
MENU_ORDER_LABEL_COLUMN = 1
MENU_ORDER_KEY_COLUMN = 2


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent: Optional[Gtk.Widget], visibility: Dict):
        super().__init__(title=tr('settings_label'),
                         transient_for=parent if (parent and parent.get_mapped()) else None,
                         flags=0)
        self.set_modal(True)
        self.set_destroy_with_parent(True)
        self.set_default_size(500, 520)
        self.add_buttons(tr('cancel_label'), Gtk.ResponseType.CANCEL,
                         tr('apply_label'), Gtk.ResponseType.OK)
        self.visibility_settings = visibility

        box = self.get_content_area()
        box.set_border_width(12)

        notebook = Gtk.Notebook()
        notebook.set_border_width(4)
        box.add(notebook)

        general_scroller = Gtk.ScrolledWindow()
        general_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        general_scroller.set_shadow_type(Gtk.ShadowType.NONE)
        general_scroller.set_min_content_height(520)
        general_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        general_content.set_border_width(10)
        general_scroller.add(general_content)
        notebook.append_page(general_scroller, Gtk.Label(label=tr('display_tab')))

        notification_scroller = Gtk.ScrolledWindow()
        notification_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        notification_scroller.set_shadow_type(Gtk.ShadowType.NONE)
        notification_scroller.set_min_content_height(520)
        notification_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notification_content.set_border_width(10)
        notification_scroller.add(notification_content)
        notebook.append_page(notification_scroller, Gtk.Label(label=tr('notification_section')))

        logging_scroller = Gtk.ScrolledWindow()
        logging_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        logging_scroller.set_shadow_type(Gtk.ShadowType.NONE)
        logging_scroller.set_min_content_height(520)
        logging_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        logging_content.set_border_width(10)
        logging_scroller.add(logging_content)
        notebook.append_page(logging_scroller, Gtk.Label(label=tr('logging_tab')))

        license_scroller = Gtk.ScrolledWindow()
        license_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        license_scroller.set_shadow_type(Gtk.ShadowType.NONE)
        license_scroller.set_min_content_height(520)
        license_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        license_content.set_border_width(10)
        license_scroller.add(license_content)
        notebook.append_page(license_scroller, Gtk.Label(label=tr('license_tab')))

        # def add_section_title(label_key: str):
        #     title = Gtk.Label()
        #     title.set_markup(f"<b>{tr(label_key)}</b>")
        #     title.set_xalign(0)
        #     title.set_margin_top(4)
        #     title.set_margin_bottom(2)
        #     general_content.add(title)

        def add_check(label_key: str, key: str):
            chk = Gtk.CheckButton(label=tr(label_key))
            chk.set_active(self.visibility_settings.get(key, True))
            chk.set_margin_top(2)
            chk.set_margin_bottom(2)
            general_content.add(chk)
            return chk

        # add_section_title('display_section')
        self.tray_cpu_check = add_check('cpu_tray', 'tray_cpu')
        self.tray_ram_check = add_check('ram_tray', 'tray_ram')
        display_separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        display_separator.set_margin_top(2)
        display_separator.set_margin_bottom(2)
        general_content.add(display_separator)

        reorder_title = Gtk.Label(label=tr('menu_order_title'))
        reorder_title.set_xalign(0)
        reorder_title.set_margin_top(4)
        reorder_title.set_margin_bottom(2)
        general_content.add(reorder_title)

        self.menu_order_store = Gtk.ListStore(bool, str, str)

        order_labels = [
            ('cpu_info', 'cpu'),
            ('ram_loading', 'ram'),
            ('swap_loading', 'swap'),
            ('disk_loading', 'disk'),
            ('lan_speed', 'net'),
            ('keyboard_clicks', 'keyboard_clicks'),
            ('mouse_clicks', 'mouse_clicks'),
            ('uptime_label', 'uptime'),
            ('power_off', 'show_power_off'),
            ('reboot', 'show_reboot'),
            ('lock', 'show_lock'),
            ('settings', 'show_timer'),
            ('ping_network', 'ping_network'),
            ('system_info', 'show_system_info'),
        ]

        display_map = {key: label_key for label_key, key in order_labels}
        current_order = self._normalize_menu_order(self.visibility_settings.get('menu_order'))
        for key in current_order:
            label_key = display_map.get(key, key)
            self.menu_order_store.append([bool(self.visibility_settings.get(key, True)), tr(label_key), key])

        self.menu_order_view = Gtk.TreeView(model=self.menu_order_store)
        self.menu_order_view.set_headers_visible(False)
        self.menu_order_view.set_reorderable(True)
        self.menu_order_selection = self.menu_order_view.get_selection()

        toggle_renderer = Gtk.CellRendererToggle()
        toggle_renderer.set_activatable(True)
        toggle_renderer.connect('toggled', self._on_menu_item_toggled)
        toggle_column = Gtk.TreeViewColumn('', toggle_renderer, active=MENU_ORDER_ENABLED_COLUMN)
        self.menu_order_view.append_column(toggle_column)

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn('', renderer, text=MENU_ORDER_LABEL_COLUMN)
        self.menu_order_view.append_column(column)

        order_scroll = Gtk.ScrolledWindow()
        order_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        order_scroll.set_min_content_height(330)
        order_scroll.set_shadow_type(Gtk.ShadowType.IN)
        order_scroll.set_margin_bottom(6)
        order_scroll.add(self.menu_order_view)
        general_content.add(order_scroll)

        # license_title = Gtk.Label()
        # license_title.set_markup(f"<b>{tr('license_tab')}</b>")
        # license_title.set_xalign(0)
        # license_content.add(license_title)

        license_link_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        license_link_box.set_halign(Gtk.Align.START)
        link = Gtk.LinkButton(uri="https://github.com/OlegEgoism/SyMo", label="SyMo Ⓡ")
        license_link_box.pack_start(link, False, False, 0)
        license_content.add(license_link_box)

        license_info = Gtk.Label(label=tr('license_info'))
        license_info.set_xalign(0)
        license_info.set_line_wrap(True)
        license_info.set_selectable(True)
        license_content.add(license_info)

        # logging_title = Gtk.Label()
        # logging_title.set_markup(f"<b>{tr('logging_section')}</b>")
        # logging_title.set_xalign(0)
        # logging_title.set_margin_top(2)
        # logging_title.set_margin_bottom(1)
        # logging_content.add(logging_title)

        logging_box = Gtk.Box(spacing=6)
        logging_box.set_margin_bottom(2)
        self.logging_check = Gtk.CheckButton(label=tr('enable_logging'))
        self.logging_check.set_active(self.visibility_settings.get('logging_enabled', True))
        self.logging_check.set_margin_bottom(2)
        logging_box.pack_start(self.logging_check, False, False, 0)

        self.download_button = Gtk.Button(label=tr('download_log'))
        self.download_button.connect("clicked", self.download_log_file)
        self.download_button.set_margin_bottom(2)
        logging_box.pack_end(self.download_button, False, False, 0)
        logging_content.add(logging_box)

        logsize_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        logsize_label = Gtk.Label(label=tr('max_log_size_mb'))
        logsize_label.set_xalign(0)
        logsize_label.set_width_chars(28)
        self.logsize_spin = Gtk.SpinButton.new_with_range(1, 1024, 1)
        self.logsize_spin.set_value(int(self.visibility_settings.get('max_log_mb', 5)))
        self.logsize_spin.set_width_chars(8)
        logsize_box.pack_start(logsize_label, False, False, 0)
        logsize_box.pack_start(self.logsize_spin, False, False, 0)
        logging_content.add(logsize_box)

        graph_history_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        graph_history_label = Gtk.Label(label=tr('graph_history_minutes'))
        graph_history_label.set_xalign(0)
        graph_history_label.set_width_chars(28)
        self.graph_history_spin = Gtk.SpinButton.new_with_range(
            GRAPH_HISTORY_MINUTES_MIN,
            GRAPH_HISTORY_MINUTES_MAX,
            1,
        )
        self.graph_history_spin.set_value(
            int(self.visibility_settings.get('graph_history_minutes', GRAPH_HISTORY_MINUTES_DEFAULT))
        )
        self.graph_history_spin.set_width_chars(8)
        graph_history_box.pack_start(graph_history_label, False, False, 0)
        graph_history_box.pack_start(self.graph_history_spin, False, False, 0)
        logging_content.add(graph_history_box)

        # notification_title = Gtk.Label()
        # notification_title.set_markup(f"<b>{tr('notification_section')}</b>")
        # notification_title.set_xalign(0)
        # notification_title.set_margin_top(2)
        # notification_title.set_margin_bottom(1)
        # notification_content.add(notification_title)

        telegram_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        telegram_box.set_margin_bottom(2)
        self.telegram_enable_check = Gtk.CheckButton(label=tr('telegram_notification'))
        telegram_box.pack_start(self.telegram_enable_check, False, False, 0)
        test_button = Gtk.Button(label=tr('check_telegram'))
        test_button.set_halign(Gtk.Align.END)
        test_button.connect("clicked", self.test_telegram)
        telegram_box.pack_end(test_button, False, False, 0)
        notification_content.add(telegram_box)

        token_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        token_label = Gtk.Label(label=tr('token_bot'))
        token_label.set_xalign(0)
        token_label.set_width_chars(20)
        self.token_entry = Gtk.Entry()
        self.token_entry.set_placeholder_text("123...:ABC...")
        self.token_entry.set_visibility(False)
        self.token_entry.set_hexpand(True)
        token_box.pack_start(token_label, False, False, 0)
        token_box.pack_start(self.token_entry, True, True, 0)
        token_toggle = Gtk.ToggleButton(label="👁")
        token_toggle.set_relief(Gtk.ReliefStyle.NONE)
        token_toggle.connect("toggled", lambda btn: self.token_entry.set_visibility(btn.get_active()))
        token_box.pack_end(token_toggle, False, False, 0)
        token_box.set_margin_bottom(2)
        notification_content.add(token_box)

        chat_id_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chat_id_label = Gtk.Label(label=tr('id_chat'))
        chat_id_label.set_xalign(0)
        chat_id_label.set_width_chars(20)
        self.chat_id_entry = Gtk.Entry()
        self.chat_id_entry.set_placeholder_text("123456789")
        self.chat_id_entry.set_visibility(False)
        self.chat_id_entry.set_hexpand(True)
        chat_id_box.pack_start(chat_id_label, False, False, 0)
        chat_id_box.pack_start(self.chat_id_entry, True, True, 0)
        chat_id_toggle = Gtk.ToggleButton(label="👁")
        chat_id_toggle.set_relief(Gtk.ReliefStyle.NONE)
        chat_id_toggle.connect("toggled", lambda btn: self.chat_id_entry.set_visibility(btn.get_active()))
        chat_id_box.pack_end(chat_id_toggle, False, False, 0)
        chat_id_box.set_margin_bottom(2)
        notification_content.add(chat_id_box)

        interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        interval_label = Gtk.Label(label=tr('time_send'))
        interval_label.set_xalign(0)
        interval_label.set_width_chars(20)
        self.interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1)
        self.interval_spin.set_value(3600)
        self.interval_spin.set_width_chars(8)
        interval_box.pack_start(interval_label, False, False, 0)
        interval_box.pack_start(self.interval_spin, False, False, 0)
        interval_box.set_margin_top(1)
        interval_box.set_margin_bottom(6)
        notification_content.add(interval_box)

        discord_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        discord_box.set_margin_bottom(2)
        self.discord_enable_check = Gtk.CheckButton(label=tr('discord_notification'))
        discord_box.pack_start(self.discord_enable_check, False, False, 0)
        discord_test_button = Gtk.Button(label=tr('check_discord'))
        discord_test_button.set_halign(Gtk.Align.END)
        discord_test_button.connect("clicked", self.test_discord)
        discord_box.pack_end(discord_test_button, False, False, 0)
        notification_content.add(discord_box)

        webhook_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        webhook_label = Gtk.Label(label=tr('webhook_url'))
        webhook_label.set_xalign(0)
        webhook_label.set_width_chars(20)
        self.webhook_entry = Gtk.Entry()
        self.webhook_entry.set_placeholder_text("https://discord.com/api/webhooks/...")
        self.webhook_entry.set_visibility(False)
        self.webhook_entry.set_hexpand(True)
        webhook_box.pack_start(webhook_label, False, False, 0)
        webhook_box.pack_start(self.webhook_entry, True, True, 0)
        webhook_toggle = Gtk.ToggleButton(label="👁")
        webhook_toggle.set_relief(Gtk.ReliefStyle.NONE)
        webhook_toggle.connect("toggled", lambda btn: self.webhook_entry.set_visibility(btn.get_active()))
        webhook_box.pack_end(webhook_toggle, False, False, 0)
        webhook_box.set_margin_bottom(2)
        notification_content.add(webhook_box)

        discord_interval_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        discord_interval_label = Gtk.Label(label=tr('time_send'))
        discord_interval_label.set_xalign(0)
        discord_interval_label.set_width_chars(20)
        self.discord_interval_spin = Gtk.SpinButton.new_with_range(10, 86400, 1)
        self.discord_interval_spin.set_value(3600)
        self.discord_interval_spin.set_width_chars(8)
        discord_interval_box.pack_start(discord_interval_label, False, False, 0)
        discord_interval_box.pack_start(self.discord_interval_spin, False, False, 0)
        discord_interval_box.set_margin_top(1)
        discord_interval_box.set_margin_bottom(8)
        notification_content.add(discord_interval_box)

        self._prefill_configs()
        self.show_all()

    def _normalize_menu_order(self, order) -> list[str]:
        unique = []
        for key in order or []:
            if key in MENU_ORDER_DEFAULT and key not in unique:
                unique.append(key)
        for key in MENU_ORDER_DEFAULT:
            if key not in unique:
                unique.append(key)
        return unique

    def _on_menu_item_toggled(self, _renderer, path: str):
        tree_iter = self.menu_order_store.get_iter(path)
        current = bool(self.menu_order_store.get_value(tree_iter, MENU_ORDER_ENABLED_COLUMN))
        self.menu_order_store.set_value(tree_iter, MENU_ORDER_ENABLED_COLUMN, not current)

    def get_menu_order(self) -> list[str]:
        keys = []
        for row in self.menu_order_store:
            keys.append(row[MENU_ORDER_KEY_COLUMN])
        return self._normalize_menu_order(keys)

    def get_menu_visibility(self) -> Dict[str, bool]:
        values: Dict[str, bool] = {}
        for row in self.menu_order_store:
            values[row[MENU_ORDER_KEY_COLUMN]] = bool(row[MENU_ORDER_ENABLED_COLUMN])
        return values

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
            ok = notifier.send_message(tr('test_message'), force=True)
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
            ok = notifier.send_message(tr('test_message'), force=True)
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
