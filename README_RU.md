# SyMo ([EN](README.md))

<img src="logo.png" width="96" alt="Логотип SyMo" />

SyMo — это лёгкое GTK-приложение для Linux-трея: показывает системные метрики и отправляет уведомления в Telegram/Discord.

## Минимальное описание проекта

- Мониторинг в трее (CPU/RAM/Swap/Disk/Network/Uptime).
- Быстрые действия: выключение, перезагрузка, блокировка, таймер.
- Команды Telegram-бота: `/status`, `/screenshot`.
- Уведомления через Discord webhook.

## Возможности

- Мониторинг системы в реальном времени:
    - загрузка и температура CPU;
    - использование RAM и swap;
    - использование диска;
    - скорость сети (скачивание/загрузка);
    - аптайм;
    - счётчики активности клавиатуры и мыши.
- Настраиваемое меню в трее:
    - показывать/скрывать пункты меню;
    - изменять порядок пунктов меню перетаскиванием в Настройках.
- Отдельные окна графиков по каждой метрике (CPU, RAM, Swap, Disk, Network, Keyboard, Mouse).
  - Интерактивное управление в окнах графиков:
    - колесо мыши: масштабирование по горизонтали;
    - зажатая левая кнопка мыши + движение: горизонтальное перемещение графика;
    - наведение курсора: подсказка рядом с мышью с временем и значениями ближайшей точки.
- Управление питанием:
    - выключение;
    - перезагрузка;
    - блокировка экрана;
    - отложенное выполнение с планировщиком/таймером.
- Уведомления:
    - интеграция с Telegram-ботом;
    - интеграция с Discord webhook.
  - Команды Telegram-бота:
    - `/status` — текущий статус системы;
    - `/screenshot` — сделать скриншот экрана и отправить в Telegram.
- Многоязычный интерфейс.

## Поддерживаемые языки интерфейса

- 🇷🇺 Русский (`ru`)
- 🇬🇧 Английский (`en`)
- 🇨🇳 Китайский (`cn`)
- 🇩🇪 Немецкий (`de`)
- 🇮🇹 Итальянский (`it`)
- 🇪🇸 Испанский (`es`)
- 🇹🇷 Турецкий (`tr`)
- 🇫🇷 Французский (`fr`)

## Структура репозитория

```text
SyMo/
├─ app.py                    # тонкий launcher
├─ app_core/                 # основная логика приложения
│  ├─ app.py                 # runtime, tray, menu, graphs, updates
│  ├─ dialogs.py             # диалог настроек
│  ├─ power_control.py       # команды питания и таймеры
│  ├─ system_usage.py        # сбор системных метрик
│  ├─ click_tracker.py       # счётчики клавиатуры/мыши
│  ├─ localization.py        # i18n-утилиты
│  ├─ language.py            # словари переводов
│  ├─ constants.py           # константы и пути config/log
│  └─ logging_utils.py       # утилиты ротации логов
├─ notifications/
│  ├─ telegram.py            # уведомления Telegram + опрос команд
│  └─ discord.py             # уведомления Discord webhook
├─ tests/                    # наборы тестов pytest
├─ build.sh                  # сборка Nuitka (standalone + onefile)
├─ uninstall-symo.sh         # удаляет артефакты/desktop-файлы/бинарники
├─ requirements.txt
├─ logo.png
├─ img.png
└─ README.md
```

## Требования

- Linux-окружение рабочего стола с GTK3 + AppIndicator (или Ayatana AppIndicator).
- Python 3.10+ (рекомендуется).

### Дополнительные зависимости для `/screenshot` в Telegram

SyMo использует несколько backend’ов для скриншота. Установите хотя бы один:

```bash
sudo apt install -y gnome-screenshot scrot grim imagemagick
```

> Примечания:
> - Для GNOME/X11 обычно достаточно `gnome-screenshot`.
> - Для Wayland-композиторов (например, Sway) чаще используют `grim`.
> - Пакет `imagemagick` даёт fallback-команду `import`.

### Python-зависимости

```bash
pip install -r requirements.txt
```

## Основные команды

### Запуск в режиме разработки

```bash
python3 app.py
```

### Установка зависимостей (разработка)

```bash
sudo apt update
sudo apt install -y \
  python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 \
  gnome-shell-extension-appindicator \
  build-essential libgirepository1.0-dev gir1.2-glib-2.0 \
  gobject-introspection pkg-config libcairo2-dev \
  gnome-screenshot scrot grim imagemagick
pip install -r requirements.txt
```

### Установка как приложения
Запуск:

```bash
chmod +x build.sh
./build.sh
```

Проверить результат:

```bash
ls -la SyMo-bundle
```

## Удаление

```bash
chmod +x uninstall-symo.sh
./uninstall-symo.sh
```

## Тесты

```bash
pytest -q
```

## Контакты

- Автор: [OlegEgoism](https://github.com/OlegEgoism)
- Репозиторий: <https://github.com/OlegEgoism/SyMo>
- Telegram: [@OlegEgoism](https://t.me/OlegEgoism)
- Email: olegpustovalov220@gmail.com

<img src="img.png" width="960" alt="SyMo preview" />

## Видео на YouTube:

[![YouTube](https://img.shields.io/badge/YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtube.com/shorts/X1tlQ4XuLSM?feature=share)
[![YouTube](https://img.shields.io/badge/YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtu.be/zvdoo9JA88k)
