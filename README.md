# SyMo

<img src="logo.png" width="96" alt="SyMo logo" />

SyMo — это GTK‑утилита в системном трее для Linux, которая показывает метрики системы в реальном времени, поддерживает быстрые power‑действия и может отправлять периодические уведомления в Telegram/Discord.

## Возможности

- Мониторинг в реальном времени:
  - загрузка CPU + температура;
  - RAM и SWAP;
  - диск;
  - скорость сети (входящая/исходящая);
  - uptime;
  - счётчики нажатий клавиатуры и кликов мыши.
- Контекстное меню трея с гибкой настройкой видимости пунктов.
- Окна графиков по клику на метрики (CPU, RAM, SWAP, Disk, Network, Keyboard, Mouse).
- Power‑действия:
  - выключение;
  - перезагрузка;
  - блокировка экрана;
  - отложенное выполнение с таймером.
- Уведомления:
  - Telegram bot;
  - Discord webhook.
- Локализация интерфейса.

## Поддерживаемые языки интерфейса

- 🇷🇺 Русский (`ru`)
- 🇬🇧 English (`en`)
- 🇨🇳 中文 (`cn`)
- 🇩🇪 Deutsch (`de`)
- 🇮🇹 Italiano (`it`)
- 🇪🇸 Español (`es`)
- 🇹🇷 Türkçe (`tr`)
- 🇫🇷 Français (`fr`)

## Структура репозитория

```text
SyMo/
├─ app.py                    # тонкий launcher
├─ app_core/                 # core-логика приложения
│  ├─ app.py                 # runtime, tray, меню, графики, обновления
│  ├─ dialogs.py             # окно настроек
│  ├─ power_control.py       # power-команды и таймеры
│  ├─ system_usage.py        # сбор системных метрик
│  ├─ click_tracker.py       # подсчёт клавиатуры/мыши
│  ├─ localization.py        # i18n функции
│  ├─ language.py            # словари переводов
│  ├─ constants.py           # константы и пути к конфигам/логам
│  └─ logging_utils.py       # ротация логов
├─ notifications/
│  ├─ telegram.py            # Telegram notifier + polling команд
│  └─ discord.py             # Discord webhook notifier
├─ tests/                    # тесты pytest
├─ build.sh                  # сборка Nuitka (standalone + onefile)
├─ uninstall-symo.sh         # удаление артефактов/ярлыков/бинарей
├─ requirements.txt
├─ logo.png
├─ img.png
└─ README.md
```

## Требования

- Linux desktop environment с GTK3/AppIndicator (или Ayatana AppIndicator).
- Python 3.10+ (рекомендуется).

### Базовые системные пакеты (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install -y \
  python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 \
  gnome-shell-extension-appindicator \
  build-essential libgirepository1.0-dev gir1.2-glib-2.0 \
  gobject-introspection pkg-config libcairo2-dev
```

### Python‑зависимости

```bash
pip install -r requirements.txt
```

## Запуск в режиме разработки

```bash
python3 app.py
```

## Конфигурационные файлы и лог

Приложение использует файлы в домашней директории пользователя:

- `~/.symo_settings.json` — настройки отображения/поведения;
- `~/.symo_telegram.json` — настройки Telegram;
- `~/.symo_discord.json` — настройки Discord;
- `~/.symo_log.txt` — журнал метрик.

## Сборка

Скрипт `build.sh` выполняет:

1. сборку `standalone` через Nuitka;
2. попытку сборки `onefile`;
3. создание launcher-скриптов;
4. упаковку артефактов в каталог `SyMo-bundle/`;
5. создание desktop entry и autostart entry.

Запуск:

```bash
chmod +x build.sh
./build.sh
```

Проверка результатов:

```bash
ls -la SyMo-bundle
```

Ожидаемые артефакты (в зависимости от успешности onefile-сборки):

- `app.build`
- `app.dist`
- `app.onefile-build`
- `build_standalone`
- `SyMo-standalone`
- `SyMo-onefile`
- `SyMo-launch`
- `SyMo-run`

## Удаление

```bash
chmod +x uninstall-symo.sh
./uninstall-symo.sh
```

Скрипт удаляет:

- локальные build-артефакты рядом с репозиторием;
- desktop/autostart entries (`SyMo.desktop` и `symo.desktop`);
- возможные установленные бинарники/каталоги SyMo.

## Тесты

```bash
pytest -q
```

## Обратная связь

- Автор: [OlegEgoism](https://github.com/OlegEgoism)
- Репозиторий: <https://github.com/OlegEgoism/SyMo>

<img src="img.png" width="560" alt="SyMo preview" />
