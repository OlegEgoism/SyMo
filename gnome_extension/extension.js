import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const UUID = 'symo@olegegoism.github.io';
const APP_BINARY = 'SyMo';
const LOG_PATH = GLib.build_filenamev([GLib.get_home_dir(), '.symo_log.txt']);
const COMMAND_PATH = GLib.build_filenamev([GLib.get_home_dir(), '.symo_command.json']);

const POLL_SEC = 3;
const THRESHOLDS = {
    cpu: 90,
    ram: 90,
    disk: 95,
    temp: 85,
};

function readFileText(path) {
    try {
        const file = Gio.File.new_for_path(path);
        const [ok, contents] = file.load_contents(null);
        if (!ok)
            return '';
        return new TextDecoder().decode(contents);
    } catch (_error) {
        return '';
    }
}

function writeJson(path, payload) {
    try {
        const file = Gio.File.new_for_path(path);
        const text = JSON.stringify(payload);
        file.replace_contents(
            text,
            null,
            false,
            Gio.FileCreateFlags.REPLACE_DESTINATION,
            null
        );
        return true;
    } catch (error) {
        log(`[${UUID}] Failed to write command: ${error}`);
        return false;
    }
}

function parseLatestMetrics(logText) {
    const lines = (logText || '').trim().split('\n').filter(Boolean);
    const line = lines.length > 0 ? lines[lines.length - 1] : '';
    if (!line)
        return null;

    const cpuMatch = line.match(/CPU:\s*(\d+)%\s*(-?\d+)°C/i);
    const ramMatch = line.match(/RAM:\s*([\d.]+)\/([\d.]+)\s*GB/i);
    const diskMatch = line.match(/Disk:\s*([\d.]+)\/([\d.]+)\s*GB/i);
    if (!cpuMatch || !ramMatch || !diskMatch)
        return null;

    const cpuUsage = Number.parseFloat(cpuMatch[1]);
    const cpuTemp = Number.parseFloat(cpuMatch[2]);
    const ramUsed = Number.parseFloat(ramMatch[1]);
    const ramTotal = Math.max(0.0001, Number.parseFloat(ramMatch[2]));
    const diskUsed = Number.parseFloat(diskMatch[1]);
    const diskTotal = Math.max(0.0001, Number.parseFloat(diskMatch[2]));
    const ramPercent = (ramUsed / ramTotal) * 100;
    const diskPercent = (diskUsed / diskTotal) * 100;

    return {
        cpuUsage,
        cpuTemp,
        ramPercent,
        diskPercent,
        rawLine: line,
    };
}

class SyMoCompanionIndicator extends PanelMenu.Button {
    constructor() {
        super(0.0, 'SyMo Companion');

        this._pollSourceId = 0;
        this._notificationsPaused = false;

        this._content = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({
            icon_name: 'utilities-system-monitor-symbolic',
            style_class: 'system-status-icon',
        });
        this._label = new St.Label({
            text: 'CPU --% RAM --%',
            y_align: St.Align.MIDDLE,
            style: 'margin-left: 6px;',
        });

        this._content.add_child(this._icon);
        this._content.add_child(this._label);
        this.add_child(this._content);

        this._summaryItem = new PopupMenu.PopupMenuItem('No metrics yet');
        this._summaryItem.setSensitive(false);
        this.menu.addMenuItem(this._summaryItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._pauseItem = new PopupMenu.PopupMenuItem('Pause notifications');
        this._pauseItem.connect('activate', () => this._toggleNotificationsPause());
        this.menu.addMenuItem(this._pauseItem);

        const openGraphsMenu = new PopupMenu.PopupSubMenuMenuItem('Open graph');
        this._addGraphAction(openGraphsMenu.menu, 'CPU', 'cpu');
        this._addGraphAction(openGraphsMenu.menu, 'RAM', 'ram');
        this._addGraphAction(openGraphsMenu.menu, 'Swap', 'swap');
        this._addGraphAction(openGraphsMenu.menu, 'Disk', 'disk');
        this._addGraphAction(openGraphsMenu.menu, 'Network', 'net');
        this._addGraphAction(openGraphsMenu.menu, 'Keyboard', 'keyboard');
        this._addGraphAction(openGraphsMenu.menu, 'Mouse', 'mouse');
        this.menu.addMenuItem(openGraphsMenu);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._openItem = new PopupMenu.PopupMenuItem('Open SyMo');
        this._openItem.connect('activate', () => this._launchSyMo());
        this.menu.addMenuItem(this._openItem);

        this._aboutItem = new PopupMenu.PopupMenuItem('About companion');
        this._aboutItem.connect('activate', () => {
            Main.notify('SyMo', 'Companion mode is active: panel metrics + quick actions.');
        });
        this.menu.addMenuItem(this._aboutItem);

        this._refreshMetrics();
        this._pollSourceId = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT,
            POLL_SEC,
            () => this._refreshMetrics()
        );
    }

    _addGraphAction(menu, title, graphKey) {
        const item = new PopupMenu.PopupMenuItem(title);
        item.connect('activate', () => this._sendCommand({
            action: 'open_graph',
            graph: graphKey,
            requested_at: Date.now(),
        }));
        menu.addMenuItem(item);
    }

    _sendCommand(payload) {
        if (!writeJson(COMMAND_PATH, payload)) {
            Main.notify('SyMo', 'Unable to send command to SyMo companion.');
            return;
        }

        if (payload.action === 'open_graph')
            this._launchSyMo();
    }

    _toggleNotificationsPause() {
        this._notificationsPaused = !this._notificationsPaused;
        this._pauseItem.label.text = this._notificationsPaused
            ? 'Resume notifications'
            : 'Pause notifications';
        this._sendCommand({
            action: 'toggle_notifications_pause',
            requested_at: Date.now(),
        });
    }

    _refreshMetrics() {
        const metrics = parseLatestMetrics(readFileText(LOG_PATH));
        if (!metrics) {
            this._label.text = 'CPU --% RAM --%';
            this._summaryItem.label.text = 'No metrics yet (enable logging in SyMo).';
            this._icon.icon_name = 'utilities-system-monitor-symbolic';
            return GLib.SOURCE_CONTINUE;
        }

        this._label.text = `CPU ${metrics.cpuUsage.toFixed(0)}% RAM ${metrics.ramPercent.toFixed(0)}%`;
        this._summaryItem.label.text =
            `CPU ${metrics.cpuUsage.toFixed(0)}% (${metrics.cpuTemp.toFixed(0)}°C) · RAM ${metrics.ramPercent.toFixed(0)}% · Disk ${metrics.diskPercent.toFixed(0)}%`;

        const breached = (
            metrics.cpuUsage >= THRESHOLDS.cpu ||
            metrics.ramPercent >= THRESHOLDS.ram ||
            metrics.diskPercent >= THRESHOLDS.disk ||
            metrics.cpuTemp >= THRESHOLDS.temp
        );

        if (breached) {
            this._icon.icon_name = 'dialog-warning-symbolic';
            this._summaryItem.label.text = `⚠ ${this._summaryItem.label.text}`;
        } else {
            this._icon.icon_name = 'utilities-system-monitor-symbolic';
        }

        return GLib.SOURCE_CONTINUE;
    }

    _launchSyMo() {
        try {
            const appInfo = Gio.AppInfo.create_from_commandline(
                APP_BINARY,
                'SyMo',
                Gio.AppInfoCreateFlags.NONE
            );
            appInfo.launch([], null);
        } catch (error) {
            log(`[${UUID}] Failed to start SyMo: ${error}`);
            Main.notify('SyMo', 'Unable to start SyMo. Ensure SyMo is installed and available in PATH.');
        }
    }

    destroy() {
        if (this._pollSourceId) {
            GLib.Source.remove(this._pollSourceId);
            this._pollSourceId = 0;
        }
        super.destroy();
    }
}

export default class SyMoExtension {
    enable() {
        this._indicator = new SyMoCompanionIndicator();
        Main.panel.addToStatusArea(UUID, this._indicator);
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
