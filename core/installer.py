import os
import shutil
import hashlib
from pathlib import Path
from core.database import Mod, ModFile, InstalledFile


class ModInstaller:
    def __init__(self, config_manager, logger):
        self.config = config_manager
        self.session = config_manager.session
        self.logger = logger
        self.backup_dir = Path(self.config.library_path) / "Backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def toggle_mod(self, mod_id):
        mod = self.session.query(Mod).get(mod_id)
        if not mod: return False, "Мод не найден"
        return self._deactivate_mod(mod) if mod.is_enabled else self._activate_mod(mod)

    def _activate_mod(self, mod):
        game_root = Path(self.config.game_path)
        mod_storage = Path(mod.storage_path)
        files_to_install = [f for f in mod.files if f.target_game_path]

        self.logger.log(f"Активация мода '{mod.name}' ({len(files_to_install)} файлов)...", "info")

        # ИЗМЕНЕНИЕ 1: Мы будем собирать все записи для БД в список и добавлять их разом
        # Это защищает от частичной установки в случае ошибки.
        newly_installed_records = []
        errors = []

        try:
            for file_record in files_to_install:
                source_path = mod_storage / file_record.source_rel_path
                target_path = game_root / file_record.target_game_path

                backup_path_info = None
                original_hash_info = None

                # Шаг 1: Подготовить целевой путь (обработать конфликты)
                if target_path.exists() or target_path.is_symlink():
                    success, backup_path_info, original_hash_info = self._handle_conflict(target_path)
                    if not success:
                        errors.append(f"Конфликт: {file_record.target_game_path}")
                        continue

                # Шаг 2: Создать папки
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # Шаг 3: Создать симлинк
                try:
                    os.symlink(source_path, target_path)
                except OSError as e:
                    if hasattr(e, 'winerror') and e.winerror == 1314:
                        raise Exception("Требуются права Администратора или Режим разработчика для создания симлинков!")
                    errors.append(f"Ошибка ссылки: {e}")
                    continue  # Пропускаем этот файл

                # Шаг 4: Подготовить запись для БД (но пока не добавлять в сессию)
                # Это ЕДИНСТВЕННОЕ место, где создается InstalledFile
                newly_installed_records.append(
                    InstalledFile(
                        game_path=str(file_record.target_game_path),
                        active_mod_id=mod.id,
                        backup_path=backup_path_info,
                        original_hash=original_hash_info
                    )
                )

            if errors:
                # Если были ошибки (кроме критической), сообщаем о них
                self.logger.log(f"При активации возникли проблемы ({len(errors)}). Пример: {errors[0]}", "warning")

            # ИЗМЕНЕНИЕ 2: Если все прошло успешно, добавляем все записи в БД разом
            self.session.add_all(newly_installed_records)
            mod.is_enabled = True
            self.session.commit()
            self.logger.log(f"Мод '{mod.name}' активирован.", "success")
            return True, "Активирован"

        except Exception as e:
            # В случае критической ошибки (нет прав, диск отвалился) - откатываем всё
            self.session.rollback()
            self.logger.log(f"Критическая ошибка активации: {e}", "error")
            # TODO: В будущем здесь нужно будет откатить уже созданные симлинки
            return False, str(e)

    def _deactivate_mod(self, mod):
        self.logger.log(f"Деактивация мода '{mod.name}'...", "info")
        installed_files = self.session.query(InstalledFile).filter_by(active_mod_id=mod.id).all()
        game_root = Path(self.config.game_path)

        for record in installed_files:
            target_path = game_root / record.game_path

            if target_path.is_symlink():
                try:
                    target_path.unlink()
                except:
                    pass

            if record.backup_path:
                backup_src = Path(record.backup_path)
                if backup_src.exists():
                    try:
                        shutil.move(str(backup_src), str(target_path))
                    except Exception as e:
                        self.logger.log(f"Ошибка восстановления бэкапа: {e}", "error")

            self.session.delete(record)
            self._cleanup_empty_dirs(target_path.parent, game_root)

        mod.is_enabled = False
        self.session.commit()
        self.logger.log(f"Мод '{mod.name}' выключен.", "success")
        return True, "Деактивирован"

    # ИЗМЕНЕНИЕ 3: Функция теперь не трогает БД, а только файлы, и возвращает результат
    def _handle_conflict(self, target_path):
        """
        Обрабатывает существующий файл. Возвращает (Success, backup_path, original_hash).
        """
        rel_path = str(target_path.relative_to(self.config.game_path))
        existing_record = self.session.query(InstalledFile).filter_by(game_path=rel_path).first()

        if existing_record:
            self.logger.log(f"Конфликт! Файл {rel_path} занят другим модом.", "warning")
            return False, None, None

        if target_path.exists() and not target_path.is_symlink():
            file_hash = self._get_hash(target_path)
            backup_name = f"{file_hash}_{target_path.name}"
            backup_full_path = self.backup_dir / backup_name

            if not backup_full_path.exists():
                shutil.move(str(target_path), str(backup_full_path))
            else:
                target_path.unlink()

            # Возвращаем информацию о бэкапе для основного цикла
            return True, str(backup_full_path), file_hash

        # Если это 'висячий' симлинк или другая непонятная ситуация
        return False, None, None

    def _get_hash(self, path):
        hash_md5 = hashlib.md5()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except:
            return None  # Если файл не удалось прочитать

    def _cleanup_empty_dirs(self, path, stop_at_root):
        try:
            while path != stop_at_root and path.exists():
                if not any(path.iterdir()):
                    path.rmdir()
                    path = path.parent
                else:
                    break
        except:
            pass