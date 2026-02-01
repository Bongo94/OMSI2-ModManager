import json

import webview
import os
from core.config import ConfigManager
from core.importer import ModImporter


class UILogger:
    """Класс для отправки сообщений в веб-интерфейс"""

    def __init__(self, window):
        self.window = window

    def log(self, message, level="info"):
        """
        levels: info, success, warning, error
        """
        # Экранируем текст и отправляем в JS функцию addLog()
        sanitized_msg = json.dumps(message)
        self.window.evaluate_js(f"addLog({sanitized_msg}, '{level}')")


class Api:
    """API, которое будет доступно из JavaScript"""

    def __init__(self):
        self.config_manager = ConfigManager()

    def get_config(self):
        return {
            "game_path": self.config_manager.game_path,
            "library_path": self.config_manager.library_path
        }

    def import_mod_step1(self):
        """ШАГ 1: Выбор файла и Анализ"""
        file_types = ('Archives (*.zip;*.7z;*.rar)', 'All files (*.*)')
        result = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)

        if result:
            filepath = result[0]
            # Создаем импортер с логгером
            importer = ModImporter(self.config_manager, self.logger)

            # Запускаем анализ
            preview_data = importer.step1_prepare_preview(filepath)
            return preview_data
        return None

    def import_mod_step2(self, preview_data):
        """ШАГ 2: Подтверждение"""
        importer = ModImporter(self.config_manager, self.logger)
        success = importer.step2_confirm_import(preview_data)
        return success

    def cancel_import(self, temp_path):
        """Отмена"""
        importer = ModImporter(self.config_manager, self.logger)
        importer.cancel_import(temp_path)

    def browse_folder(self):
        """Открывает нативное окно выбора папки"""
        folder = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return folder[0] if folder else None

    def set_game_path(self, path):
        return self.config_manager.set_game_path(path)

    def set_library_path(self, path):
        return self.config_manager.set_library_path(path)

    def import_mod(self):
        """Открывает диалог выбора файла и запускает импорт"""
        # Фильтр файлов
        file_types = ('Archives (*.zip;*.7z;*.rar)', 'All files (*.*)')

        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=file_types
        )

        if result:
            filepath = result[0]
            importer = ModImporter(self.config_manager)

            # Внимание: Операция может быть долгой, в идеале нужно запускать в потоке
            # Но пока сделаем синхронно для простоты
            success, message = importer.import_mod_archive(filepath)
            return {"success": success, "message": message}

        return None

    def get_mods_list(self):
        """Возвращает список модов для отображения в таблице"""
        from core.database import Mod
        session = self.config_manager.session
        mods = session.query(Mod).all()

        result = []
        for m in mods:
            result.append({
                "id": m.id,
                "name": m.name,
                "type": m.mod_type.value,  # enum toё string
                "is_enabled": m.is_enabled,
                "date": m.install_date.strftime("%Y-%m-%d %H:%M")
            })
        return result

    def set_window(self, window):
        self.window = window
        self.logger = UILogger(window)


if __name__ == '__main__':
    api = Api()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    # ОБРАТИ ВНИМАНИЕ НА ПУТЬ:
    ui_path = os.path.join(current_dir, 'ui', 'index.html')

    window = webview.create_window(
        'OMSI 2 Mod Manager',
        url=f'file://{ui_path}',
        width=1100,  # Сделал пошире
        height=800,
        js_api=api,
        min_size=(900, 600),
        background_color='#111827'  # Цвет фона (серый темный) чтобы не мелькало белым
    )
    api.set_window(window)
    webview.start(debug=True)
