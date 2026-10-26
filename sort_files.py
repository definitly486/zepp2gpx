import os
import shutil
from datetime import datetime

# Путь к текущей директории, где лежит скрипт
source_dir = os.path.dirname(os.path.abspath(__file__))

for filename in os.listdir(source_dir):
    file_path = os.path.join(source_dir, filename)
    
    # Пропускаем сам скрипт и папки
    if os.path.isdir(file_path) or filename == "sort_files.py":
        continue
        
    year, month = None, None
    name, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext == '.gpx':
        # Пример: 2023-04-14_053642_1681439802.gpx -> берем первые 7 символов
        try:
            date_str = name[:7] # "2023-04"
            year, month = date_str.split('-')
        except ValueError:
            continue

    elif ext == '.json':
        # Пример: 1681439802.json -> конвертируем Unix timestamp
        try:
            timestamp = int(name)
            date_obj = datetime.fromtimestamp(timestamp)
            year = date_obj.strftime('%Y')
            month = date_obj.strftime('%m')
        except ValueError:
            continue

    if year and month:
        # Создаем структуру папок: Год/Месяц (например: 2023/04)
        target_dir = os.path.join(source_dir, year, month)
        os.makedirs(target_dir, exist_ok=True)
        
        # Переносим файл
        shutil.move(file_path, os.path.join(target_dir, filename))

print("Сортировка успешно завершена!")
