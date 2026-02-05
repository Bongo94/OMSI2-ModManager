import os
import shutil
import sys
import time
import subprocess
import re
from datetime import datetime
from pathlib import Path
from core.database import Mod, ModFile, HofFile, ModType
from core.analyzer import ModAnalyzer


class ModImporter:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger

        # Логика определения пути (дублируем, чтобы не делать лишних импортов)
        if getattr(sys, 'frozen', False):
            # Если запущено как EXE
            base_dir = sys._MEIPASS
        else:
            # Если запущено как скрипт
            base_dir = os.path.abspath(".")

        # Указываем путь к exe внутри папки 7Zip
        self.seven_zip_tool = os.path.join(base_dir, "7Zip", "7z.exe")

    def _progress_callback(self, percent, text=None):
        self.logger.log(text, level="progress", progress=percent)

    def _extract_archive(self, archive_path, target_path):
        """
        Универсальная сверхбыстрая распаковка через 7z.exe для ZIP, 7Z и RAR.
        """
        if not os.path.exists(self.seven_zip_tool):
            self.logger.log("Ошибка: Не найден 7z.exe и 7z.dll в корне приложения!", "error")
            raise FileNotFoundError("7z.exe missing")

        target_path_str = str(target_path)
        ext = archive_path.suffix.lower()

        self.logger.log(f"Распаковка {ext} через 7-Zip Engine...", "info")

        # Команды 7z:
        # x : извлечь с сохранением путей
        # -o : путь назначения
        # -y : отвечать "да" на все вопросы
        # -bsp1 : выводить прогресс в поток (важно для перехвата процентов)
        cmd = [
            self.seven_zip_tool,
            "x", str(archive_path),
            f"-o{target_path_str}",
            "-y",
            "-bsp1"
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        # Регулярка ловит " 45%"
        pattern = re.compile(r"(\d+)%")

        while True:
            # 7z выводит прогресс в stdout при использовании -bsp1
            char = process.stdout.read(8)
            if not char and process.poll() is not None:
                break

            if char:
                match = pattern.search(char)
                if match:
                    percent = int(match.group(1))
                    self._progress_callback(percent, f"Распаковка: {percent}%")

        if process.returncode != 0:
            err_msg = process.stderr.read()
            self.logger.log(f"7-Zip Error: {err_msg}", "error")
            raise Exception("Extraction failed")

        self._progress_callback(100, "Распаковка завершена")

    def step1_prepare_preview(self, archive_path):
        archive_path = Path(archive_path)
        mod_folder_name = f"{archive_path.stem}_{int(datetime.now().timestamp())}"
        extract_path = Path(self.config.library_path) / "Mods" / mod_folder_name

        try:
            extract_path.mkdir(parents=True, exist_ok=True)
            # Вызываем нашу новую универсальную распаковку
            self._extract_archive(archive_path, extract_path)
        except Exception as e:
            if extract_path.exists(): shutil.rmtree(extract_path)
            return None

        # --- Дальше идет анализ (analyzer.py), который мы уже довели до ума ---
        self.logger.log("Анализ структуры...", "info")
        analyzer = ModAnalyzer(extract_path)
        structure = analyzer.analyze()

        mapped_files = []
        mod_root = extract_path
        analysis_root = structure['root_path'] or mod_root
        implicit_buses = structure.get('implicit_buses', [])

        for root, _, files in os.walk(mod_root):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(mod_root)

                # Логика HOF (как договорились — отдельно)
                if file.lower().endswith('.hof'):
                    mapped_files.append({"source": str(rel_path), "target": "Хранилище HOF", "status": "hof"})
                    continue

                try:
                    path_from_root = full_path.relative_to(analysis_root)
                    top_folder = path_from_root.parts[0] if path_from_root.parts else ""

                    if top_folder.lower() in ModAnalyzer.OMSI_ROOT_FOLDERS:
                        target = str(path_from_root);
                        status = "mapped"
                    elif top_folder in implicit_buses:
                        target = str(Path("Vehicles") / path_from_root);
                        status = "mapped"
                    elif structure.get('is_flat_bus'):
                        target = str(Path("Vehicles") / archive_path.stem / path_from_root);
                        status = "mapped"
                    else:
                        target = str(Path("Addons") / archive_path.stem / path_from_root);
                        status = "addon"
                except ValueError:
                    target = str(Path("Addons") / archive_path.stem / rel_path);
                    status = "addon"

                mapped_files.append({"source": str(rel_path), "target": target, "status": status})

        # Конвертация для JS
        structure_js = structure.copy()
        structure_js['type'] = structure['type'].value
        if structure_js.get('root_path'): structure_js['root_path'] = str(structure_js['root_path'])
        structure_js['implicit_buses'] = list(structure_js['implicit_buses'])

        return {
            "temp_id": str(extract_path),
            "mod_name": archive_path.stem,
            "type": structure['type'].value,
            "mapped_files": mapped_files,
            "structure_data": structure_js
        }

    # step2_confirm_import остается таким же (с перемещением HOF файлов)
    def step2_confirm_import(self, preview_data):
        extract_path = Path(preview_data['temp_id'])
        mod_name = preview_data['mod_name']
        self.logger.log("Запись в БД и сортировка HOF...", "info")

        new_mod = Mod(name=mod_name, mod_type=ModType(preview_data['type']), storage_path=str(extract_path),
                      is_enabled=False)
        self.session.add(new_mod)
        self.session.flush()

        hof_storage_dir = extract_path / "_hofs"
        hof_storage_dir.mkdir(exist_ok=True)

        for file_info in preview_data['mapped_files']:
            is_hof = file_info['status'] == 'hof'
            final_source = file_info['source']
            target = file_info['target'] if not is_hof else None

            if is_hof:
                full_src = extract_path / final_source
                new_path = hof_storage_dir / full_src.name
                if new_path.exists():
                    new_path = hof_storage_dir / f"{full_src.stem}_{int(time.time())}{full_src.suffix}"
                try:
                    shutil.move(str(full_src), str(new_path))
                    final_source = str(new_path.relative_to(extract_path))
                except:
                    pass
                self.session.add(HofFile(mod_id=new_mod.id, filename=new_path.name,
                                         full_source_path=str(extract_path / final_source),
                                         description="Auto-extracted"))

            self.session.add(
                ModFile(mod_id=new_mod.id, source_rel_path=final_source, target_game_path=target, is_hof=is_hof,
                        file_hash="pending"))

        self.session.commit()
        for root, dirs, files in os.walk(extract_path, topdown=False):
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except:
                    pass
        return True

    def cancel_import(self, temp_path):
        if Path(temp_path).exists(): shutil.rmtree(temp_path)