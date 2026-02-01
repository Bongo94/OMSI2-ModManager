import json
import os
import webview
from core.config import ConfigManager
from core.database import Mod
from core.importer import ModImporter
from core.installer import ModInstaller


class UILogger:
    """Класс для отправки сообщений в веб-интерфейс."""

    def __init__(self, window):
        self._window = window

    def log(self, message, level="info", progress=None):
        """Отправляет сообщение в JS-функцию addLog."""
        try:
            # Убедимся, что сообщение - строка, и экранируем его для JS
            sanitized_msg = json.dumps(str(message))
            # Если есть прогресс, вызываем другую функцию в JS
            if level == "progress":
                self._window.evaluate_js(f"window.updateProgress({progress}, {sanitized_msg})")
            else:
                self._window.evaluate_js(f"window.addLog({sanitized_msg}, '{level}')")
        except Exception as e:
            print(f"Failed to log to UI: {e}")


class Api:
    """API, которое доступно из JavaScript."""

    def __init__(self):
        self.config_manager = ConfigManager()
        self._window = None
        self._logger = None

    def set_window(self, window):
        """Вызывается после создания окна для установки ссылок."""
        self._window = window
        self._logger = UILogger(window)

    def get_config(self):
        """Возвращает текущие настройки путей."""
        return {
            "game_path": self.config_manager.game_path,
            "library_path": self.config_manager.library_path,
        }

    def browse_folder(self):
        """Открывает нативное окно выбора папки."""
        if not self._window: return None
        folder = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return folder[0] if folder else None

    def set_game_path(self, path):
        return self.config_manager.set_game_path(path)

    def set_library_path(self, path):
        return self.config_manager.set_library_path(path)

    def get_mods_list(self):
        """Возвращает список всех модов из БД для отображения в таблице."""
        session = self.config_manager.session
        mods = session.query(Mod).order_by(Mod.name).all()

        result = []
        for m in mods:
            result.append({
                "id": m.id,
                "name": m.name,
                "type": m.mod_type.value if m.mod_type else "unknown",
                "is_enabled": m.is_enabled,
                "date": m.install_date.strftime("%Y-%m-%d"),
            })
        return result

    def import_mod_step1(self):
        """ШАГ 1: Диалог выбора файла и запуск анализа."""
        file_types = ('Архивы (*.zip;*.7z;*.rar)', 'Все файлы (*.*)')
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)

        if result and result[0]:
            filepath = result[0]
            importer = ModImporter(self.config_manager, self._logger)
            preview_data = importer.step1_prepare_preview(filepath)
            return preview_data
        return None

    def import_mod_step2(self, preview_data):
        """ШАГ 2: Подтверждение и запись мода в БД."""
        importer = ModImporter(self.config_manager, self._logger)
        success = importer.step2_confirm_import(preview_data)
        return success

    def cancel_import(self, temp_path):
        """Отмена импорта и удаление временных файлов."""
        importer = ModImporter(self.config_manager, self._logger)
        importer.cancel_import(temp_path)

    def toggle_mod(self, mod_id):
        # Теперь передаем True/False, логика "переключения" внутри
        session = self.config_manager.session
        mod = session.query(Mod).get(mod_id)
        current_state = mod.is_enabled

        installer = ModInstaller(self.config_manager, self._logger)
        success, msg = installer.toggle_mod(mod_id, not current_state)  # Инвертируем

        if success:
            return {"status": "success", "message": msg}
        return {"status": "error", "message": msg}

    def get_conflicts(self):
        """
        Возвращает ТОЛЬКО те моды, которые имеют конфликты файлов (исключая Fonts).
        """
        session = self.config_manager.session
        # Берем только включенные моды
        enabled_mods = session.query(Mod).filter_by(is_enabled=True).order_by(Mod.priority).all()

        file_map = {}  # { "Vehicles/Bus/file.cfg": [ModA, ModB] }

        # 1. Собираем карту всех файлов
        for mod in enabled_mods:
            for f in mod.files:
                path = f.target_game_path
                if not path: continue

                # НОРМАЛИЗАЦИЯ ПУТИ (важно для Windows)
                path = path.replace("\\", "/").lower()

                # ИГНОРИРУЕМ FONTS
                if path.startswith("fonts/"):
                    continue

                if path not in file_map:
                    file_map[path] = []
                file_map[path].append(mod)

        # 2. Ищем файлы, где претендентов > 1
        conflicting_mod_ids = set()
        for path, mods_list in file_map.items():
            if len(mods_list) > 1:
                for m in mods_list:
                    conflicting_mod_ids.add(m.id)

        # 3. Формируем итоговый список модов, сохраняя их текущий порядок приоритета
        result = []
        # Проходим по исходному отсортированному списку, чтобы сохранить относительный порядок
        for mod in enabled_mods:
            if mod.id in conflicting_mod_ids:
                result.append({
                    "id": mod.id,
                    "name": mod.name,
                    "priority": mod.priority
                })

        # Если конфликтов нет, список будет пуст
        return result

    def save_load_order(self, ordered_mod_ids):
        """
        Обновляет приоритеты.
        ordered_mod_ids: список ID конфликтных модов в порядке возрастания приоритета (СНИЗУ ВВЕРХ в UI).
        """
        installer = ModInstaller(self.config_manager, self._logger)

        # 1. Получаем все активные моды в текущем порядке
        session = self.config_manager.session
        all_active_mods = session.query(Mod).filter_by(is_enabled=True).order_by(Mod.priority).all()

        # 2. Создаем маппинг для быстрой перестановки
        # Нам нужно внедрить новый порядок (ordered_mod_ids) внутрь общего списка all_active_mods,
        # не нарушив порядок тех модов, которые в конфликте не участвуют.

        # Простая стратегия:
        # Присвоим всем модам новые приоритеты с шагом 10.
        # Конфликтным модам выставим приоритеты так, чтобы они выстроились как надо.

        # Но самый надежный способ для пользователя:
        # Просто переписать приоритеты переданных модов, сделав их выше остальных?
        # Нет, это сломает логику.

        # РЕШЕНИЕ: Просто обновляем приоритеты переданных модов,
        # распределяя их равномерно, но выше предыдущего значения

        try:
            # Для простоты: просто переиндексируем ВСЕ активные моды.
            # Но сначала переставим переданные ID в нужном порядке.

            # Собираем список ID всех активных
            full_id_list = [m.id for m in all_active_mods]

            # Удаляем из общего списка те, что мы сейчас сортируем
            for uid in ordered_mod_ids:
                if uid in full_id_list:
                    full_id_list.remove(uid)

            # Вставляем их обратно в конец списка (так как в UI мы обычно решаем, кто "победит",
            # а побеждает тот, кто ниже в списке / выше приоритет).
            # В данном случае мы просто добавим их в конец, считая их "самыми важными" в текущем контексте,
            # либо попытаемся вставить на "среднее" место.

            # Давайте просто добавим их в конец списка глобального приоритета.
            # Это гарантирует, что порядок, который выставил юзер, будет соблюден.
            full_id_list.extend(ordered_mod_ids)

            # Применяем новые приоритеты
            for index, mod_id in enumerate(full_id_list):
                mod = session.query(Mod).get(mod_id)
                if mod:
                    mod.priority = index

            session.commit()  # ВАЖНО: Сохранить в БД перед вызовом установщика

            # 3. Запускаем синхронизацию
            success, msg = installer.sync_state()
            return {"status": "success" if success else "error", "message": msg}

        except Exception as e:
            return {"status": "error", "message": str(e)}


if __name__ == '__main__':
    api = Api()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    ui_path = os.path.join(current_dir, 'ui', 'index.html')

    window = webview.create_window(
        'OMSI 2 Mod Manager',
        url=f'file://{ui_path}',
        width=1100,
        height=800,
        js_api=api,
        min_size=(900, 600),
        background_color='#111827'
    )

    # Передаем созданное окно в API после его создания
    api.set_window(window)

    webview.start(debug=False)
