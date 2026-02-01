import os
import shutil
import zipfile
import py7zr
import rarfile
import time
import hashlib
from datetime import datetime
from pathlib import Path
from core.database import Mod, ModFile, HofFile, ModType
from core.analyzer import ModAnalyzer

# Указываем rarfile, где искать UnRAR.exe (если он лежит рядом с main.py)
rarfile.UNRAR_TOOL = "UnRAR.exe"


class ModImporter:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger

    def _progress_callback(self, item_name, current, total):
        """Callback для отправки прогресса в UI"""
        percent = int((current / total) * 100) if total > 0 else 0
        if current % 10 == 0 or current == total:
            self.logger.log(f"{current}/{total}: {item_name}", level="progress", progress=percent)
            time.sleep(0.001)

    def _extract_archive(self, archive_path, target_path):
        """Распаковывает архив и сообщает о прогрессе."""
        ext = archive_path.suffix.lower()

        if ext == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as zf:
                members = zf.infolist()
                total_files = len(members)
                for i, member in enumerate(members):
                    zf.extract(member, target_path)
                    self._progress_callback(member.filename, i + 1, total_files)
        elif ext == '.7z':
            with py7zr.SevenZipFile(archive_path, mode='r') as z:
                all_files = z.getnames()
                total_files = len(all_files)
                for i, filename in enumerate(all_files):
                    z.extract(targets=[filename], path=target_path)
                    self._progress_callback(filename, i + 1, total_files)
        elif ext == '.rar':
            if not os.path.exists(rarfile.UNRAR_TOOL):
                raise FileNotFoundError(f"Не найден {rarfile.UNRAR_TOOL}! Поместите его рядом с main.py.")
            with rarfile.RarFile(archive_path) as rf:
                members = rf.infolist()
                total_files = sum(1 for m in members if not m.isdir())
                current_file = 0
                for member in members:
                    if not member.isdir():
                        rf.extract(member, str(target_path))
                        current_file += 1
                        self._progress_callback(member.filename, current_file, total_files)
        else:
            raise Exception(f"Неподдерживаемый формат архива: {ext}")

    def step1_prepare_preview(self, archive_path):
        archive_path = Path(archive_path)
        self.logger.log(f"Начинаю обработку архива: {archive_path.name}")

        mod_folder_name = f"{archive_path.stem}_{int(datetime.now().timestamp())}"
        extract_path = Path(self.config.library_path) / "Mods" / mod_folder_name

        try:
            self.logger.log("Создание временной папки...", "info")
            extract_path.mkdir(parents=True, exist_ok=True)
            self._extract_archive(archive_path, extract_path)
            self.logger.log("Распаковка завершена.", "success")
        except Exception as e:
            if extract_path.exists(): shutil.rmtree(extract_path)
            self.logger.log(f"Ошибка: {e}", "error")
            return None

        self.logger.log("Анализ структуры...", "info")
        analyzer = ModAnalyzer(extract_path)
        structure = analyzer.analyze()
        self.logger.log(f"Определен тип мода: {structure['type'].value}", "success")
        if not structure['root_path']:
            self.logger.log(
                "Внимание: Не удалось автоматически определить 'корень' мода. Файлы могут быть не распределены.",
                "warning")

        mapped_files, unmapped_files = [], []
        mod_root = extract_path
        analysis_root = structure['root_path']

        for root, _, files in os.walk(mod_root):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(mod_root)

                target_path, status = None, "unmapped"

                if analysis_root:
                    try:
                        path_from_root = full_path.relative_to(analysis_root)
                        target_path = str(path_from_root)
                        status = "mapped"
                        if structure.get('is_flat_bus'):
                            target_path = f"Vehicles\\{archive_path.stem}\\{path_from_root}"
                    except ValueError:
                        status = "unmapped"

                file_info = {"source": str(rel_path), "target": target_path or "???", "status": status}
                if status == "mapped":
                    mapped_files.append(file_info)
                else:
                    unmapped_files.append(file_info)

        if len(unmapped_files) > 0:
            self.logger.log(f"Найдено {len(unmapped_files)} файлов без явного назначения", "warning")

        # --- ИСПРАВЛЕНИЕ ОШИБКИ JSON ---
        structure_for_js = structure.copy()
        structure_for_js['type'] = structure['type'].value

        # Path объект (root_path) нельзя сериализовать в JSON, преобразуем в строку
        if structure_for_js.get('root_path'):
            structure_for_js['root_path'] = str(structure_for_js['root_path'])
        # -------------------------------

        return {
            "temp_id": str(extract_path),
            "mod_name": archive_path.stem,
            "type": structure['type'].value,
            "mapped_files": mapped_files,
            "unmapped_files": unmapped_files,
            "hof_files": structure['hof_files'],
            "structure_data": structure_for_js
        }

    def _register_files(self, mod, structure):
        """Проходит по файлам и записывает их в БД"""
        mod_root = Path(mod.storage_path)
        analysis_root = structure.get('root_path')
        if analysis_root:
            analysis_root = Path(analysis_root)  # Убедимся, что это Path объект

        for root, _, files in os.walk(mod_root):
            for file in files:
                full_path = Path(root) / file
                source_rel_path = full_path.relative_to(mod_root)

                target_game_path = None
                if analysis_root:
                    try:
                        path_from_analysis_root = full_path.relative_to(analysis_root)
                        target_game_path = str(path_from_analysis_root)

                        if structure.get('is_flat_bus'):
                            target_game_path = str(Path('Vehicles') / mod.name / path_from_analysis_root)
                    except ValueError:
                        pass

                is_hof = file.lower().endswith('.hof')

                db_file = ModFile(
                    mod_id=mod.id,
                    source_rel_path=str(source_rel_path),
                    target_game_path=target_game_path,
                    is_hof=is_hof,
                    file_hash="pending"
                )
                self.session.add(db_file)

                if is_hof and target_game_path:
                    hof_entry = HofFile(
                        mod_id=mod.id,
                        filename=file,
                        full_source_path=str(full_path),
                        description="Автоматически найден"
                    )
                    self.session.add(hof_entry)

    def step2_confirm_import(self, preview_data):
        extract_path = Path(preview_data['temp_id'])
        mod_name = preview_data['mod_name']
        structure = preview_data['structure_data']

        # Конвертируем обратно из строки в Path-объект, если он есть (т.к. мы превратили его в строку в step1)
        if structure.get('root_path'):
            structure['root_path'] = Path(structure['root_path'])

        self.logger.log("Сохранение в базу данных...", "info")

        new_mod = Mod(
            name=mod_name,
            mod_type=ModType(preview_data['type']),
            storage_path=str(extract_path),
            is_enabled=False
        )
        self.session.add(new_mod)
        self.session.flush()

        self._register_files(new_mod, structure)

        self.session.commit()
        self.logger.log(f"Мод '{mod_name}' успешно добавлен в библиотеку!", "success")
        return True

    def cancel_import(self, temp_path):
        path = Path(temp_path)
        if path.exists():
            shutil.rmtree(path)
            self.logger.log("Импорт отменен. Временные файлы удалены.", "info")