# SyMo Ⓡ
- 🇧🇾 Приложение SyMo для мониторинга системы и управления питанием с иконкой в трее. 🇧🇾 

# Основные функции
Системный монитор
- Реальное время отображения:
  - Загрузка CPU (с температурой)
  - Использование RAM и SWAP
  - Дисковое пространство
  - Скорость сети (входящий/исходящий трафик)
  - Время работы системы (uptime)
  - Счетчик нажатий клавиш и кликов мыши
- Настраиваемый интерфейс:
  - Выбор отображаемых параметров
  - Настройка отображения в трее

Управление питанием
- Быстрые действия:
  - Выключение компьютера
  - Перезагрузка компьютера
  - Блокировка экрана компьютера
- Таймерные команды:
  - Отложенное выполнение действий
  - Уведомления перед выполнением

Доступные языки интерфейса:
- Русский
- Английский
- Китайский
- Немецкий

---------------------------------------------------------------------------------
🎥 Видео-демо
[![Watch the video](https://img.youtube.com/vi/lcWTL0O7paI/maxresdefault.jpg)](https://www.youtube.com/watch?v=lcWTL0O7paI)

---------------------------------------------------------------------------------
-  ЗАПУСК В РЕЖИМИ РАЗАРБОТКИ.

💡 Установка apt для Debian/Ubuntu (основные библиотеки).
```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1
sudo apt install -y build-essential libgirepository1.0-dev gir1.2-glib-2.0 python3-gi python3-gi-cairo gobject-introspection
```

💡 Если буду проблемы при запуске.
```bash
sudo apt update
sudo apt install python3.10-dev
sudo apt install pkg-config
sudo apt install libcairo2-dev
sudo apt install build-essential
sudo apt install gnome-shell-extension-appindicator
pip install pygobject
```

💡 Python-зависимости.
```bash
pip install -r requirements.txt
```

💡 Запуск.
```bash
python3 app.py
```

---------------------------------------------------------------------------------
- СБОРКА ПРИЛОЖЕНИЯ

💡 Сборка приложения в пакет (файлы и папки). В файле "build_deb.sh" вся структура проекта для сборки приложения!
```bash
chmod +x build_deb.sh
./build_deb.sh
dpkg-deb --build deb_build/SyMo deb_build/SyMo.deb
```

💡 Установка собранного пакета.
```bash
sudo dpkg -i deb_build/SyMo.deb
```

💡 Удалить пакет
```bash
sudo dpkg -r symo
sudo apt --fix-broken install
```

💡 Убедится, что пакет удален
```bash
dpkg -l | grep symo
```

---------------------------------------------------------------------------------
- ОБРАТНАЯ СВЯЗЬ

- Почта: olegpustovalov220@gmail.com 
- Телеграмм: @OlegEgoism

