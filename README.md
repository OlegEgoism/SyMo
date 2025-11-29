<h1>
"SyMo" Application
</h1>

<img src="logo.png" width="10%" />

<h2 style="color: chocolate">
Application Description and Features
</h2> 

Made By ❤ [OlegEgoism](https://github.com/OlegEgoism)

<h3>System Monitor</h3>

- Real-time display:
    - CPU load with temperature.
    - RAM and SWAP usage.
    - Disk space.
    - Network speed (incoming/outgoing traffic).
    - System uptime.
    - Keyboard presses and mouse clicks counter.
- Customizable interface:
    - Select display parameters.
    - Tray display settings.
    - Send notifications to Telegram and Discord on timer.

<h3>Power Management</h3>

- Quick actions:
    - Shut down computer.
    - Restart computer.
    - Lock computer screen.
- Timer commands:
    - Delayed action execution.
    - Notifications before execution.

<h3>Available Interface Languages</h3>

- 🇷🇺 Russian.
- 🇬🇧 English.
- 🇨🇳 Chinese.
- 🇩🇪 German.
- 🇮🇹 Italian.
- 🇪🇸 Spanish.
- 🇹🇷 Turkish.
- 🇸🇦 Arabic.
- 🇫🇷 French.

<h3>Feedback and Support</h3>

- Email: olegpustovalov220@gmail.com
- Special thanks for help: https://github.com/korneyka3000
- Developers: https://github.com/korneyka3000, https://github.com/OlegEgoism

<h3>Video Demonstration</h3>

[![YouTube Video](https://img.youtube.com/vi/eNh-yalHPO0/0.jpg)](https://www.youtube.com/watch?v=eNh-yalHPO0)

<h2 style="color: chocolate">
Telegram and Discord Integration
</h2>

<h3>Telegram Instructions</h3>

To create and get information about "Token": https://web.telegram.org/k/#@BotFather

To get "Chat ID": https://web.telegram.org/k/#@getmyid_bot

<h3>Discord Instructions</h3>

- Open Discord → select your server.
- Go to Server Settings → Integrations → Webhooks.
- Click "Create Webhook".

<h2 style="color: chocolate">
Running in Development Mode
</h2>

<h3>💡 apt Installation for Debian/Ubuntu (core libraries)</h3>

```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1
sudo apt install -y build-essential libgirepository1.0-dev gir1.2-glib-2.0 python3-gi python3-gi-cairo gobject-introspection
```

<h3>💡 If there are problems with startup</h3>

```bash
sudo apt update
sudo apt install python3.10-dev
sudo apt install pkg-config
sudo apt install libcairo2-dev
sudo apt install build-essential
sudo apt install gnome-shell-extension-appindicator
pip install pygobject
```

<h3>💡 Python-dependencies</h3>

```bash
pip install -r requirements.txt
```

<h3>💡 Launching the application</h3>

```bash
python3 app.py
```

<h2 style="color: chocolate">
    Building app
    <span style="color: red">(recommended)</span>
</h2>

<h3>💡 Launch file "build.sh" (assembly time up to 5 minutes)</h3>

```bash
chmod +x build.sh
./build.sh
```

<h3>💡 Checking the created file SyMo-onefile</h3>

```bash
ls -l *SyMo-onefile
```

The build script also prepares an archive with everything needed to install the app on another machine:

```bash
ls -l dist/SyMo-installer.tar.gz
```


<h2 style="color: chocolate">
  Remove
  <span style="color: red">(recommended)</span>
</h2>

```bash
chmod +x uninstall-symo.sh
./uninstall-symo.sh
```