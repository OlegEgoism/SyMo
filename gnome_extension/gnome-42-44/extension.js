// SPDX-License-Identifier: GPL-2.0-or-later
// SyMo Launcher for GNOME Shell 42-44 (legacy imports).

const {GLib, GObject, Gio, Shell, St} = imports.gi;

const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ExtensionUtils = imports.misc.extensionUtils;

const DESKTOP_ID = 'SyMo.desktop';
const COMMANDS = ['symo', 'SyMo'];
// SyMo owns this name on the session bus while it runs.
const BUS_NAME = 'io.github.olegegoism.SyMo';
// Owned by the panel extension that draws tray (AppIndicator) icons. Without it
// SyMo's own icon cannot be shown, so the launcher button must stay visible.
const TRAY_WATCHER_NAME = 'org.kde.StatusNotifierWatcher';
const TRAY_SUPPORT_URL = 'https://extensions.gnome.org/extension/615/appindicator-support/';

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
    Main.notify(name, 'SyMo is not installed. Download it from https://github.com/OlegEgoism/SyMo');
}

function openUri(name, uri) {
    try {
        Gio.AppInfo.launch_default_for_uri(uri, global.create_app_launch_context(0, -1));
    } catch (error) {
        console.error(`${name}: failed to open ${uri}: ${error}`);
    }
}

const SyMoIndicator = GObject.registerClass(
class SyMoIndicator extends PanelMenu.Button {
    _init(metadata) {
        super._init(0.0, metadata.name);

        this.add_child(new St.Icon({
            icon_name: 'utilities-system-monitor-symbolic',
            style_class: 'system-status-icon',
        }));

        this._openItem = new PopupMenu.PopupMenuItem('Open SyMo');
        this._openItem.connect('activate', () => launchSyMo(metadata.name));
        this.menu.addMenuItem(this._openItem);

        // Shown instead of "Open SyMo" when SyMo runs but no tray is available.
        this._trayHintItem = new PopupMenu.PopupMenuItem(
            'SyMo is running, but its tray icon cannot be shown', {reactive: false});
        this.menu.addMenuItem(this._trayHintItem);
        this._traySupportItem = new PopupMenu.PopupMenuItem('Install tray icon support');
        this._traySupportItem.connect('activate', () => openUri(metadata.name, TRAY_SUPPORT_URL));
        this.menu.addMenuItem(this._traySupportItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const pageItem = new PopupMenu.PopupMenuItem('Project page');
        pageItem.connect('activate', () => openUri(metadata.name, metadata.url));
        this.menu.addMenuItem(pageItem);

        this.setTrayMissing(false);
    }

    setTrayMissing(missing) {
        this._openItem.visible = !missing;
        this._trayHintItem.visible = missing;
        this._traySupportItem.visible = missing;
    }
});

class SyMoLauncherExtension {
    enable() {
        const metadata = ExtensionUtils.getCurrentExtension().metadata;
        this._indicator = new SyMoIndicator(metadata);
        Main.panel.addToStatusArea(metadata.uuid, this._indicator);
        // The button stays hidden until both watchers report their initial
        // state, so it never flashes at login.
        this._indicator.container.visible = false;
        this._appRunning = false;
        this._trayAvailable = false;
        this._pendingWatches = 2;
        this._appWatchId = this._watchName(BUS_NAME, running => {
            this._appRunning = running;
        });
        this._trayWatchId = this._watchName(TRAY_WATCHER_NAME, available => {
            this._trayAvailable = available;
        });
    }

    disable() {
        for (const id of [this._appWatchId, this._trayWatchId]) {
            if (id)
                Gio.bus_unwatch_name(id);
        }
        this._appWatchId = 0;
        this._trayWatchId = 0;
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }

    _watchName(name, setState) {
        let reported = false;
        const update = present => {
            setState(present);
            if (!reported) {
                reported = true;
                this._pendingWatches--;
            }
            this._sync();
        };
        return Gio.bus_watch_name(Gio.BusType.SESSION, name, Gio.BusNameWatcherFlags.NONE,
            () => update(true), () => update(false));
    }

    // Hide the button only when SyMo's own tray icon is actually visible.
    _sync() {
        if (!this._indicator || this._pendingWatches > 0)
            return;
        this._indicator.setTrayMissing(this._appRunning && !this._trayAvailable);
        this._indicator.container.visible = !(this._appRunning && this._trayAvailable);
    }
}

function init() {
    return new SyMoLauncherExtension();
}
