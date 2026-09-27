// SPDX-License-Identifier: GPL-2.0-or-later
// SyMo Launcher for GNOME Shell 45 and newer (ES modules).

import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

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

export default class SyMoLauncherExtension extends Extension {
    enable() {
        this._indicator = new SyMoIndicator(this.metadata);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        this._indicator?.destroy();
        this._indicator = null;
    }
}
