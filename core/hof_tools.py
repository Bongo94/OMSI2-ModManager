import os
import shutil
import hashlib
from pathlib import Path

from sqlalchemy import func

from core.database import HofFile, HofInstall, Mod


class HofTools:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger
        self.game_root = Path(self.config.game_path)
        self.vehicles_path = self.game_root / "Vehicles"
        self.hof_lib_path = Path(self.config.library_path) / "HOF_Storage"
        self.hof_lib_path.mkdir(parents=True, exist_ok=True)

    def get_library_hofs(self):
        """
        Возвращает список уникальных HOF-файлов с информацией о моде-источнике.
        """
        # 1. Сначала находим максимальные ID для уникальных имен (как в прошлом шаге)
        subquery = (
            self.session.query(
                HofFile.filename,
                func.max(HofFile.id).label('max_id')
            )
            .group_by(HofFile.filename)
            .subquery()
        )

        # 2. Делаем основной запрос с JOIN к таблице Mod
        # Используем outerjoin, так как у HOF, импортированных из игры, mod_id может быть None
        results = (
            self.session.query(HofFile, Mod.name)
            .join(subquery, HofFile.id == subquery.c.max_id)
            .outerjoin(Mod, HofFile.mod_id == Mod.id)
            .order_by(HofFile.filename)
            .all()
        )

        hof_data = []
        for hof, mod_name in results:
            hof_data.append({
                "id": hof.id,
                "name": hof.filename,
                "desc": hof.description,
                "mod_name": mod_name if mod_name else "Импорт / Общее"
            })

        return hof_data

    def scan_existing_game_hofs(self):
        """
        Ищет HOF в игре, которых НЕТ в библиотеке по имени файла.
        """
        found_hofs = {} # name -> full_path

        if not self.vehicles_path.exists():
            return []

        # 1. Сканируем папку Vehicles
        for root, _, files in os.walk(self.vehicles_path):
            for file in files:
                if file.lower().endswith('.hof'):
                    # Оставляем только один экземпляр каждого имени при сканировании
                    if file not in found_hofs:
                        found_hofs[file] = os.path.join(root, file)

        # 2. Получаем все имена, которые УЖЕ есть в базе
        existing_names = {
            h.filename for h in self.session.query(HofFile.filename).all()
        }

        # 3. Оставляем только те, которых в базе нет совсем
        unique_new = []
        for name, path in found_hofs.items():
            if name not in existing_names:
                unique_new.append({"name": name, "path": path})

        return unique_new

    def scan_for_buses(self):
        """
        Сканирует папку Vehicles и возвращает ТОЛЬКО играбельный транспорт.
        """
        buses = []
        if not self.vehicles_path.exists():
            return []

        for entry in sorted(os.scandir(self.vehicles_path), key=lambda e: e.name.lower()):
            if not entry.is_dir(): continue

            bus_folder_path = Path(entry.path)
            # Ищем все файлы конфигурации
            bus_files = list(bus_folder_path.glob("*.bus")) + list(bus_folder_path.glob("*.ovh"))

            if not bus_files: continue

            folder_display_name = None
            is_folder_playable = False

            for b_file in bus_files:
                analysis = self._analyze_is_playable(b_file)

                if analysis['playable']:
                    is_folder_playable = True
                    # Если нашли красивое имя в игровом файле - запоминаем его
                    if analysis['name']:
                        folder_display_name = analysis['name']
                    break  # Если хоть один файл в папке играбельный - папка нам подходит

            # ВАЖНО: Добавляем в список ТОЛЬКО если папка прошла проверку
            if is_folder_playable:
                buses.append({
                    "folder": entry.name,
                    "name": folder_display_name if folder_display_name else entry.name
                })

        return buses

    def _analyze_is_playable(self, file_path):
        """
        Жесткая проверка файла. Трафик не пройдет.
        """
        res = {'playable': False, 'name': None}

        try:
            # Читаем файл (OMSI использует latin-1)
            with open(file_path, 'r', encoding='latin-1', errors='replace') as f:
                content = f.read()

            # 1. Базовая проверка: есть ли вообще имя для меню?
            if "[friendlyname]" not in content:
                return res

            # 2. Проверка на AI-пути (самый частый признак трафика)
            # Если скрипты или звуки лежат в папках AI_Cars / AI_Buses - это мусор
            content_lower = content.lower()
            if "ai_cars" in content_lower or "ai_buses" in content_lower:
                return res

            # 3. Проверка сложности систем (Скрипты)
            # У игрока всегда есть: кабина, двигатель, электроника, коробка передач
            # У трафика обычно 1-3 скрипта (main_AI.osc и пара варлистов)
            has_systems = False
            # Ищем ключевые слова в именах файлов скриптов
            playable_keywords = ['antrieb.osc', 'engine.osc', 'elec.osc', 'cockpit.osc', 'ibis.osc', 'matrix.osc']
            if any(key in content_lower for key in playable_keywords):
                has_systems = True

            # 4. Наличие кабины пассажиров (тег [passengercabin])
            # Почти 100% признак того, что это автобус для игрока
            has_cabin = "[passengercabin]" in content_lower

            # 5. Наличие зеркал/отдельных камер (тег [add_camera_reflexion])
            has_mirrors = "add_camera_reflexion" in content_lower

            # ИТОГОВОЕ РЕШЕНИЕ:
            # Мы считаем транспорт играбельным, если есть friendlyname И (Сложные скрипты ИЛИ Кабина ИЛИ Зеркала)
            if has_systems or has_cabin or has_mirrors:
                res['playable'] = True

                # Попутно вытащим имя для красоты
                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if line.strip().lower() == "[friendlyname]":
                        try:
                            m = lines[i + 1].strip()
                            n = lines[i + 2].strip()
                            if m and not m.startswith('['):
                                res['name'] = f"{m} {n}".strip()
                        except:
                            pass
                        break

            return res

        except:
            return res

    def _parse_bus_info(self, file_path):
        """
        Читает файл и ищет секцию [friendlyname].
        Возвращает dict {'manuf': ..., 'model': ...} или None, если секции нет.
        """
        try:
            # OMSI файлы часто в кодировке latin-1 (или windows-1252), utf-8 редко
            with open(file_path, 'r', encoding='latin-1', errors='replace') as f:
                content = f.read().splitlines()

            for i, line in enumerate(content):
                clean_line = line.strip()

                # Ищем ключевое слово
                if clean_line.lower() == "[friendlyname]":
                    # Секция найдена! Это играбельный автобус.
                    # Следующие строки:
                    # 1. Производитель
                    # 2. Модель
                    # 3. Окраска (нам не нужна)

                    manufacturer = ""
                    model = ""

                    # Пытаемся прочитать следующие непустые строки
                    offset = 1
                    found_lines = []
                    while i + offset < len(content) and len(found_lines) < 2:
                        val = content[i + offset].strip()
                        if val and not val.startswith('[') and not val.startswith(
                                '\t'):  # Игнорируем другие теги или пустые
                            found_lines.append(val)
                        offset += 1

                    if len(found_lines) >= 1: manufacturer = found_lines[0]
                    if len(found_lines) >= 2: model = found_lines[1]

                    return {"manuf": manufacturer, "model": model}

            return None  # Тег не найден -> вероятно трафик или мусор

        except Exception:
            return None

    def scan_existing_game_hofs(self):
        """
        Ищет HOF файлы уже установленные в игре, которых нет в библиотеке.
        Возвращает список уникальных найденных файлов.
        """
        found_hofs = {}  # name -> full_path

        if not self.vehicles_path.exists():
            return []

        self.logger.log("Сканирование папки Vehicles на наличие HOF...", "info")

        for root, _, files in os.walk(self.vehicles_path):
            for file in files:
                if file.lower().endswith('.hof'):
                    # Если файл уже есть в найденных, пропускаем (предполагаем дубликаты одинаковыми по имени)
                    # Можно добавить проверку хеша, но это долго.
                    if file not in found_hofs:
                        found_hofs[file] = os.path.join(root, file)

        # Фильтруем те, что уже есть в БД
        existing_names = {h.filename for h in self.session.query(HofFile).all()}
        unique_new = []

        for name, path in found_hofs.items():
            if name not in existing_names:
                unique_new.append({"name": name, "path": path})

        return unique_new

    def import_game_hofs(self, hof_list):
        """Импортирует выбранные HOF из игры в библиотеку менеджера"""
        imported_count = 0
        for item in hof_list:
            src = Path(item['path'])
            target = self.hof_lib_path / item['name']

            # Если файл с таким именем есть, добавляем таймштамп
            if target.exists():
                continue

            try:
                shutil.copy2(src, target)

                # Создаем запись в БД
                # Пробуем прочитать описание (первая строка файла)
                desc = "Imported from Game"
                try:
                    with open(target, 'r', encoding='latin-1') as f:  # OMSI обычно latin-1
                        line = f.readline().strip()
                        if line and "[name]" not in line:
                            desc = line[:50]
                except:
                    pass

                new_hof = HofFile(
                    filename=item['name'],
                    full_source_path=str(target),  # Абсолютный путь, или относительный к Lib
                    description=desc,
                    mod_id=None  # Это глобальный HOF, не привязан к моду
                )
                self.session.add(new_hof)
                imported_count += 1
            except Exception as e:
                self.logger.log(f"Ошибка импорта {item['name']}: {e}", "error")

        self.session.commit()
        return imported_count

    def install_hofs_to_buses(self, hof_ids, bus_folder_names):
        """
        Копирует выбранные HOF (ids) в выбранные автобусы (names).
        """
        hofs = self.session.query(HofFile).filter(HofFile.id.in_(hof_ids)).all()

        total_ops = len(hofs) * len(bus_folder_names)
        current = 0
        errors = []

        self.logger.log(f"Установка {len(hofs)} HOF в {len(bus_folder_names)} автобусов...", "info")

        for bus_name in bus_folder_names:
            bus_path = self.vehicles_path / bus_name
            if not bus_path.exists(): continue

            for hof in hofs:
                current += 1
                # Источник: Либо в папке мода, либо в HOF_Storage
                # В базе путь может быть absolute или relative. Обработаем это.
                src_candidate = Path(hof.full_source_path)

                # Если путь не абсолютный, пробуем найти относительно библиотеки
                if not src_candidate.is_absolute():
                    # Проверяем в Mods
                    temp = Path(self.config.library_path) / "Mods" / src_candidate
                    if not temp.exists():
                        # Проверяем в HOF_Storage (куда мы импортируем)
                        temp = self.hof_lib_path / hof.filename
                    src_candidate = temp

                if not src_candidate.exists():
                    errors.append(f"Source missing: {hof.filename}")
                    continue

                target = bus_path / hof.filename

                try:
                    shutil.copy2(src_candidate, target)
                    # TODO: Можно записать в HofInstall, если нужна история
                except Exception as e:
                    errors.append(f"Err {bus_name}/{hof.filename}: {e}")

                if current % 10 == 0:
                    self.logger.log(None, "progress", int(current / total_ops * 100))

        self.session.commit()

        if errors:
            return False, f"Завершено с ошибками ({len(errors)})"
        return True, "Все HOF файлы успешно скопированы!"
