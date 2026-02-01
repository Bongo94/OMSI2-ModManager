import os
import shutil
import zipfile
import py7zr
import hashlib
from datetime import datetime
from pathlib import Path
from core.database import Mod, ModFile, HofFile, ModType
from core.analyzer import ModAnalyzer


class ModImporter:
    def __init__(self, config_manager):
        self.config = config_manager
        self.session = config_manager.session

    def import_mod_archive(self, archive_path):
        """
        Главная функция: принимает путь к архиву, делает всё остальное.
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            return False, "Файл не найден"

        # 1. Создаем папку для мода в библиотеке
        # Имя папки = ИмяАрхива_Timestamp (чтобы не было дублей)
        mod_folder_name = f"{archive_path.stem}_{int(datetime.now().timestamp())}"
        extract_path = Path(self.config.library_path) / "Mods" / mod_folder_name
        extract_path.mkdir(parents=True, exist_ok=True)

        # 2. Распаковка
        try:
            self._extract_archive(archive_path, extract_path)
        except Exception as e:
            # Если ошибка, чистим за собой
            shutil.rmtree(extract_path)
            return False, f"Ошибка распаковки: {str(e)}"

        # 3. Анализ
        analyzer = ModAnalyzer(extract_path)
        structure = analyzer.analyze()

        # 4. Запись в БД
        new_mod = Mod(
            name=archive_path.stem,
            mod_type=structure['type'],
            storage_path=str(extract_path),  # Храним абсолютный путь или относительный
            is_enabled=False
        )
        self.session.add(new_mod)
        self.session.flush()  # Чтобы получить ID мода

        # Регистрируем все файлы
        self._register_files(new_mod, structure)

        self.session.commit()
        return True, f"Мод '{new_mod.name}' успешно добавлен!"

    def _extract_archive(self, archive_path, target_path):
        """Определяет тип архива и распаковывает"""
        ext = archive_path.suffix.lower()

        if ext == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(target_path)

        elif ext == '.7z':
            with py7zr.SevenZipFile(archive_path, mode='r') as z:
                z.extractall(path=target_path)

        elif ext == '.rar':
            # Для RAR нужен установленный WinRAR или patool
            # Пока оставим базовую проверку
            raise Exception("RAR формат пока требует ручной распаковки (сложно автоматизировать без WinRAR)")

        else:
            raise Exception("Неизвестный формат архива")

    def _register_files(self, mod, structure):
        """Проходит по файлам и записывает их в БД"""
        mod_root = Path(mod.storage_path)

        # Определяем "смещение" для путей игры
        # Если structure['root_path'] == .../MyMod/OMSI, то файлы внутри пойдут в корень
        analysis_root = structure['root_path']

        for root, dirs, files in os.walk(mod_root):
            for file in files:
                full_path = Path(root) / file
                rel_path_in_mod = full_path.relative_to(mod_root)

                # Вычисляем целевой путь (куда это должно встать в игре)
                target_game_path = None

                if analysis_root:
                    try:
                        # Пытаемся понять путь относительно найденного "корня OMSI"
                        path_from_analysis_root = full_path.relative_to(analysis_root)
                        target_game_path = str(path_from_analysis_root)

                        # КОРРЕКЦИЯ для "голых" автобусов
                        if structure.get('is_flat_bus'):
                            # Если это голый автобус, его файлы должны лететь в Vehicles/ИмяМода/
                            target_game_path = str(Path('Vehicles') / mod.name / path_from_analysis_root)

                    except ValueError:
                        # Файл лежит вне найденного корня (мусор или readme)
                        target_game_path = None

                is_hof = (file.lower().endswith('.hof'))

                # Создаем запись о файле
                db_file = ModFile(
                    mod_id=mod.id,
                    source_rel_path=str(rel_path_in_mod),
                    target_game_path=target_game_path,
                    is_hof=is_hof,
                    file_hash="pending"  # Хеш посчитаем позже, если нужно, для скорости
                )
                self.session.add(db_file)

                # Если это HOF, добавляем в спец. таблицу
                if is_hof:
                    hof_entry = HofFile(
                        mod_id=mod.id,
                        filename=file,
                        full_source_path=str(full_path),
                        description="Автоматически найден"
                    )
                    self.session.add(hof_entry)