import os
import shutil
import zipfile
import py7zr
import rarfile
import time
from datetime import datetime
from pathlib import Path
from core.database import Mod, ModFile, HofFile, ModType
from core.analyzer import ModAnalyzer

# Указываем rarfile, где искать UnRAR.exe
rarfile.UNRAR_TOOL = "UnRAR.exe"


class ModImporter:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger

    def _progress_callback(self, item_name, current, total):
        percent = int((current / total) * 100) if total > 0 else 0
        if current % 10 == 0 or current == total:
            self.logger.log(f"{current}/{total}: {item_name}", level="progress", progress=percent)
            time.sleep(0.001)

    def _extract_archive(self, archive_path, target_path):
        """
        Распаковывает архив с максимальной скоростью (используя extractall).
        """
        ext = archive_path.suffix.lower()
        target_path_str = str(target_path)

        self.logger.log(f"Распаковка {ext} (Turbo Mode)...", "info")
        self._progress_callback("Распаковка архива...", 50, 100)

        try:
            if ext == '.zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(target_path_str)

            elif ext == '.7z':
                with py7zr.SevenZipFile(archive_path, mode='r') as z:
                    z.extractall(path=target_path_str)

            elif ext == '.rar':
                if not os.path.exists(rarfile.UNRAR_TOOL):
                    raise FileNotFoundError(f"Не найден {rarfile.UNRAR_TOOL}!")
                with rarfile.RarFile(archive_path) as rf:
                    rf.extractall(target_path_str)
            else:
                raise Exception(f"Неподдерживаемый формат: {ext}")

            self._progress_callback("Распаковка завершена", 100, 100)

        except Exception as e:
            self.logger.log(f"Сбой при распаковке: {str(e)}", "error")
            raise e

    def step1_prepare_preview(self, archive_path):
        archive_path = Path(archive_path)
        self.logger.log(f"Начинаю обработку: {archive_path.name}")

        mod_folder_name = f"{archive_path.stem}_{int(datetime.now().timestamp())}"
        extract_path = Path(self.config.library_path) / "Mods" / mod_folder_name

        try:
            self.logger.log("Создание временной папки...", "info")
            extract_path.mkdir(parents=True, exist_ok=True)
            self._extract_archive(archive_path, extract_path)
        except Exception as e:
            if extract_path.exists(): shutil.rmtree(extract_path)
            self.logger.log(f"Ошибка: {e}", "error")
            return None

        self.logger.log("Анализ структуры...", "info")
        analyzer = ModAnalyzer(extract_path)
        structure = analyzer.analyze()

        self.logger.log(f"Тип мода: {structure['type'].value}", "success")

        mapped_files = []
        mod_root = extract_path
        analysis_root = structure['root_path'] or mod_root
        implicit_buses = structure.get('implicit_buses', [])

        for root, dirs, files in os.walk(mod_root):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(mod_root)

                target_path = None
                status = "unmapped"

                # ЛОГИКА 1: HOF файлы всегда отдельно
                if file.lower().endswith('.hof'):
                    status = "hof"
                    target_path = "Хранилище HOF"  # Просто метка для UI
                    mapped_files.append({
                        "source": str(rel_path),
                        "target": target_path,
                        "status": status
                    })
                    continue  # Переходим к следующему файлу

                # ЛОГИКА 2: Обычные файлы
                try:
                    path_from_root = full_path.relative_to(analysis_root)
                    top_folder = path_from_root.parts[0] if path_from_root.parts else ""

                    if top_folder.lower() in ModAnalyzer.OMSI_ROOT_FOLDERS:
                        target_path = str(path_from_root)
                        status = "mapped"

                    elif top_folder in implicit_buses:
                        target_path = str(Path("Vehicles") / path_from_root)
                        status = "mapped"

                    elif structure.get('is_flat_bus'):
                        target_path = str(Path("Vehicles") / archive_path.stem / path_from_root)
                        status = "mapped"
                    else:
                        # В Addons
                        addon_subfolder = archive_path.stem
                        target_path = str(Path("Addons") / addon_subfolder / path_from_root)
                        status = "addon"

                except ValueError:
                    # Файл вне корня -> Addons
                    addon_subfolder = archive_path.stem
                    target_path = str(Path("Addons") / addon_subfolder / rel_path)
                    status = "addon"

                mapped_files.append({
                    "source": str(rel_path),
                    "target": target_path,
                    "status": status
                })

        # Подготовка данных для JS
        structure_js = structure.copy()
        structure_js['type'] = structure['type'].value
        if structure_js.get('root_path'):
            structure_js['root_path'] = str(structure_js['root_path'])
        structure_js['implicit_buses'] = list(structure_js['implicit_buses'])

        return {
            "temp_id": str(extract_path),
            "mod_name": archive_path.stem,
            "type": structure['type'].value,
            "mapped_files": mapped_files,
            "unmapped_files": [],
            "hof_files": structure['hof_files'],
            "structure_data": structure_js
        }

    def step2_confirm_import(self, preview_data):
        extract_path = Path(preview_data['temp_id'])
        mod_name = preview_data['mod_name']

        self.logger.log("Регистрация мода в базе...", "info")

        new_mod = Mod(
            name=mod_name,
            mod_type=ModType(preview_data['type']),
            storage_path=str(extract_path),
            is_enabled=False
        )
        self.session.add(new_mod)
        self.session.flush()

        # Создаем специальную папку для HOF внутри мода
        hof_storage_dir = extract_path / "_hofs"
        hof_storage_dir.mkdir(exist_ok=True)

        count = 0
        for file_info in preview_data['mapped_files']:
            source_path = file_info['source']
            is_hof = file_info['status'] == 'hof'
            target_game_path = file_info['target']

            # Если это HOF, мы его ПЕРЕМЕЩАЕМ в отдельную папку и обнуляем target_game_path
            final_source_rel_path = source_path

            if is_hof:
                target_game_path = None  # Не устанавливать в игру автоматически

                # Физическое перемещение
                original_full_path = extract_path / source_path
                filename = original_full_path.name

                # Защита от дубликатов имен хофов в одном моде
                new_hof_path = hof_storage_dir / filename
                if new_hof_path.exists():
                    timestamp = int(time.time())
                    new_hof_path = hof_storage_dir / f"{original_full_path.stem}_{timestamp}{original_full_path.suffix}"

                try:
                    # Перемещаем файл
                    shutil.move(str(original_full_path), str(new_hof_path))
                    # Обновляем путь источника относительно корня мода
                    final_source_rel_path = str(new_hof_path.relative_to(extract_path))
                except Exception as e:
                    self.logger.log(f"Не удалось переместить HOF {filename}: {e}", "warning")

            # Запись в БД
            db_file = ModFile(
                mod_id=new_mod.id,
                source_rel_path=final_source_rel_path,
                target_game_path=target_game_path,
                is_hof=is_hof,
                file_hash="pending"
            )
            self.session.add(db_file)

            # Если HOF - добавляем в специальную таблицу
            if is_hof:
                hof_entry = HofFile(
                    mod_id=new_mod.id,
                    filename=os.path.basename(final_source_rel_path),
                    full_source_path=str(extract_path / final_source_rel_path),
                    description="Извлечен в HOF хранилище"
                )
                self.session.add(hof_entry)

            count += 1

        self.session.commit()

        # Очистка пустых папок после перемещения HOF
        self._remove_empty_folders(extract_path)

        self.logger.log(f"Мод сохранен! Обработано файлов: {count}", "success")
        return True

    def _remove_empty_folders(self, path):
        """Рекурсивно удаляет пустые папки (нужно после переноса HOFов)"""
        for root, dirs, files in os.walk(path, topdown=False):
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except OSError:
                    pass  # Папка не пуста

    def cancel_import(self, temp_path):
        path = Path(temp_path)
        if path.exists():
            shutil.rmtree(path)
            self.logger.log("Отмена. Временные файлы удалены.", "info")