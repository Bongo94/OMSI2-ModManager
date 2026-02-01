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
        """Включает или выключает мод"""
        installer = ModInstaller(self.config_manager, self._logger)
        try:
            success, msg = installer.toggle_mod(mod_id)
            if success:
                return {"status": "success", "message": msg}
            else:
                self._logger.log(msg, "error")
                return {"status": "error", "message": msg}
        except Exception as e:
            self._logger.log(str(e), "error")
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

    webview.start(debug=True)
