import os
import shutil
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

        # Пути к утилитам (должны лежать рядом с main.py или в папке bin)
        base_dir = os.getcwd()
        self.seven_zip_tool = os.path.join(base_dir, "7Zip\\7za.exe")
        self.unrar_tool = os.path.join(base_dir, "UnRAR\\UnRAR.exe")

    def _progress_callback(self, percent, text=None):
        """Отправка прогресса в UI"""
        if text:
            # Логируем текст только если он новый или важный, чтобы не спамить
            pass
        self.logger.log(text, level="progress", progress=percent)

    def _extract_with_7z(self, archive_path, target_path):
        """
        Запускает 7za.exe и парсит вывод для получения прогресса.
        Работает для .7z и .zip
        """
        if not os.path.exists(self.seven_zip_tool):
            raise FileNotFoundError("Не найден 7za.exe! Скачайте 7-Zip Console version.")

        # Команда: x (extract), -o (output), -y (yes to all), -bsp1 (вывод прогресса в stderr)
        cmd = [
            self.seven_zip_tool,
            "x", str(archive_path),
            f"-o{target_path}",
            "-y",
            "-bsp1"
        ]

        # Запускаем процесс
        # ВАЖНО: 7-Zip пишет прогресс в stderr, а не stdout
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,  # Работаем со строками, а не байтами
            creationflags=subprocess.CREATE_NO_WINDOW  # Чтобы не мигало черное окно
        )

        # Читаем вывод посимвольно или кусками, чтобы ловить проценты
        # Регулярка для поиска "12%"
        pattern = re.compile(r"\b(\d+)%")

        while True:
            # Читаем stderr (там прогресс)
            # read(1) может быть медленным, лучше читать небольшими кусками
            chunk = process.stderr.read(32)

            if not chunk and process.poll() is not None:
                break

            if chunk:
                # Ищем проценты в куске текста
                match = pattern.search(chunk)
                if match:
                    percent = int(match.group(1))
                    self._progress_callback(percent, f"Распаковка 7-Zip: {percent}%")

        if process.returncode != 0:
            raise Exception(f"7-Zip завершился с ошибкой (Code {process.returncode})")

    def _extract_with_unrar(self, archive_path, target_path):
        """
        Запускает UnRAR.exe и парсит вывод.
        """
        if not os.path.exists(self.unrar_tool):
            raise FileNotFoundError("Не найден UnRAR.exe!")

        cmd = [
            self.unrar_tool,
            "x", str(archive_path),
            str(target_path) + "\\",  # UnRAR любит слеш в конце пути назначения
            "-y"
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        pattern = re.compile(r"\b(\d+)%")

        # UnRAR пишет в stdout
        while True:
            chunk = process.stdout.read(32)
            if not chunk and process.poll() is not None:
                break

            if chunk:
                match = pattern.search(chunk)
                if match:
                    percent = int(match.group(1))
                    self._progress_callback(percent, f"Распаковка WinRAR: {percent}%")

        if process.returncode != 0:
            # Читаем ошибку из stderr
            err = process.stderr.read()
            raise Exception(f"UnRAR Error: {err}")

    def _extract_archive(self, archive_path, target_path):
        """Главный метод-диспетчер"""
        ext = archive_path.suffix.lower()
        target_path_str = str(target_path)

        self.logger.log(f"Запуск нативной распаковки: {archive_path.name}", "info")

        try:
            if ext in ['.7z', '.zip']:
                self._extract_with_7z(archive_path, target_path_str)
            elif ext == '.rar':
                self._extract_with_unrar(archive_path, target_path_str)
            else:
                # Фоллбэк для всего остального (если вдруг .tar или еще что)
                self.logger.log("Неизвестный формат, пробую 7-Zip...", "warning")
                self._extract_with_7z(archive_path, target_path_str)

            self._progress_callback(100, "Распаковка завершена")

        except Exception as e:
            self.logger.log(f"Критическая ошибка распаковки: {e}", "error")
            raise e

    # --- ОСТАЛЬНОЙ КОД БЕЗ ИЗМЕНЕНИЙ (step1, step2...) ---

    def step1_prepare_preview(self, archive_path):
        # Копируем код из предыдущего ответа, он идеален
        archive_path = Path(archive_path)
        # ... (код step1_prepare_preview из предыдущего сообщения) ...
        # (Если нужно, я могу продублировать его целиком, но там менялся только _extract_archive)

        # ... ТУТ ВЕСЬ КОД step1 ИЗ ПРЕДЫДУЩЕГО СООБЩЕНИЯ ...
        # Чтобы не раздувать ответ, я вставлю только начало и конец,
        # но логика внутри step1 и step2 остается той же, что мы утвердили ранее

        mod_folder_name = f"{archive_path.stem}_{int(datetime.now().timestamp())}"
        extract_path = Path(self.config.library_path) / "Mods" / mod_folder_name

        try:
            self.logger.log("Создание папки...", "info")
            extract_path.mkdir(parents=True, exist_ok=True)
            self._extract_archive(archive_path, extract_path)  # <-- Вызовет новый быстрый метод
        except Exception as e:
            if extract_path.exists(): shutil.rmtree(extract_path)
            self.logger.log(f"Ошибка: {e}", "error")
            return None

        # ... Дальше идет анализ (Analyzer) и формирование JSON ...
        # Копируем логику с HOF и Addons из предыдущего моего ответа
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
                target_path = None
                status = "unmapped"

                if file.lower().endswith('.hof'):
                    status = "hof"
                    target_path = "Хранилище HOF"
                    mapped_files.append({"source": str(rel_path), "target": target_path, "status": status})
                    continue

                try:
                    path_from_root = full_path.relative_to(analysis_root)
                    top_folder = path_from_root.parts[0] if path_from_root.parts else ""

                    if top_folder.lower() in ModAnalyzer.OMSI_ROOT_FOLDERS:
                        target_path = str(path_from_root);
                        status = "mapped"
                    elif top_folder in implicit_buses:
                        target_path = str(Path("Vehicles") / path_from_root);
                        status = "mapped"
                    elif structure.get('is_flat_bus'):
                        target_path = str(Path("Vehicles") / archive_path.stem / path_from_root);
                        status = "mapped"
                    else:
                        target_path = str(Path("Addons") / archive_path.stem / path_from_root);
                        status = "addon"
                except ValueError:
                    target_path = str(Path("Addons") / archive_path.stem / rel_path);
                    status = "addon"

                mapped_files.append({"source": str(rel_path), "target": target_path, "status": status})

        structure_js = structure.copy()
        structure_js['type'] = structure['type'].value
        if structure_js.get('root_path'): structure_js['root_path'] = str(structure_js['root_path'])
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
        # ... Код step2 берем целиком из предыдущего ответа (с перемещением HOF) ...
        # Он не зависит от распаковки, он работает уже с распакованными файлами
        extract_path = Path(preview_data['temp_id'])
        mod_name = preview_data['mod_name']

        self.logger.log("Запись в БД...", "info")
        new_mod = Mod(name=mod_name, mod_type=ModType(preview_data['type']), storage_path=str(extract_path),
                      is_enabled=False)
        self.session.add(new_mod)
        self.session.flush()

        hof_storage_dir = extract_path / "_hofs"
        hof_storage_dir.mkdir(exist_ok=True)

        count = 0
        for file_info in preview_data['mapped_files']:
            is_hof = file_info['status'] == 'hof'
            final_source = file_info['source']
            target = file_info['target'] if not is_hof else None

            if is_hof:
                full_src = extract_path / final_source
                new_path = hof_storage_dir / full_src.name
                if new_path.exists(): new_path = hof_storage_dir / f"{full_src.stem}_{int(time.time())}{full_src.suffix}"
                try:
                    shutil.move(str(full_src), str(new_path))
                    final_source = str(new_path.relative_to(extract_path))
                except:
                    pass

                self.session.add(HofFile(mod_id=new_mod.id, filename=new_path.name,
                                         full_source_path=str(extract_path / final_source), description="Auto"))

            self.session.add(
                ModFile(mod_id=new_mod.id, source_rel_path=final_source, target_game_path=target, is_hof=is_hof,
                        file_hash="pending"))
            count += 1

        self.session.commit()
        self._remove_empty_folders(extract_path)
        self.logger.log(f"Успех! Файлов: {count}", "success")
        return True

    def _remove_empty_folders(self, path):
        for root, dirs, files in os.walk(path, topdown=False):
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except:
                    pass

    def cancel_import(self, temp_path):
        if Path(temp_path).exists(): shutil.rmtree(temp_path)