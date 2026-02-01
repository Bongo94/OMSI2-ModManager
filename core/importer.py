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
        target_path_str = str(target_path)  # Библиотеки любят строки, а не Path объекты

        self.logger.log(f"Распаковка {ext} (Режим Turbo)...", "info")
        # Ставим фейковый прогресс, чтобы юзер понимал, что процесс идет
        self._progress_callback("Распаковка архива...", 50, 100)

        try:
            if ext == '.zip':
                # ZIP: extractall работает быстрее циклов
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    zf.extractall(target_path_str)

            elif ext == '.7z':
                # 7Z: extractall обязателен для Solid архивов и работает быстрее
                # py7zr - это чистый Python, поэтому он все равно медленнее WinRAR/7Zip,
                # но это самый быстрый способ без внешних .exe
                with py7zr.SevenZipFile(archive_path, mode='r') as z:
                    z.extractall(path=target_path_str)

            elif ext == '.rar':
                # RAR: Критически важно использовать extractall!
                # Раньше мы вызывали UnRAR.exe для каждого файла (медленно).
                # Теперь мы вызываем его 1 раз на весь архив.
                if not os.path.exists(rarfile.UNRAR_TOOL):
                    raise FileNotFoundError(f"Не найден {rarfile.UNRAR_TOOL}!")

                with rarfile.RarFile(archive_path) as rf:
                    rf.extractall(target_path_str)
            else:
                raise Exception(f"Неподдерживаемый формат: {ext}")

            # Завершили
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
        analysis_root = structure['root_path']
        implicit_buses = structure.get('implicit_buses', [])

        # Если корень не найден, считаем корнем саму папку распаковки, но все пойдет в Addons
        if not analysis_root:
            analysis_root = mod_root

        for root, dirs, files in os.walk(mod_root):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(mod_root)

                target_path = None
                status = "unmapped"

                # Пробуем определить путь относительно найденного "корня игры" внутри мода
                try:
                    # Путь файла относительно определенного корня (например Fonts/arial.ttf)
                    path_from_root = full_path.relative_to(analysis_root)

                    # Первый компонент пути (например 'Fonts' или '1_VOLGABUS')
                    top_folder = path_from_root.parts[0] if path_from_root.parts else ""

                    # ЛОГИКА РАСПРЕДЕЛЕНИЯ

                    # 1. Если это стандартная папка OMSI (Fonts, Vehicles, Maps...)
                    if top_folder.lower() in ModAnalyzer.OMSI_ROOT_FOLDERS:
                        target_path = str(path_from_root)
                        status = "mapped"

                    # 2. Если это "Скрытый автобус" (папка с автобусом, лежащая в корне)
                    elif top_folder in implicit_buses:
                        # Добавляем Vehicles к пути
                        target_path = str(Path("Vehicles") / path_from_root)
                        status = "mapped"

                    # 3. Особый случай для "Голого автобуса" (когда весь архив - это одна папка автобуса)
                    elif structure.get('is_flat_bus'):
                        target_path = str(Path("Vehicles") / archive_path.stem / path_from_root)
                        status = "mapped"

                    # 4. Все остальное (readme, картинки, левые папки) -> В Addons
                    else:
                        # Используем имя мода для папки в Addons
                        addon_subfolder = archive_path.stem
                        target_path = str(Path("Addons") / addon_subfolder / path_from_root)
                        status = "addon"  # Специальный статус, чтобы подсветить в UI

                except ValueError:
                    # Файл находится "выше" корня (редкий случай, но все же кинем в Addons)
                    addon_subfolder = archive_path.stem
                    target_path = str(Path("Addons") / addon_subfolder / rel_path)
                    status = "addon"

                mapped_files.append({
                    "source": str(rel_path),
                    "target": target_path,
                    "status": status
                })

        # Подготовка данных для JS (удаляем Path объекты)
        structure_js = structure.copy()
        structure_js['type'] = structure['type'].value
        if structure_js.get('root_path'):
            structure_js['root_path'] = str(structure_js['root_path'])
        structure_js['implicit_buses'] = list(structure_js['implicit_buses'])

        return {
            "temp_id": str(extract_path),
            "mod_name": archive_path.stem,
            "type": structure['type'].value,
            "mapped_files": mapped_files,  # Теперь тут ВСЕ файлы
            "unmapped_files": [],  # Этот список теперь всегда пуст, т.к. всё уходит в Addons
            "hof_files": structure['hof_files'],
            "structure_data": structure_js
        }

    def step2_confirm_import(self, preview_data):
        """Сохраняет мод в БД."""
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
        self.session.flush()  # Получаем ID

        # Берем маппинг прямо из preview_data, который прислал фронтенд (или пересчитываем)
        # Надежнее взять то, что мы сгенерировали в step1, но переданное обратно
        # В данном коде мы просто пройдемся по mapped_files из JSON

        count = 0
        for file_info in preview_data['mapped_files']:
            is_hof = file_info['source'].lower().endswith('.hof')

            db_file = ModFile(
                mod_id=new_mod.id,
                source_rel_path=file_info['source'],
                target_game_path=file_info['target'],  # Путь уже с Addons или Vehicles
                is_hof=is_hof,
                file_hash="pending"
            )
            self.session.add(db_file)

            if is_hof:
                # Определяем полный путь для HOF
                full_source = extract_path / file_info['source']
                hof_entry = HofFile(
                    mod_id=new_mod.id,
                    filename=os.path.basename(file_info['source']),
                    full_source_path=str(full_source),
                    description="Найден при установке"
                )
                self.session.add(hof_entry)
            count += 1

        self.session.commit()
        self.logger.log(f"Мод сохранен! Файлов: {count}", "success")
        return True

    def cancel_import(self, temp_path):
        path = Path(temp_path)
        if path.exists():
            shutil.rmtree(path)
            self.logger.log("Отмена. Временные файлы удалены.", "info")
