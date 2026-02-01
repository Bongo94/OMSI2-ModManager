import json
import webview
import os
from core.config import ConfigManager
from core.importer import ModImporter
from core.database import Mod  # Импортируем Mod здесь, чтобы избежать циклического импорта


class UILogger:
    """Класс для отправки сообщений в веб-интерфейс"""

    def __init__(self, window):
        self._window = window

    def log(self, message, level="info", progress=None):
        try:
            sanitized_msg = json.dumps(str(message))
            # Если есть прогресс, вызываем другую функцию в JS
            if level == "progress":
                self._window.evaluate_js(f"window.updateProgress({progress}, {sanitized_msg})")
            else:
                self._window.evaluate_js(f"window.addLog({sanitized_msg}, '{level}')")
        except Exception as e:
            print(f"Failed to log to UI: {e}")


class Api:
    """API, которое будет доступно из JavaScript"""

    def __init__(self):
        self.config_manager = ConfigManager()
        # Эти переменные будут инициализированы после создания окна
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
            "library_path": self.config_manager.library_path
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
                "date": m.install_date.strftime("%Y-%m-%d %H:%M")
            })
        return result

    def import_mod_step1(self):
        """ШАГ 1: Диалог выбора файла и запуск анализа."""
        file_types = ('Архивы (*.zip;*.7z;*.rar)', 'All files (*.*)')
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


if __name__ == '__main__':
    api = Api()

    # Определяем путь к HTML файлу
    current_dir = os.path.dirname(os.path.abspath(__file__))
    ui_path = os.path.join(current_dir, 'ui', 'index.html')

    # Создаем окно приложения
    window = webview.create_window(
        'OMSI 2 Mod Manager',
        url=f'file://{ui_path}',
        width=1100,
        height=800,
        js_api=api,
        min_size=(900, 600),
        background_color='#111827'
    )

    # Передаем созданное окно в API, чтобы логгер мог работать
    api.set_window(window)

    # Запускаем приложение
    webview.start(debug=True)  # debug=True включает консоль разработчика (F12)
