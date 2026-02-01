import os
import appdirs
from core.database import init_db, AppSetting


class ConfigManager:
    def __init__(self):
        # Папка данных приложения в AppData (или ~/.local)
        self.app_data_dir = appdirs.user_data_dir("OMSI2_ModManager", "OMSI_Tools")
        os.makedirs(self.app_data_dir, exist_ok=True)

        # Инициализация БД
        self.db_path = os.path.join(self.app_data_dir, "manager_v1.db")
        self.session = init_db(self.db_path)

        # Загрузка кэшированных путей
        self.game_path = self._get_setting("game_path")
        self.library_path = self._get_setting("library_path")

    def _get_setting(self, key):
        setting = self.session.query(AppSetting).filter_by(key=key).first()
        return setting.value if setting else None

    def _set_setting(self, key, value):
        setting = self.session.query(AppSetting).filter_by(key=key).first()
        if not setting:
            setting = AppSetting(key=key)
            self.session.add(setting)
        setting.value = value
        self.session.commit()

    def set_game_path(self, path):
        if os.path.exists(path) and os.path.exists(os.path.join(path, "Omsi.exe")):
            self._set_setting("game_path", path)
            self.game_path = path
            return True, "Путь к OMSI 2 сохранен!"
        return False, "Не найдет Omsi.exe в указанной папке."

    def set_library_path(self, path):
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except:
                return False, "Не удалось создать папку."
        self._set_setting("library_path", path)
        self.library_path = path
        return True, "Библиотека модов настроена."