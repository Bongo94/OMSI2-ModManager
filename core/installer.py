# --- core/installer.py ---

import os
import shutil
import hashlib
from pathlib import Path
from sqlalchemy import func
from core.database import Mod, ModFile, InstalledFile


class ModInstaller:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger
        self.game_root = Path(self.config.game_path)

        self.backup_dir = Path(self.config.library_path) / "Backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def update_load_order(self, mod_id_list):
        """Обновляет приоритеты на основе списка ID (от низкого к высокому)"""
        for index, mod_id in enumerate(mod_id_list):
            mod = self.session.query(Mod).get(mod_id)
            if mod:
                mod.priority = index
        self.session.commit()
        # После смены приоритета нужно пересчитать состояние файлов
        return self.sync_state()

    def toggle_mod(self, mod_id, enable):
        """Просто меняет флаг is_enabled, затем запускает полную синхронизацию"""
        mod = self.session.query(Mod).get(mod_id)
        if not mod:
            return False, "Мод не найден"

        mod.is_enabled = enable
        # Если включаем, ставим максимальный приоритет (в конец списка)
        if enable:
            max_prio = self.session.query(func.max(Mod.priority)).scalar() or 0
            mod.priority = max_prio + 1

        self.session.commit()
        return self.sync_state()

    def sync_state(self):
        """
        ГЛАВНАЯ ФУНКЦИЯ.
        Приводит папку игры в соответствие с включенными модами и их приоритетами.
        """
        self.logger.log("Начало синхронизации файлов...", "info")

        # 1. Получаем все включенные моды, отсортированные по приоритету (0..99)
        # Моды с высшим приоритетом перезапишут файлы модов с низшим.
        active_mods = self.session.query(Mod).filter_by(is_enabled=True).order_by(Mod.priority).all()

        # 2. Строим карту "Желаемого состояния": { game_path: (source_path, mod_id) }
        desired_state = {}
        for mod in active_mods:
            for file in mod.files:
                if not file.target_game_path: continue
                # Нормализуем слеши
                path_key = file.target_game_path.replace("\\", "/")

                # Записываем (или перезаписываем, если приоритет выше)
                full_source = Path(mod.storage_path) / file.source_rel_path
                desired_state[path_key] = (full_source, mod.id)

        # 3. Получаем "Текущее состояние" из БД (какие файлы мы контролируем)
        tracked_files = self.session.query(InstalledFile).all()
        tracked_map = {rec.game_path.replace("\\", "/"): rec for rec in tracked_files}

        changes_count = 0
        errors = []

        # ШАГ А: Удаление файлов, которые больше не нужны (мод выключен или файл перекрыт)
        for game_path, record in tracked_map.items():
            # Если файла нет в желаемом состоянии ИЛИ его владельцем должен стать другой мод
            if game_path not in desired_state or desired_state[game_path][1] != record.active_mod_id:
                try:
                    self._remove_installed_file(record)
                    # Удаляем запись из сессии (она удалится из БД при commit)
                    self.session.delete(record)
                    changes_count += 1
                except Exception as e:
                    errors.append(f"Ошибка удаления {game_path}: {e}")

        # Промежуточный коммит, чтобы освободить пути
        self.session.commit()

        # ШАГ Б: Установка/Обновление файлов
        for game_path, (source_path, mod_id) in desired_state.items():
            # Проверяем, установлен ли уже этот файл именно этим модом
            # (Мы удалили старые записи выше, так что если запись есть - она актуальна)
            existing_record = self.session.query(InstalledFile).filter_by(game_path=game_path).first()

            if existing_record and existing_record.active_mod_id == mod_id:
                continue  # Всё уже стоит правильно

            try:
                self._install_file(game_path, source_path, mod_id)
                changes_count += 1
            except Exception as e:
                errors.append(f"Ошибка установки {game_path}: {e}")

        self.session.commit()

        if errors:
            self.logger.log(f"Синхронизация завершена с ошибками ({len(errors)})", "warning")
            return False, "\n".join(errors[:3])

        self.logger.log(f"Синхронизация успешно завершена. Изменений: {changes_count}", "success")
        return True, "Готово"

    def _install_file(self, game_rel_path, source_full_path, mod_id):
        target_path = self.game_root / game_rel_path

        # 1. Подготовка родительской папки
        target_path.parent.mkdir(parents=True, exist_ok=True)

        backup_path = None
        original_hash = None

        # 2. Если по пути что-то есть
        if target_path.exists() or target_path.is_symlink():
            if target_path.is_symlink():
                # Это старый симлинк (возможно битый), просто сносим
                target_path.unlink()
            else:
                # ЭТО ОРИГИНАЛЬНЫЙ ФАЙЛ ИГРЫ! НУЖЕН БЭКАП!
                original_hash = self._get_hash(target_path)
                backup_name = f"{original_hash}_{target_path.name}"
                backup_full_path = self.backup_dir / backup_name

                # Перемещаем оригинал в бэкап, если его там еще нет
                if not backup_full_path.exists():
                    shutil.move(str(target_path), str(backup_full_path))
                else:
                    # Если такой бэкап уже есть, оригинал можно удалить (он сохранен)
                    target_path.unlink()

                backup_path = str(backup_full_path)

        # 3. Создаем симлинк
        try:
            os.symlink(str(source_full_path), str(target_path))
        except OSError:
            # Fallback для старых Windows или отсутствия прав: копирование
            shutil.copy2(str(source_full_path), str(target_path))

        # 4. Пишем в журнал
        new_record = InstalledFile(
            game_path=str(game_rel_path).replace("\\", "/"),
            active_mod_id=mod_id,
            backup_path=backup_path,
            original_hash=original_hash
        )
        self.session.add(new_record)

    def _remove_installed_file(self, record):
        """Удаляет симлинк и восстанавливает бэкап, если он был"""
        target_path = self.game_root / record.game_path

        # Удаляем наш симлинк/файл
        if target_path.exists() or target_path.is_symlink():
            if target_path.is_dir():  # На случай ошибки, если путь стал папкой
                shutil.rmtree(target_path)
            else:
                target_path.unlink()

        # Восстанавливаем оригинал
        if record.backup_path:
            backup = Path(record.backup_path)
            if backup.exists():
                # Проверяем, не занял ли место кто-то другой (хотя логика выше должна это предотвратить)
                if not target_path.exists():
                    shutil.move(str(backup), str(target_path))
                else:
                    self.logger.log(f"Не удалось восстановить {record.game_path}: место занято.", "error")

        # Чистим пустые папки вверх
        self._cleanup_empty_dirs(target_path.parent)

    def _get_hash(self, path):
        hash_md5 = hashlib.md5()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except:
            return "error_hash"

    def _cleanup_empty_dirs(self, path):
        try:
            while path != self.game_root and path.exists():
                if not any(path.iterdir()):
                    path.rmdir()
                    path = path.parent
                else:
                    break
        except:
            pass