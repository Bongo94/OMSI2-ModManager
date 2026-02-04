import json
import os
import webview
from core.config import ConfigManager
from core.database import Mod, GameProfile
from core.hof_tools import HofTools
from core.importer import ModImporter
from core.installer import ModInstaller


class UILogger:
    def __init__(self, window):
        self._window = window

    def log(self, message, level="info", progress=None):
        try:
            sanitized_msg = json.dumps(str(message))
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
        self._window = window
        self._logger = UILogger(window)

    def get_config(self):
        return {
            "game_path": self.config_manager.game_path,
            "library_path": self.config_manager.library_path,
        }

    def browse_folder(self):
        if not self._window: return None
        folder = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return folder[0] if folder else None

    def set_game_path(self, path):
        return self.config_manager.set_game_path(path)

    def set_library_path(self, path):
        return self.config_manager.set_library_path(path)

    def get_mods_list(self):
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
        file_types = ('Архивы (*.zip;*.7z;*.rar)', 'Все файлы (*.*)')
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)

        if result and result[0]:
            filepath = result[0]
            importer = ModImporter(self.config_manager, self._logger)
            preview_data = importer.step1_prepare_preview(filepath)
            return preview_data
        return None

    def import_mod_step2(self, preview_data):
        importer = ModImporter(self.config_manager, self._logger)
        success = importer.step2_confirm_import(preview_data)
        return success

    def cancel_import(self, temp_path):
        importer = ModImporter(self.config_manager, self._logger)
        importer.cancel_import(temp_path)

    def toggle_mod(self, mod_id):
        session = self.config_manager.session
        mod = session.query(Mod).get(mod_id)
        if not mod:
            return {"status": "error", "message": "Mod not found"}
        current_state = mod.is_enabled

        installer = ModInstaller(self.config_manager, self._logger)
        success, msg = installer.toggle_mod(mod_id, not current_state)

        if success:
            return {"status": "success", "message": msg}
        return {"status": "error", "message": msg}

    # --- НОВАЯ ФУНКЦИЯ УДАЛЕНИЯ ---
    def delete_mod(self, mod_id):
        installer = ModInstaller(self.config_manager, self._logger)
        success, msg = installer.delete_mod_permanently(mod_id)
        return {"status": "success" if success else "error", "message": msg}

    # -------------------------------

    def get_conflicts(self):
        session = self.config_manager.session
        enabled_mods = session.query(Mod).filter_by(is_enabled=True).order_by(Mod.priority).all()

        file_map = {}
        for mod in enabled_mods:
            for f in mod.files:
                path = f.target_game_path
                if not path: continue
                path = path.replace("\\", "/").lower()
                if path.startswith("fonts/"):
                    continue
                if path not in file_map:
                    file_map[path] = []
                file_map[path].append(mod)

        conflicting_mod_ids = set()
        for path, mods_list in file_map.items():
            if len(mods_list) > 1:
                for m in mods_list:
                    conflicting_mod_ids.add(m.id)

        result = []
        for mod in enabled_mods:
            if mod.id in conflicting_mod_ids:
                result.append({
                    "id": mod.id,
                    "name": mod.name,
                    "priority": mod.priority
                })
        return result

    def save_load_order(self, ordered_mod_ids):
        installer = ModInstaller(self.config_manager, self._logger)
        session = self.config_manager.session

        # Обновляем приоритеты
        for index, mod_id in enumerate(ordered_mod_ids):
            mod = session.query(Mod).get(mod_id)
            if mod:
                mod.priority = index

        session.commit()
        success, msg = installer.sync_state()
        return {"status": "success" if success else "error", "message": msg}

    def get_hof_data(self):
        tools = HofTools(self.config_manager, self._logger)
        return {
            "library_hofs": tools.get_library_hofs(),
            "buses": tools.scan_for_buses()
        }

    def scan_game_hofs(self):
        tools = HofTools(self.config_manager, self._logger)
        return tools.scan_existing_game_hofs()

    def import_game_hofs(self, hof_list):
        tools = HofTools(self.config_manager, self._logger)
        count = tools.import_game_hofs(hof_list)
        return {"status": "success", "message": f"Импортировано {count} файлов."}

    def _save_current_profile(self):
        """Сохраняет текущее состояние модов в профиль текущей папки"""
        current_path = self.config_manager.game_path
        if not current_path: return

        session = self.config_manager.session
        mods = session.query(Mod).all()

        # Собираем словарь {id: {enabled, prio}}
        state_data = {}
        for m in mods:
            if m.is_enabled or m.priority > 0:
                state_data[m.id] = {
                    "e": m.is_enabled,
                    "p": m.priority
                }

        json_str = json.dumps(state_data)

        # Записываем в БД
        profile = session.query(GameProfile).get(current_path)
        if not profile:
            profile = GameProfile(game_path=current_path)
            session.add(profile)

        profile.mods_state_json = json_str
        session.commit()

    def _load_profile(self, new_path):
        """Загружает состояние модов для новой папки"""
        session = self.config_manager.session
        profile = session.query(GameProfile).get(new_path)

        mods = session.query(Mod).all()

        if not profile:
            # Если профиля нет (новая папка), выключаем все моды
            for m in mods:
                m.is_enabled = False
                m.priority = 0
        else:
            # Если профиль есть, восстанавливаем
            state_data = json.loads(profile.mods_state_json)
            for m in mods:
                # Ключи в JSON это строки, приводим к int
                m_id_str = str(m.id)
                if m_id_str in state_data:
                    data = state_data[m_id_str]
                    m.is_enabled = data["e"]
                    m.priority = data["p"]
                else:
                    m.is_enabled = False
                    m.priority = 0

        session.commit()

    def switch_game_folder(self):
        """Вызывается из UI по кнопке смены папки"""
        if not self._window: return

        # 1. Спрашиваем новую папку
        folder = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not folder or not folder[0]: return {"status": "cancel"}
        new_path = folder[0]

        # Проверка на omsi.exe
        if not os.path.exists(os.path.join(new_path, "Omsi.exe")):
            return {"status": "error", "message": "В этой папке нет Omsi.exe!"}

        if new_path == self.config_manager.game_path:
            return {"status": "cancel"}

        # 2. Сохраняем состояние старой папки
        self._save_current_profile()

        # 3. Меняем путь в конфиге
        self.config_manager.set_game_path(new_path)

        # 4. Загружаем состояние новой папки
        self._load_profile(new_path)

        return {
            "status": "success",
            "new_path": new_path,
            "message": "Папка игры изменена. Список модов обновлен."
        }

    def install_hofs(self, hof_ids, bus_names):
        tools = HofTools(self.config_manager, self._logger)
        success, msg = tools.install_hofs_to_buses(hof_ids, bus_names)
        return {"status": "success" if success else "warning", "message": msg}

    # НОВЫЙ МЕТОД
    def uninstall_all_hofs(self):
        tools = HofTools(self.config_manager, self._logger)
        success, msg = tools.uninstall_all_hofs()
        return {"status": "success", "message": msg}


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
    api.set_window(window)
    webview.start(debug=False)