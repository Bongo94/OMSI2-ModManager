import os
import shutil
import zipfile
import py7zr
import rarfile
import time
from pathlib import Path
from datetime import datetime
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
        percent = int((current / total) * 100)
        self.logger.log(f"Распаковка: {item_name}", "progress", percent)
        # Небольшая задержка, чтобы UI успевал обновляться
        time.sleep(0.01)

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

                # py7zr не имеет удобного file-by-file extract, но мы можем использовать callback
                # Создаем обертку для нашего стандартного callback
                def py7zr_callback(filename, extracted_size, total_size):
                    # К сожалению, py7zr не дает номера файла, поэтому прогресс будет по байтам
                    # Для простоты будем считать по файлам, хоть это и не идеально точно
                    try:
                        current_index = all_files.index(filename)
                        self._progress_callback(filename, current_index + 1, total_files)
                    except ValueError:
                        pass  # Пропускаем папки

                z.extractall(path=target_path, callback=py7zr_callback)

        elif ext == '.rar':
            if not os.path.exists(rarfile.UNRAR_TOOL):
                raise FileNotFoundError(f"Не найден {rarfile.UNRAR_TOOL}! Поместите его рядом с main.py.")
            with rarfile.RarFile(archive_path) as rf:
                members = rf.infolist()
                total_files = len(members)
                for i, member in enumerate(members):
                    rf.extract(member, str(target_path))
                    self._progress_callback(member.filename, i + 1, total_files)
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
            self.logger.log("Распаковка файлов...", "info")
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
            self.logger.log("Внимание: Не удалось автоматически определить 'корень' мода.", "warning")

        mapped_files, unmapped_files, hof_files = [], [], []
        mod_root = extract_path
        analysis_root = structure['root_path']

        for root, _, files in os.walk(mod_root):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(mod_root)

                target_path, status = None, "unmapped"

                if file.lower().endswith('.hof'):
                    hof_files.append(str(rel_path))

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
            self.logger.log(f"Найдено {len(unmapped_files)} файлов без явного назначения.", "warning")

        return {
            "temp_id": str(extract_path),
            "mod_name": archive_path.stem,
            "type": structure['type'].value,
            "mapped_files": mapped_files,
            "unmapped_files": unmapped_files,
            "hof_files": hof_files,
            "structure_data": structure
        }

    # _register_files остается без изменений, но убедись, что он у тебя есть
    def _register_files(self, mod, structure):
        """Проходит по файлам и записывает их в БД"""
        mod_root = Path(mod.storage_path)
        analysis_root = structure.get('root_path')

        for root, dirs, files in os.walk(mod_root):
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
                        pass  # Файл вне корня, target_game_path остается None

                is_hof = file.lower().endswith('.hof')

                db_file = ModFile(
                    mod_id=mod.id,
                    source_rel_path=str(source_rel_path),
                    target_game_path=target_game_path,
                    is_hof=is_hof,
                    file_hash="pending"
                )
                self.session.add(db_file)

                if is_hof:
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

        # Т.к. pywebview не может сериализовать Enum, конвертируем строку обратно
        mod_type_str = preview_data['type']
        structure['type'] = ModType(mod_type_str)

        self.logger.log("Сохранение в базу данных...", "info")

        new_mod = Mod(
            name=mod_name,
            mod_type=structure['type'],
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