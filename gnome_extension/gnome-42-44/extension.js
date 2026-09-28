// SPDX-License-Identifier: GPL-2.0-or-later
// SyMo Launcher for GNOME Shell 42-44 (legacy imports).

const {Clutter, GLib, GObject, Gio, Shell, St} = imports.gi;

const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ExtensionUtils = imports.misc.extensionUtils;

const DESKTOP_ID = 'SyMo.desktop';
const COMMANDS = ['symo', 'SyMo'];
// SyMo owns this name on the session bus while it runs; it then shows its own
// tray icon, so this indicator hides to avoid a second icon.
const BUS_NAME = 'io.github.olegegoism.SyMo';
const UPDATE_INTERVAL_SEC = 2;

// Same short labels as the SyMo tray icon; other languages use the English ones.
const LABELS = {
    ru: {cpu: 'ЦПУ', ram: 'ОЗУ', gb: 'ГБ'},
    cn: {cpu: '处理器', ram: '内存', gb: 'GB'},
    fr: {cpu: 'CPU', ram: 'RAM', gb: 'Go'},
    en: {cpu: 'CPU', ram: 'RAM', gb: 'GB'},
};

function panelLabels() {
    for (const name of GLib.get_language_names()) {
        const code = name.split(/[_.@]/)[0].toLowerCase();
        const key = code === 'zh' ? 'cn' : code;
        if (LABELS[key])
            return LABELS[key];
    }
    return LABELS.en;
}

Gio._promisify(Gio.File.prototype, 'load_contents_async');

async function readText(path) {
    const [bytes] = await Gio.File.new_for_path(path).load_contents_async(null);
    return new TextDecoder().decode(bytes);
}

// Busy and total jiffies from the aggregate "cpu" line of /proc/stat.
async function readCpuTimes() {
    const fields = (await readText('/proc/stat')).split('\n')[0].trim().split(/\s+/).slice(1).map(Number);
    const idle = fields[3] + (fields[4] || 0);
    const total = fields.reduce((sum, value) => sum + value, 0);
    return {busy: total - idle, total};
}

async function readUsedMemoryGb() {
    const info = {};
    for (const line of (await readText('/proc/meminfo')).split('\n')) {
        const [key, value] = line.split(':');
        if (value)
            info[key] = parseInt(value, 10);
    }
    return (info.MemTotal - info.MemAvailable) / (1024 * 1024);
}

function findCommand() {
    for (const command of COMMANDS) {
        const path = GLib.find_program_in_path(command);
        if (path)
            return path;
    }
    // ~/.local/bin is often missing from the GNOME Shell session PATH.
    const localBin = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'symo']);
    return GLib.file_test(localBin, GLib.FileTest.IS_EXECUTABLE) ? localBin : null;
}

function launchSyMo(name) {
    try {
        const app = Shell.AppSystem.get_default().lookup_app(DESKTOP_ID);
        if (app) {
            app.activate();
            return;
        }
        const command = findCommand();
        if (command) {
            Gio.AppInfo.create_from_commandline(command, 'SyMo', Gio.AppInfoCreateFlags.NONE)
                .launch([], global.create_app_launch_context(0, -1));
            return;
        }
    } catch (error) {
        console.error(`${name}: failed to start SyMo: ${error}`);
    }
    Main.notify(name, 'The SyMo app adds graphs, power actions and notifications. Download it from https://github.com/OlegEgoism/SyMo');
}

const SyMoIndicator = GObject.registerClass(
class SyMoIndicator extends PanelMenu.Button {
    _init(extension) {
        super._init(0.0, extension.metadata.name);
        this._labels = panelLabels();
        this._prevCpu = null;
        this._timerId = 0;
        this._updating = false;
        this._destroyed = false;

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        box.add_child(new St.Icon({
            gicon: Gio.icon_new_for_string(GLib.build_filenamev([extension.path, 'symo.png'])),
            style_class: 'system-status-icon',
        }));
        this._label = new St.Label({text: '…', y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._label);
        this.add_child(box);

        const openItem = new PopupMenu.PopupMenuItem('Open SyMo');
        openItem.connect('activate', () => launchSyMo(extension.metadata.name));
        this.menu.addMenuItem(openItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const pageItem = new PopupMenu.PopupMenuItem('Project page');
        pageItem.connect('activate', () => {
            try {
                Gio.AppInfo.launch_default_for_uri(extension.metadata.url, global.create_app_launch_context(0, -1));
            } catch (error) {
                console.error(`${extension.metadata.name}: failed to open ${extension.metadata.url}: ${error}`);
            }
        });
        this.menu.addMenuItem(pageItem);
    }

    startUpdates() {
        if (this._timerId)
            return;
        this._prevCpu = null;
        this._update();
        this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, UPDATE_INTERVAL_SEC, () => {
            this._update();
            return GLib.SOURCE_CONTINUE;
        });
    }

    stopUpdates() {
        if (this._timerId) {
            GLib.source_remove(this._timerId);
            this._timerId = 0;
        }
    }

    async _update() {
        if (this._updating)
            return;
        this._updating = true;
        try {
            // CPU load is a difference of two samples, so the first update has none yet.
            const cpu = await readCpuTimes();
            const ramGb = await readUsedMemoryGb();
            if (this._destroyed)
                return;
            let usage = '…';
            if (this._prevCpu && cpu.total > this._prevCpu.total)
                usage = `${Math.round(100 * (cpu.busy - this._prevCpu.busy) / (cpu.total - this._prevCpu.total))}%`;
            this._prevCpu = cpu;
            const {cpu: cpuLabel, ram, gb} = this._labels;
            this._label.text = `${cpuLabel}: ${usage}  ${ram}: ${ramGb.toFixed(1)}${gb}`;
        } catch (error) {
            console.error(`SyMo Launcher: failed to read system usage: ${error}`);
            this.stopUpdates();
        } finally {
            this._updating = false;
        }
    }

    destroy() {
        this._destroyed = true;
        this.stopUpdates();
        super.destroy();
    }
});

class SyMoLauncherExtension {
    enable() {
        const extension = ExtensionUtils.getCurrentExtension();
        this._indicator = new SyMoIndicator(extension);
        Main.panel.addToStatusArea(extension.metadata.uuid, this._indicator);
        // Hidden until the watcher reports that SyMo is not running: it always
        // reports the initial state, so the indicator never flashes at login.
        this._setIndicatorVisible(false);
        this._watchId = Gio.bus_watch_name(Gio.BusType.SESSION, BUS_NAME,
            Gio.BusNameWatcherFlags.NONE,
            () => this._setIndicatorVisible(false),
            () => this._setIndicatorVisible(true));
    }

    disable() {
        if (this._watchId) {
            Gio.bus_unwatch_name(this._watchId);
            this._watchId = 0;
        }
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }

    _setIndicatorVisible(visible) {
        if (!this._indicator)
            return;
        this._indicator.container.visible = visible;
        if (visible)
            this._indicator.startUpdates();
        else
            this._indicator.stopUpdates();
    }
}

function init() {
    return new SyMoLauncherExtension();
}
