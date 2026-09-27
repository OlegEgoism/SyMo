// SyMo Launcher for GNOME Shell 42-44 (legacy imports).

const {GLib, GObject, Gio, Shell, St} = imports.gi;

const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const ExtensionUtils = imports.misc.extensionUtils;

const DESKTOP_ID = 'SyMo.desktop';
const COMMANDS = ['symo', 'SyMo'];

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

const SyMoIndicator = GObject.registerClass(
class SyMoIndicator extends PanelMenu.Button {
    _init(metadata) {
        super._init(0.0, metadata.name);

        this.add_child(new St.Icon({
            icon_name: 'utilities-system-monitor-symbolic',
            style_class: 'system-status-icon',
        }));

        const openItem = new PopupMenu.PopupMenuItem('Open SyMo');
        openItem.connect('activate', () => launchSyMo(metadata.name));
        this.menu.addMenuItem(openItem);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const pageItem = new PopupMenu.PopupMenuItem('Project page');
        pageItem.connect('activate', () => {
            try {
                Gio.AppInfo.launch_default_for_uri(metadata.url, global.create_app_launch_context(0, -1));
            } catch (error) {
                console.error(`${metadata.name}: failed to open ${metadata.url}: ${error}`);
            }
        });
        this.menu.addMenuItem(pageItem);
    }
});

class SyMoLauncherExtension {
    enable() {
        const metadata = ExtensionUtils.getCurrentExtension().metadata;
        this._indicator = new SyMoIndicator(metadata);
        Main.panel.addToStatusArea(metadata.uuid, this._indicator);
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}

function init() {
    return new SyMoLauncherExtension();
}
