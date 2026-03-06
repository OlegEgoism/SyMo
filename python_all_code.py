import os
from pathlib import Path

def combine_files(output_file="python_all_code.txt"):
    """
    Объединяет код из указанных файлов в один файл.
    """
    # Определяем корневую директорию проекта (предполагается, что скрипт запускается из корня проекта)
    project_root = Path.cwd()
    
    # Список файлов для объединения с путями относительно корня проекта
    files_to_combine = [
        "power_control.py",
        "system_usage.py",
        "logging_utils.py",
        "localization.py",
        "dialogs.py",
        "constants.py",
        "click_tracker.py",
        "app.py",
    ]
    
    # Файлы из папки notifications
    notifications_files = [
        "notifications/telegram.py",
        "notifications/discord.py",
        "notifications/__init__.py",
    ]
    
    # Добавляем файлы из папки notifications в общий список
    files_to_combine.extend(notifications_files)
    
    with open(output_file, "w", encoding="utf-8") as outfile:
        outfile.write(f"# Объединенный код проекта SyMo\n")
        outfile.write(f"# Сгенерировано автоматически\n")
        outfile.write(f"# Файлы объединены в следующем порядке:\n")
        
        for i, file_path in enumerate(files_to_combine, 1):
            outfile.write(f"# {i}. {file_path}\n")
        
        outfile.write(f"\n{'='*80}\n\n")
        
        # Проходим по всем файлам и добавляем их содержимое
        for file_path in files_to_combine:
            full_path = project_root / file_path
            
            if full_path.exists():
                outfile.write(f"\n{'='*80}\n")
                outfile.write(f"# Файл: {file_path}\n")
                outfile.write(f"{'='*80}\n\n")
                
                try:
                    with open(full_path, "r", encoding="utf-8") as infile:
                        content = infile.read()
                        outfile.write(content)
                        outfile.write("\n\n")
                        print(f"✓ Добавлен: {file_path}")
                except UnicodeDecodeError:
                    # Попробуем другую кодировку
                    try:
                        with open(full_path, "r", encoding="cp1251") as infile:
                            content = infile.read()
                            outfile.write(content)
                            outfile.write("\n\n")
                            print(f"✓ Добавлен: {file_path} (кодировка: cp1251)")
                    except Exception as e:
                        print(f"✗ Ошибка при чтении {file_path}: {e}")
                        outfile.write(f"# ОШИБКА: Не удалось прочитать файл {file_path}\n")
                        outfile.write(f"# {str(e)}\n\n")
                except Exception as e:
                    print(f"✗ Ошибка при чтении {file_path}: {e}")
                    outfile.write(f"# ОШИБКА: Не удалось прочитать файл {file_path}\n")
                    outfile.write(f"# {str(e)}\n\n")
            else:
                print(f"✗ Файл не найден: {file_path}")
                outfile.write(f"\n{'='*80}\n")
                outfile.write(f"# Файл не найден: {file_path}\n")
                outfile.write(f"{'='*80}\n\n")
        
        outfile.write(f"\n{'='*80}\n")
        outfile.write(f"# Конец объединенного файла\n")
        outfile.write(f"{'='*80}\n")
    
    print(f"\n✅ Объединение завершено! Результат сохранен в файл: {output_file}")
    print(f"📊 Всего обработано файлов: {len(files_to_combine)}")

if __name__ == "__main__":
    # Запускаем объединение
    combine_files()
    
    # Дополнительная информация
    output_file = "python_all_code.txt"
    if os.path.exists(output_file):
        file_size = os.path.getsize(output_file)
        print(f"📁 Размер выходного файла: {file_size} байт ({file_size/1024:.2f} KB)")