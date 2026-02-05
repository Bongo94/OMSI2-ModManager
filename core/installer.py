import os
import shutil
import hashlib
from pathlib import Path
from sqlalchemy import func
from core.database import Mod, ModFile, InstalledFile, HofFile


class ModInstaller:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger
        self.game_root = Path(self.config.game_path)

        self.backup_dir = Path(self.config.library_path) / "Backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def update_load_order(self, mod_id_list):
        for index, mod_id in enumerate(mod_id_list):
            mod = self.session.query(Mod).get(mod_id)
            if mod:
                mod.priority = index
        self.session.commit()
        return self.sync_state()

    def toggle_mod(self, mod_id, enable):
        mod = self.session.query(Mod).get(mod_id)
        if not mod:
            return False, "Мод не найден"

        mod.is_enabled = enable
        if enable:
            max_prio = self.session.query(func.max(Mod.priority)).scalar() or 0
            mod.priority = max_prio + 1

        self.session.commit()
        return self.sync_state()

    def delete_mod_permanently(self, mod_id):
        mod = self.session.query(Mod).get(mod_id)
        if not mod:
            return False, "Мод не найден в БД"

        mod_name = mod.name
        storage_path = Path(mod.storage_path)

        self.logger.log(f"Удаление мода: {mod_name}...", "info")

        if mod.is_enabled:
            mod.is_enabled = False
            self.session.commit()
            success, msg = self.sync_state()
            if not success:
                return False, f"Ошибка при отключении файлов: {msg}"

        # Удаление HOF файлов
        hofs = self.session.query(HofFile).filter_by(mod_id=mod.id).all()
        for hof in hofs:
            try:
                hof_path = Path(hof.full_source_path)
                if hof_path.exists() and self.config.library_path in str(hof_path):
                    os.remove(hof_path)
            except Exception as e:
                self.logger.log(f"Не удалось удалить HOF {hof.filename}: {e}", "warning")

        # Удаление папки
        try:
            if storage_path.exists():
                def on_rm_error(func, path, exc_info):
                    os.chmod(path, 0o777)
                    func(path)

                shutil.rmtree(storage_path, onerror=on_rm_error)
        except Exception as e:
            return False, f"Ошибка удаления файлов с диска: {e}"

        try:
            self.session.delete(mod)
            self.session.commit()
        except Exception as e:
            return False, f"Ошибка БД: {e}"

        return True, f"Мод '{mod_name}' успешно удален."

    def sync_state(self):
        self.logger.log("Сбор данных...", "progress", 0)

        # Получаем текущий корень игры (строкой) для фильтрации в БД
        current_root = str(self.game_root)

        active_mods = self.session.query(Mod).filter_by(is_enabled=True).order_by(Mod.priority).all()

        # Загружаем установленные файлы ТОЛЬКО для текущей папки игры
        tracked_files_query = self.session.query(InstalledFile).filter_by(root_path=current_root).all()
        current_installed_map = {rec.game_path.replace("\\", "/").lower(): rec for rec in tracked_files_query}

        # desired_state = { "путь/к/файлу_lowercase": (source_path, mod_id, ORIGINAL_CASE_PATH) }
        desired_state = {}

        for mod in active_mods:
            for file in mod.files:
                if not file.target_game_path: continue

                # Ключ для словаря - lowercase (чтобы избежать дублей File.txt и file.txt)
                path_key = file.target_game_path.replace("\\", "/").lower()

                full_source = Path(mod.storage_path) / file.source_rel_path

                # ВАЖНО: Мы сохраняем file.target_game_path (оригинальный регистр) третьим элементом
                desired_state[path_key] = (full_source, mod.id, file.target_game_path)

        to_remove = []
        to_install = []

        # А) Проверяем, что нужно УДАЛИТЬ
        for game_path_lower, record in current_installed_map.items():
            if game_path_lower not in desired_state:
                to_remove.append(record)
            elif desired_state[game_path_lower][1] != record.active_mod_id:
                to_remove.append(record)

        # Б) Проверяем, что нужно УСТАНОВИТЬ
        # Распаковываем теперь 3 значения: source, mod_id и original_case_path
        for game_path_lower, (source, mod_id, original_case_path) in desired_state.items():
            if game_path_lower not in current_installed_map:
                to_install.append((original_case_path, source, mod_id))
            elif current_installed_map[game_path_lower] in to_remove:
                to_install.append((original_case_path, source, mod_id))

        total_ops = len(to_remove) + len(to_install)
        if total_ops == 0:
            return True, "Изменений не требуется"

        current_op = 0
        errors = []
        new_db_records = []

        # Удаление
        for record in to_remove:
            try:
                self._remove_installed_file(record)
                self.session.delete(record)
            except Exception as e:
                errors.append(f"Err rm {record.game_path}: {e}")
            current_op += 1
            if current_op % 20 == 0:
                self._report_progress(current_op, total_ops, "Удаление старых файлов...")

        self.session.flush()

        # Установка
        for original_case_path, source, mod_id in to_install:
            try:
                # ВАЖНО: передаем original_case_path (с большими буквами)
                backup, orig_hash = self._install_file_physically(original_case_path, source)

                new_db_records.append(InstalledFile(
                    game_path=original_case_path,  # Сохраняем красивый путь в базу
                    root_path=current_root,
                    active_mod_id=mod_id,
                    backup_path=backup,
                    original_hash=orig_hash
                ))
            except PermissionError:
                # Ловим конкретно ошибку доступа
                error_msg = f"Access Denied to '{original_case_path}'. Try running the manager as an Administrator."
                errors.append(error_msg)
            except Exception as e:
                # Ловим все остальные ошибки
                errors.append(f"Err inst {original_case_path}: {e}")

            current_op += 1
            if current_op % 20 == 0:
                self._report_progress(current_op, total_ops, "Установка новых файлов...")

        self.logger.log("Сохранение базы данных...", "progress", 99)
        if new_db_records:
            self.session.bulk_save_objects(new_db_records)

        self.session.commit()

        if errors:
            # Сообщение-заголовок
            summary_msg = f"Завершено с ошибками ({len(errors)}). Детали ниже:"
            self.logger.log(summary_msg, "warning")

            # Отправляем каждую ошибку в лог отдельно
            for error_detail in errors:
                self.logger.log(str(error_detail), "error")  # Уровень 'error' для красного цвета

            return False, summary_msg

        return True, "Успешно"

    def _report_progress(self, current, total, text):
        percent = int((current / total) * 100)
        self.logger.log(text, "progress", percent)

    def _install_file_physically(self, game_rel_path, source_full_path):
        """
        Создает симлинк, сохраняя регистр папок.
        """
        target_path = self.game_root / game_rel_path

        # ВАЖНО: mkdir parents=True создает папки.
        # Если Windows, она может создать lowercase, если мы не аккуратны.
        # Но pathlib обычно использует регистр, переданный в аргументе.
        if not target_path.parent.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)

        backup_path = None
        original_hash = None

        if target_path.exists() or target_path.is_symlink():
            if target_path.is_symlink():
                target_path.unlink()
            else:
                original_hash = self._get_hash(target_path)
                backup_name = f"{original_hash}_{target_path.name}"
                backup_full_path = self.backup_dir / backup_name

                if not backup_full_path.exists():
                    shutil.move(str(target_path), str(backup_full_path))
                else:
                    target_path.unlink()

                backup_path = str(backup_full_path)

        try:
            if not source_full_path.exists():
                raise FileNotFoundError(f"Source missing: {source_full_path}")

            os.symlink(str(source_full_path), str(target_path))
        except OSError:
            shutil.copy2(str(source_full_path), str(target_path))

        return backup_path, original_hash

    def _remove_installed_file(self, record):
        target_path = self.game_root / record.game_path

        if target_path.exists() or target_path.is_symlink():
            if target_path.is_dir():
                shutil.rmtree(target_path)
            else:
                target_path.unlink()

        if record.backup_path:
            backup = Path(record.backup_path)
            if backup.exists() and not target_path.exists():
                shutil.move(str(backup), str(target_path))

        self._cleanup_empty_dirs(target_path.parent)

    def _get_hash(self, path):
        hash_md5 = hashlib.md5()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except:
            return "error"

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