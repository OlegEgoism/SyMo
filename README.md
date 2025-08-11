<h1 style="color: aqua">
Приложение SyMo Ⓡ
</h1>

<h2 style="color: chocolate">
Описание и функционал приложения
</h2> 

<h3>Системный монитор</h3>
- Реальное время отображения:
  - Загрузка CPU с температурой.
  - Использование RAM и SWAP.
  - Дисковое пространство.
  - Скорость сети (входящий/исходящий трафик).
  - Время работы системы.
  - Счетчик нажатий клавиш и кликов мыши.
- Настраиваемый интерфейс:
  - Выбор отображаемых параметров.
  - Настройка отображения в трее.
  - Отправка уведомлений в Telegram и Discord по таймеру.

<h3>Управление питанием</h3>
- Быстрые действия:
  - Выключение компьютера.
  - Перезагрузка компьютера.
  - Блокировка экрана компьютера.
- Таймерные команды:
  - Отложенное выполнение действий.
  - Уведомления перед выполнением.

<h3>Доступные языки интерфейса</h3>
- Русский.
- Английский.
- Китайский.
- Немецкий.

<h3>Обратная связь и поддержка</h3> 
- Почта: olegpustovalov220@gmail.com 
- Телеграмм: @OlegEgoism
- Благодарность за помощь: https://github.com/korneyka3000

<h3>Видео демонстрация</h3>

[![Видео на YouTube](https://img.youtube.com/vi/eNh-yalHPO0/0.jpg)](https://www.youtube.com/watch?v=eNh-yalHPO0)

---------------------------------------------------------------------------------
<h2 style="color: chocolate">Подключение Telegram и Discord</h2>

<h3>Инструкция Telegram</h3>
Для создания и получения информации о "Токене": https://web.telegram.org/k/#@BotFather

Для получения "ID чата": https://web.telegram.org/k/#@getmyid_bot

<h3>Инструкция Discord</h3>
- Открой Discord → выбери сервер.
- Перейди в Настройки сервера → Интеграции → Вебхуки.
- Нажми "Создать Вебхук".

---------------------------------------------------------------------------------
<h2 style="color: chocolate">
Запуск в режиме разработки
</h2>

<h3>💡 Установка apt для Debian/Ubuntu (основные библиотеки)</h3>
```bash
sudo apt update
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1
sudo apt install -y build-essential libgirepository1.0-dev gir1.2-glib-2.0 python3-gi python3-gi-cairo gobject-introspection
```

<h3>💡 Если буду проблемы при запуске</h3>
```bash
sudo apt update
sudo apt install python3.10-dev
sudo apt install pkg-config
sudo apt install libcairo2-dev
sudo apt install build-essential
sudo apt install gnome-shell-extension-appindicator
pip install pygobject
```

<h3>💡 Python-зависимости</h3>
```bash
pip install -r requirements.txt
```

<h3>💡 Запуск приложения</h3>
```bash
python3 app.py
```

---------------------------------------------------------------------------------
<h2 style="color: chocolate">
    Сборка в исполняемый файл 
    <span style="color: red">(рекомендуемый вариант!)</span>
</h2>


<h3>💡 Запуск файла "build.sh" (время выполнение сборки до 5 минут)</h3>
```bash
chmod +x build.sh
./build.sh
```

<h3>💡 Проверка созданного файла SyMo-onefile</h3>
```bash
ls -l *SyMo-onefile
```

<h3>💡 После успешной сборки у вас появится иконка приложения "SyMo"</h3>

---------------------------------------------------------------------------------
<h2 style="color: chocolate">
Сборка приложения .deb
</h2>

<h3>💡 Запуск файла "build_deb.sh"</h3>
```bash
chmod +x build_deb.sh
./build_deb.sh
```

<h3>💡 Установка после успешной сборки</h3>
```bash
sudo dpkg -i SyMo_1.0.1_all.deb
```

<h3>💡 Удалить пакет (рекомендуемый способ)</h3>
```bash
sudo apt remove symo
```
```bash
sudo apt purge SyMo
```

<h3>💡 Убедится, что пакет удален</h3>
```bash
which SyMo
dpkg -l | grep SyMo
```

