import os
import shutil
import hashlib
from pathlib import Path
from sqlalchemy import func
from core.database import HofFile, HofInstall, Mod
from core.installer import ModInstaller


class HofTools:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger

        # Защита от отсутствия пути при первом запуске
        if self.config.game_path:
            self.game_root = Path(self.config.game_path)
            self.vehicles_path = self.game_root / "Vehicles"
        else:
            self.game_root = None
            self.vehicles_path = None

        self.installer = ModInstaller(config_manager, logger)

        self.hof_lib_path = Path(self.config.library_path) / "HOF_Storage"
        self.hof_lib_path.mkdir(parents=True, exist_ok=True)

    def get_library_hofs(self):
        """Возвращает список уникальных HOF-файлов с информацией о моде-источнике."""
        # 1. Находим максимальные ID для уникальных имен
        subquery = (
            self.session.query(
                HofFile.filename,
                func.max(HofFile.id).label('max_id')
            )
            .group_by(HofFile.filename)
            .subquery()
        )

        # 2. Основной запрос
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

    def scan_for_buses(self):
        """Сканирует папку Vehicles и возвращает ТОЛЬКО играбельный транспорт."""
        buses = []
        if not self.vehicles_path or not self.vehicles_path.exists():
            return []

        try:
            entries = sorted(os.scandir(self.vehicles_path), key=lambda e: e.name.lower())
        except OSError:
            return []

        for entry in entries:
            if not entry.is_dir(): continue

            bus_folder_path = Path(entry.path)
            # Ищем файлы конфигурации
            bus_files = list(bus_folder_path.glob("*.bus")) + list(bus_folder_path.glob("*.ovh"))

            if not bus_files: continue

            folder_display_name = None
            is_folder_playable = False
            vehicle_type = 'bus'  # bus or car

            for b_file in bus_files:
                analysis = self._analyze_is_playable(b_file)

                if analysis['playable']:
                    is_folder_playable = True
                    if analysis['name']:
                        folder_display_name = analysis['name']
                    if b_file.suffix == '.ovh':
                        vehicle_type = 'car'
                    break

            if is_folder_playable:
                buses.append({
                    "folder": entry.name,
                    "name": folder_display_name if folder_display_name else entry.name,
                    "type": vehicle_type
                })

        return buses

    def _analyze_is_playable(self, file_path):
        """Жесткая проверка файла. Трафик не пройдет."""
        res = {'playable': False, 'name': None}
        try:
            with open(file_path, 'r', encoding='latin-1', errors='replace') as f:
                content = f.read()

            if "[friendlyname]" not in content:
                return res

            content_lower = content.lower()
            if "ai_cars" in content_lower or "ai_buses" in content_lower:
                return res

            has_systems = False
            playable_keywords = ['antrieb.osc', 'engine.osc', 'elec.osc', 'cockpit.osc', 'ibis.osc', 'matrix.osc']
            if any(key in content_lower for key in playable_keywords):
                has_systems = True

            has_cabin = "[passengercabin]" in content_lower
            has_mirrors = "add_camera_reflexion" in content_lower

            if has_systems or has_cabin or has_mirrors:
                res['playable'] = True
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

    def scan_existing_game_hofs(self):
        """Ищет HOF файлы уже установленные в игре, которых нет в библиотеке."""
        found_hofs = {}
        if not self.vehicles_path or not self.vehicles_path.exists():
            return []

        self.logger.log("Сканирование папки Vehicles на наличие HOF...", "info")

        for root, _, files in os.walk(self.vehicles_path):
            for file in files:
                if file.lower().endswith('.hof'):
                    if file not in found_hofs:
                        found_hofs[file] = os.path.join(root, file)

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

            if target.exists():
                continue

            try:
                shutil.copy2(src, target)
                desc = "Imported from Game"
                try:
                    with open(target, 'r', encoding='latin-1') as f:
                        line = f.readline().strip()
                        if line and "[name]" not in line:
                            desc = line[:50]
                except:
                    pass

                new_hof = HofFile(
                    filename=item['name'],
                    full_source_path=str(target),
                    description=desc,
                    mod_id=None
                )
                self.session.add(new_hof)
                imported_count += 1
            except Exception as e:
                self.logger.log(f"Ошибка импорта {item['name']}: {e}", "error")

        self.session.commit()
        return imported_count

    def install_hofs_to_buses(self, hof_ids, bus_folder_names):
        """Устанавливает HOF файлы через СИМЛИНКИ."""
        hofs = self.session.query(HofFile).filter(HofFile.id.in_(hof_ids)).all()
        if not hofs: return False, "No HOFs selected"

        total_ops = len(hofs) * len(bus_folder_names)
        current = 0
        errors = []

        self.logger.log(f"Инъекция {len(hofs)} HOF в {len(bus_folder_names)} автобусов...", "info")

        for bus_name in bus_folder_names:
            bus_path_rel = Path("Vehicles") / bus_name

            # Полный путь к папке автобуса
            bus_full_path = self.game_root / bus_path_rel
            if not bus_full_path.exists():
                continue

            for hof in hofs:
                current += 1

                # Поиск исходника
                src_candidate = Path(hof.full_source_path)
                if not src_candidate.is_absolute():
                    temp = self.hof_lib_path / hof.filename
                    if temp.exists():
                        src_candidate = temp
                    else:
                        temp = Path(self.config.library_path) / "Mods" / src_candidate
                        src_candidate = temp

                if not src_candidate.exists():
                    errors.append(f"Missing source: {hof.filename}")
                    continue

                target_rel_path = bus_path_rel / hof.filename

                try:
                    backup, _ = self.installer._install_file_physically(target_rel_path, src_candidate)

                    install_record = HofInstall(
                        hof_file_id=hof.id,
                        bus_folder_name=bus_name,
                        game_rel_path=str(target_rel_path),
                        backup_path=backup
                    )
                    self.session.add(install_record)

                except Exception as e:
                    errors.append(f"Err {bus_name}/{hof.filename}: {e}")

                if current % 5 == 0:
                    self.logger.log(None, "progress", int(current / total_ops * 100))

        self.session.commit()

        if errors:
            return False, f"Завершено с ошибками ({len(errors)})"
        return True, "HOF файлы успешно привязаны (симлинки)!"

    def uninstall_all_hofs(self):
        """Удаляет ВСЕ установленные HOF файлы и восстанавливает оригиналы."""
        installs = self.session.query(HofInstall).all()
        if not installs:
            return True, "Нет установленных HOF файлов."

        self.logger.log(f"Удаление {len(installs)} HOF файлов...", "info")

        count = 0
        for record in installs:
            try:
                target_full = self.game_root / record.game_rel_path  # Используем правильное поле game_rel_path

                if target_full.is_symlink() or target_full.exists():
                    if target_full.is_dir():
                        shutil.rmtree(target_full)
                    else:
                        target_full.unlink()

                if record.backup_path:
                    backup = Path(record.backup_path)
                    if backup.exists() and not target_full.exists():
                        shutil.move(str(backup), str(target_full))

                self.session.delete(record)
                count += 1
            except Exception as e:
                self.logger.log(f"Ошибка отката {record.game_rel_path}: {e}", "warning")

        self.session.commit()
        return True, f"Откачено {count} файлов."