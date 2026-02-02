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
        """Обновляет приоритеты на основе списка ID (от низкого к высокому)"""
        for index, mod_id in enumerate(mod_id_list):
            mod = self.session.query(Mod).get(mod_id)
            if mod:
                mod.priority = index
        self.session.commit()
        return self.sync_state()

    def toggle_mod(self, mod_id, enable):
        """Просто меняет флаг is_enabled, затем запускает полную синхронизацию"""
        mod = self.session.query(Mod).get(mod_id)
        if not mod:
            return False, "Мод не найден"

        mod.is_enabled = enable
        # Если включаем, даем высокий приоритет
        if enable:
            max_prio = self.session.query(func.max(Mod.priority)).scalar() or 0
            mod.priority = max_prio + 1

        self.session.commit()
        return self.sync_state()

    def delete_mod_permanently(self, mod_id):
        """
        Полное удаление мода:
        1. Выключение (удаление из игры).
        2. Удаление файлов из библиотеки.
        3. Удаление из БД.
        """
        mod = self.session.query(Mod).get(mod_id)
        if not mod:
            return False, "Мод не найден в БД"

        mod_name = mod.name
        storage_path = Path(mod.storage_path)

        self.logger.log(f"Удаление мода: {mod_name}...", "info")

        # ШАГ 1: Убираем файлы из игры (если мод был включен)
        if mod.is_enabled:
            self.logger.log("Отключение мода перед удалением...", "info")
            mod.is_enabled = False
            self.session.commit()

            success, msg = self.sync_state()
            if not success:
                return False, f"Ошибка при отключении файлов: {msg}"

        # ШАГ 2: Удаляем HOF файлы, связанные с модом (из HOF_Storage)
        # Они могут лежать вне папки storage_path, поэтому удаляем отдельно
        hofs = self.session.query(HofFile).filter_by(mod_id=mod.id).all()
        for hof in hofs:
            try:
                hof_path = Path(hof.full_source_path)
                # Удаляем только если файл существует и находится внутри библиотеки (защита от удаления лишнего)
                if hof_path.exists() and self.config.library_path in str(hof_path):
                    os.remove(hof_path)
            except Exception as e:
                self.logger.log(f"Не удалось удалить HOF {hof.filename}: {e}", "warning")

        # ШАГ 3: Физическое удаление папки мода из библиотеки
        try:
            if storage_path.exists():
                # shutil.rmtree часто падает на Windows из-за read-only файлов, поэтому используем костыль
                def on_rm_error(func, path, exc_info):
                    os.chmod(path, 0o777)
                    func(path)

                shutil.rmtree(storage_path, onerror=on_rm_error)
                self.logger.log(f"Папка {storage_path.name} удалена с диска.", "info")
            else:
                self.logger.log("Папка мода уже отсутствует на диске.", "warning")
        except Exception as e:
            return False, f"Ошибка удаления файлов с диска: {e}"

        # ШАГ 4: Удаление записи из БД
        try:
            self.session.delete(mod)
            self.session.commit()
        except Exception as e:
            return False, f"Ошибка БД: {e}"

        return True, f"Мод '{mod_name}' успешно удален."

    def sync_state(self):
        """
        ГЛАВНАЯ ФУНКЦИЯ.
        Приводит папку игры в соответствие с включенными модами и их приоритетами.
        """
        self.logger.log("Сбор данных...", "progress", 0)

        # 1. Загружаем ВСЕ данные в память одним махом
        # Активные моды
        active_mods = self.session.query(Mod).filter_by(is_enabled=True).order_by(Mod.priority).all()

        # Текущее состояние файлов в игре (что мы уже установили)
        # Превращаем в словарь: { "Vehicles/Bus/file.cfg": InstalledFileObject }
        tracked_files_query = self.session.query(InstalledFile).all()
        current_installed_map = {rec.game_path.replace("\\", "/").lower(): rec for rec in tracked_files_query}

        # 2. Рассчитываем "Желаемое состояние" в памяти
        # desired_state = { "путь/к/файлу": (source_path, mod_id) }
        desired_state = {}

        total_files_to_process = 0
        for mod in active_mods:
            for file in mod.files:
                if not file.target_game_path: continue

                path_key = file.target_game_path.replace("\\", "/").lower()
                full_source = Path(mod.storage_path) / file.source_rel_path

                # Из-за сортировки active_mods по приоритету,
                # последний записанный мод перезапишет предыдущие в словаре.
                desired_state[path_key] = (full_source, mod.id)

        # 3. Составляем списки действий (Diff)
        to_remove = []  # Список записей InstalledFile для удаления
        to_install = []  # Список (game_path, source, mod_id) для установки

        # А) Проверяем, что нужно УДАЛИТЬ (или заменить владельца)
        for game_path_lower, record in current_installed_map.items():
            # Если файла нет в желаемом состоянии
            if game_path_lower not in desired_state:
                to_remove.append(record)
            # Или если владелец изменился (был МодА, стал МодБ)
            elif desired_state[game_path_lower][1] != record.active_mod_id:
                to_remove.append(record)
                # Важно: если владелец сменился, мы удаляем старое,
                # а новое добавится в шаге Б, так как ключи совпадут

        # Б) Проверяем, что нужно УСТАНОВИТЬ
        for game_path_lower, (source, mod_id) in desired_state.items():
            # Если файла вообще нет в установленных
            if game_path_lower not in current_installed_map:
                to_install.append((game_path_lower, source, mod_id))
            # Если файл есть, но мы его пометили на удаление выше (смена владельца)
            # То его тоже надо установить заново
            elif current_installed_map[game_path_lower] in to_remove:
                to_install.append((game_path_lower, source, mod_id))
            # Иначе: файл уже стоит, и мод тот же -> пропускаем (ничего делать не надо)

        # 4. Выполняем действия с прогресс-баром
        total_ops = len(to_remove) + len(to_install)
        if total_ops == 0:
            return True, "Изменений не требуется"

        current_op = 0
        errors = []
        new_db_records = []

        # ШАГ 4.1: Массовое удаление
        for record in to_remove:
            try:
                self._remove_installed_file(record)
                self.session.delete(record)
            except Exception as e:
                errors.append(f"Err rm {record.game_path}: {e}")

            current_op += 1
            if current_op % 20 == 0:  # Обновляем UI каждые 20 файлов (чтобы не лагало)
                self._report_progress(current_op, total_ops, "Удаление старых файлов...")

        # Промежуточный сброс, чтобы освободить базу
        self.session.flush()

        # ШАГ 4.2: Массовая установка
        for game_path_lower, source, mod_id in to_install:
            try:
                # game_path_lower у нас в нижнем регистре, но для симлинка лучше брать
                # "красивый" путь. Возьмем его из source имени или оставим как есть.
                # Для надежности можно хранить оригинальный case, но пока так:

                # Для создания InstalledFile нам нужен относительный путь
                # А source - это Path объект

                # Восстанавливаем "нормальный" путь для ОС из ключа (slashes fix)
                target_rel_path = game_path_lower  # Можно попытаться восстановить регистр, но для Windows не критично

                # Установка физически
                backup, orig_hash = self._install_file_physically(target_rel_path, source)

                # Готовим запись для БД (но не добавляем пока, чтобы быстрее)
                new_db_records.append(InstalledFile(
                    game_path=target_rel_path,
                    active_mod_id=mod_id,
                    backup_path=backup,
                    original_hash=orig_hash
                ))
            except Exception as e:
                errors.append(f"Err inst {game_path_lower}: {e}")

            current_op += 1
            if current_op % 20 == 0:
                self._report_progress(current_op, total_ops, "Установка новых файлов...")

        # ШАГ 5: Финальная запись в БД
        self.logger.log("Сохранение базы данных...", "progress", 99)
        if new_db_records:
            self.session.bulk_save_objects(new_db_records)

        self.session.commit()

        self.logger.log(f"Готово. Обработано {total_ops} файлов.", "progress", 100)

        if errors:
            self.logger.log(f"Были ошибки ({len(errors)})", "warning")
            return False, "Завершено с ошибками"

        return True, "Успешно"

    def _report_progress(self, current, total, text):
        percent = int((current / total) * 100)
        self.logger.log(text, "progress", percent)

    def _install_file_physically(self, game_rel_path, source_full_path):
        """
        Только работа с файловой системой. Возвращает (backup_path, hash).
        """
        target_path = self.game_root / game_rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        backup_path = None
        original_hash = None

        if target_path.exists() or target_path.is_symlink():
            if target_path.is_symlink():
                target_path.unlink()
            else:
                # Бэкап оригинала
                original_hash = self._get_hash(target_path)
                backup_name = f"{original_hash}_{target_path.name}"
                backup_full_path = self.backup_dir / backup_name

                if not backup_full_path.exists():
                    shutil.move(str(target_path), str(backup_full_path))
                else:
                    target_path.unlink()

                backup_path = str(backup_full_path)

        try:
            # os.symlink требует прав администратора на старых Windows.
            # Если падает, пробуем копирование (это хуже для места, но работает)
            if not source_full_path.exists():
                raise FileNotFoundError(f"Source missing: {source_full_path}")

            os.symlink(str(source_full_path), str(target_path))
        except OSError:
            shutil.copy2(str(source_full_path), str(target_path))

        return backup_path, original_hash

    def _remove_installed_file(self, record):
        """Удаляет симлинк и восстанавливает бэкап, если он был"""
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