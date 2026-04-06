# SyMo ([EN](README.md))

<img src="logo.png" width="96" alt="Логотип SyMo" />

SyMo — это лёгкое GTK-приложение для Linux-трея: показывает системные метрики, даёт быстрые действия питания и отправляет уведомления в Telegram/Discord.

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

### Базовые системные пакеты (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install -y \
  python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 \
  gnome-shell-extension-appindicator \
  build-essential libgirepository1.0-dev gir1.2-glib-2.0 \
  gobject-introspection pkg-config libcairo2-dev
```

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

```bash
chmod +x build.sh
./build.sh
```

После сборки запуск из бандла:

```bash
./SyMo-bundle/run-symo.sh
```

`build.sh` также создаёт desktop/autostart записи для использования как обычного приложения.

## Настройка `/screenshot` в Telegram

1. Откройте **Настройки → Уведомления → Telegram**.
2. Заполните:
   - токен бота;
   - chat ID.
3. Включите уведомления Telegram.
4. Выберите **Качество скриншота**:
   - **Низкое** — минимальный размер, быстрая отправка;
   - **Среднее** — баланс (рекомендуется);
   - **Максимальное** — лучшее качество, больший файл.
5. Нажмите **Применить**.
6. В чате с ботом отправьте:

```text
/screenshot
```

Бот сделает скриншот рабочего стола и отправит его в указанный чат.


## Пакет для GNOME Extensions

В репозитории добавлена папка `gnome_extension/` с минимальным GNOME Shell extension (`metadata.json` и `extension.js`) для запуска приложения SyMo из панели GNOME.

Собрать zip-архив для загрузки на <https://extensions.gnome.org/upload/>:

```bash
chmod +x package-gnome-extension.sh
./package-gnome-extension.sh
```

По умолчанию архив создаётся в `dist/symo@olegegoism.github.io.zip`.

Перед загрузкой проверьте:
- UUID в `gnome_extension/metadata.json`;
- поддерживаемые версии `shell-version`;
- что расширение корректно устанавливается локально (`gnome-extensions install --force dist/symo@olegegoism.github.io.zip`).

## Сборка

`build.sh` выполняет:

1. сборку Nuitka `standalone`;
2. попытку сборки Nuitka `onefile`;
3. генерацию launcher-скрипта;
4. упаковку артефактов в `SyMo-bundle/`;
5. создание desktop- и autostart-записей.

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

<img src="img.png" width="560" alt="Превью SyMo" />

## Видео на YouTube:

[![YouTube](https://img.shields.io/badge/YouTube-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://youtube.com/shorts/X1tlQ4XuLSM?feature=share)
