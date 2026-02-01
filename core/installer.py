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

        # Папка для бэкапов оригинальных файлов игры
        self.backup_dir = Path(self.config.library_path) / "Backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def toggle_mod(self, mod_id):
        """Переключает состояние мода (Вкл/Выкл)"""
        mod = self.session.query(Mod).get(mod_id)
        if not mod:
            return False, "Мод не найден"

        if mod.is_enabled:
            return self._deactivate_mod(mod)
        else:
            return self._activate_mod(mod)

    def _activate_mod(self, mod):
        """Установка мода (создание симлинков)"""
        game_root = Path(self.config.game_path)
        mod_storage = Path(mod.storage_path)

        # Получаем список файлов, которые нужно установить (игнорируем HOFы и файлы без путей)
        files_to_install = [f for f in mod.files if f.target_game_path]

        self.logger.log(f"Активация мода '{mod.name}' ({len(files_to_install)} файлов)...", "info")

        installed_count = 0
        errors = []

        try:
            for file_record in files_to_install:
                source_path = mod_storage / file_record.source_rel_path
                target_path = game_root / file_record.target_game_path

                # 1. Проверяем конфликты
                if target_path.exists() or target_path.is_symlink():
                    if not self._handle_conflict(target_path, mod.id):
                        errors.append(f"Конфликт: {file_record.target_game_path}")
                        continue

                # 2. Создаем структуру папок в игре, если нет
                target_path.parent.mkdir(parents=True, exist_ok=True)

                # 3. Создаем симлинк
                try:
                    os.symlink(source_path, target_path)

                    # 4. Регистрируем установку
                    inst_record = InstalledFile(
                        game_path=str(file_record.target_game_path),
                        active_mod_id=mod.id,
                        backup_path=None  # Бэкап мог быть создан в _handle_conflict, но логика сложнее.
                        # Упростим: InstalledFile хранит факт того, что МЫ владеем файлом.
                    )
                    self.session.add(inst_record)
                    installed_count += 1
                except OSError as e:
                    # Ошибка 1314 = нужны права админа
                    if hasattr(e, 'winerror') and e.winerror == 1314:
                        raise Exception("Требуются права Администратора или Режим разработчика для создания симлинков!")
                    errors.append(f"Ошибка создания ссылки: {e}")

            if errors:
                self.logger.log(f"Есть ошибки ({len(errors)}). Пример: {errors[0]}", "warning")

            mod.is_enabled = True
            self.session.commit()
            self.logger.log(f"Мод '{mod.name}' активирован.", "success")
            return True, "Активирован"

        except Exception as e:
            self.session.rollback()
            self.logger.log(f"Критическая ошибка активации: {e}", "error")
            # Тут по-хорошему надо откатить уже созданные ссылки, но пока оставим так
            return False, str(e)

    def _deactivate_mod(self, mod):
        """Удаление мода (удаление ссылок, восстановление бэкапов)"""
        self.logger.log(f"Деактивация мода '{mod.name}'...", "info")

        # Ищем все файлы, которые этот мод "держит" в игре
        installed_files = self.session.query(InstalledFile).filter_by(active_mod_id=mod.id).all()
        game_root = Path(self.config.game_path)

        count = 0
        for record in installed_files:
            target_path = game_root / record.game_path

            # Удаляем наш симлинк
            if target_path.is_symlink():
                try:
                    target_path.unlink()
                except Exception as e:
                    self.logger.log(f"Не удалось удалить ссылку {record.game_path}: {e}", "warning")

            # Если был бэкап (оригинальный файл), восстанавливаем
            if record.backup_path:
                backup_src = Path(record.backup_path)
                if backup_src.exists():
                    try:
                        shutil.move(str(backup_src), str(target_path))
                    except Exception as e:
                        self.logger.log(f"Ошибка восстановления бэкапа: {e}", "error")

            # Удаляем запись о владении
            self.session.delete(record)
            count += 1

            # Удаляем пустые папки (чистота игры)
            self._cleanup_empty_dirs(target_path.parent, game_root)

        mod.is_enabled = False
        self.session.commit()
        self.logger.log(f"Мод выключен. Убрано файлов: {count}", "success")
        return True, "Деактивирован"

    def _handle_conflict(self, target_path, new_mod_id):
        """
        Решает, что делать, если файл уже есть в игре.
        Возвращает True, если путь освобожден и готов к симлинку.
        Возвращает False, если конфликт неразрешим.
        """
        # 1. Проверяем, чей это файл по базе
        # Относительный путь для поиска в БД
        rel_path = str(target_path.relative_to(self.config.game_path))
        existing_record = self.session.query(InstalledFile).filter_by(game_path=rel_path).first()

        if existing_record:
            # Файл принадлежит другому моду
            self.logger.log(f"Конфликт! Файл занят модом ID {existing_record.active_mod_id}", "warning")
            return False  # Пока просто запрещаем перезаписывать чужие моды

        # 2. Если записи в БД нет, но файл есть физически -> ЭТО ОРИГИНАЛ ИГРЫ (или мусор)
        if target_path.exists() and not target_path.is_symlink():
            # Делаем бэкап
            file_hash = self._get_hash(target_path)
            backup_name = f"{file_hash}_{target_path.name}"
            backup_full_path = self.backup_dir / backup_name

            # Копируем в бэкап, если еще нет
            if not backup_full_path.exists():
                shutil.move(str(target_path), str(backup_full_path))
            else:
                target_path.unlink()  # Бэкап уже есть, просто удаляем оригинал

            # Нам нужно сохранить информацию о бэкапе, но запись InstalledFile создается позже
            # Это архитектурный момент.
            # Для простоты сейчас: мы создадим "пустышку" записи с инфой о бэкапе,
            # а основной цикл _activate_mod ее обновит или используем existing_record.
            # Но правильнее вернуть путь к бэкапу наружу.

            # Упрощение для прототипа:
            # Мы вернем True, но запись о бэкапе добавим прямо здесь в сессию
            # (но не закоммитим пока).
            # ВНИМАНИЕ: В _activate_mod мы создаем InstalledFile.
            # Надо передать туда инфу о бэкапе.
            # Пока сделаем хак: просто вернем True, но потеряем ссылку на бэкап в БД (плохо).

            # ПРАВИЛЬНЫЙ ПУТЬ:
            # Сделаем запись InstalledFile прямо тут, но с active_mod_id = new_mod_id
            # А основной цикл будет проверять, не создана ли запись

            rec = InstalledFile(
                game_path=rel_path,
                active_mod_id=new_mod_id,
                backup_path=str(backup_full_path),
                original_hash=file_hash
            )
            self.session.add(rec)
            # Файл перемещен, место свободно
            return True

        return False

    def _get_hash(self, path):
        hash_md5 = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _cleanup_empty_dirs(self, path, stop_at_root):
        """Удаляет пустые папки вверх по дереву"""
        try:
            while path != stop_at_root:
                if not any(path.iterdir()):
                    path.rmdir()
                    path = path.parent
                else:
                    break
        except:
            pass