# core/importer.py
import shutil
import os
import zipfile
from pathlib import Path
from datetime import datetime

import py7zr

from core.database import Mod, ModFile, HofFile, ModType
from core.analyzer import ModAnalyzer


class ModImporter:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger  # Логгер для отправки сообщений в UI

    def step1_prepare_preview(self, archive_path):
        """
        РАЗВЕДКА: Распаковка и Анализ.
        Возвращает структуру отчета для пользователя.
        """
        archive_path = Path(archive_path)
        self.logger.log(f"Начинаю обработку архива: {archive_path.name}")

        # 1. Генерируем временное имя папки
        mod_folder_name = f"{archive_path.stem}_{int(datetime.now().timestamp())}"
        extract_path = Path(self.config.library_path) / "Mods" / mod_folder_name

        # 2. Распаковка
        self.logger.log("Распаковка файлов...", "info")
        try:
            extract_path.mkdir(parents=True, exist_ok=True)
            self._extract_archive(archive_path, extract_path)
        except Exception as e:
            if extract_path.exists(): shutil.rmtree(extract_path)
            self.logger.log(f"Ошибка распаковки: {e}", "error")
            return None

        # 3. Анализ
        self.logger.log("Анализ структуры...", "info")
        analyzer = ModAnalyzer(extract_path)
        structure = analyzer.analyze()

        # 4. Формируем отчет (Preview Data)
        # Нам нужно показать пользователю, какие файлы куда пойдут

        mapped_files = []  # Файлы, которые мы поняли куда класть
        unmapped_files = []  # Файлы, которые "висят в воздухе" (мусор?)
        hof_files = []  # Найденные хофы

        mod_root = extract_path
        analysis_root = structure['root_path']

        self.logger.log(f"Определен тип мода: {structure['type'].value}", "success")
        if analysis_root:
            self.logger.log(f"Корневая папка найдена: {analysis_root.name}")
        else:
            self.logger.log("Внимание: Корневая папка не найдена явно!", "warning")

        # Пробегаем по файлам для отчета
        for root, dirs, files in os.walk(mod_root):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(mod_root)

                # Логика определения пути (как в прошлом коде)
                target_path = None
                status = "unknown"

                if file.lower().endswith('.hof'):
                    hof_files.append(str(rel_path))
                    status = "hof"

                if analysis_root:
                    try:
                        # Если файл внутри "полезной" структуры
                        path_from_root = full_path.relative_to(analysis_root)
                        target_path = str(path_from_root)
                        status = "mapped"

                        if structure.get('is_flat_bus'):
                            target_path = f"Vehicles\\{archive_path.stem}\\{path_from_root}"
                    except ValueError:
                        # Файл снаружи (readme, url, pictures)
                        status = "unmapped"
                else:
                    status = "unmapped"

                file_info = {
                    "source": str(rel_path),
                    "target": target_path if target_path else "???",
                    "status": status
                }

                if status == "mapped":
                    mapped_files.append(file_info)
                elif status == "unmapped":
                    unmapped_files.append(file_info)

        if len(unmapped_files) > 0:
            self.logger.log(f"Найдено {len(unmapped_files)} файлов без явного назначения", "warning")

        # Возвращаем данные для UI. 
        # temp_id нужен, чтобы потом подтвердить установку (это путь к папке)
        return {
            "temp_id": str(extract_path),
            "mod_name": archive_path.stem,
            "type": structure['type'].value,
            "mapped_files": mapped_files,
            "unmapped_files": unmapped_files,
            "hof_files": hof_files,
            "structure_data": structure  # Сохраняем сырые данные анализа для шага 2
        }

    def step2_confirm_import(self, preview_data):
        """
        ФИНАЛ: Пользователь нажал ОК. Записываем в БД.
        """
        extract_path = Path(preview_data['temp_id'])
        mod_name = preview_data['mod_name']
        structure = preview_data['structure_data']  # Получаем обратно из UI

        self.logger.log("Сохранение в базу данных...", "info")

        new_mod = Mod(
            name=mod_name,
            mod_type=ModType(preview_data['type']),
            storage_path=str(extract_path),
            is_enabled=False
        )
        self.session.add(new_mod)
        self.session.flush()

        # Тут мы должны были бы фильтровать файлы, если юзер снял галочки
        # Но для начала запишем всё, как "mapped" (из preview_data лучше брать, если будем расширять)
        # Для простоты используем ту же логику _register_files, но теперь это безопасно
        self._register_files(new_mod, structure)

        self.session.commit()
        self.logger.log(f"Мод {mod_name} успешно добавлен в библиотеку!", "success")
        return True

    def cancel_import(self, temp_path):
        """Если пользователь нажал Отмена - удаляем распакованное"""
        path = Path(temp_path)
        if path.exists():
            shutil.rmtree(path)
            self.logger.log("Импорт отменен. Временные файлы удалены.", "info")

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