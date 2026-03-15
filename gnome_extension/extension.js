import Gio from 'gi://Gio';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const UUID = 'symo@olegegoism.github.io';
const APP_BINARY = 'SyMo';

class SyMoLauncherIndicator extends PanelMenu.Button {
    constructor() {
        super(0.0, 'SyMo Launcher');

        this._icon = new St.Icon({
            icon_name: 'utilities-system-monitor-symbolic',
            style_class: 'system-status-icon',
        });
        this.add_child(this._icon);

        this._openItem = new PopupMenu.PopupMenuItem('Open SyMo');
        this._openItem.connect('activate', () => this._launchSyMo());
        this.menu.addMenuItem(this._openItem);

        this._separator = new PopupMenu.PopupSeparatorMenuItem();
        this.menu.addMenuItem(this._separator);

        this._aboutItem = new PopupMenu.PopupMenuItem('About SyMo');
        this._aboutItem.connect('activate', () => {
            Main.notify('SyMo', 'SyMo launcher extension is active.');
        });
        this.menu.addMenuItem(this._aboutItem);
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
}

export default class SyMoExtension {
    enable() {
        this._indicator = new SyMoLauncherIndicator();
        Main.panel.addToStatusArea(UUID, this._indicator);
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
