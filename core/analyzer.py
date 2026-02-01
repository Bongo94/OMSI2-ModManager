import os
from pathlib import Path
from core.database import ModType


class ModAnalyzer:
    """
    Класс анализирует распакованную папку и определяет:
    1. Тип мода.
    2. Где находится 'Корневая папка'.
    3. Какие папки являются 'скрытыми автобусами' (лежат в корне, но без папки Vehicles).
    """

    # Папки, которые точно относятся к корню игры
    OMSI_ROOT_FOLDERS = {
        'vehicles', 'maps', 'sceneryobjects', 'splines',
        'fonts', 'texture', 'sound', 'inputs', 'gui',
        'drivers', 'ticketpacks', 'money', 'trains',
        'humans', 'addons'
    }

    def __init__(self, mod_path):
        self.mod_path = Path(mod_path)
        self.structure = {
            'type': ModType.UNKNOWN,
            'root_path': None,
            'hof_files': [],
            'implicit_buses': [],  # Список папок, которые надо закинуть в Vehicles
            'is_flat_bus': False
        }

    def analyze(self):
        self._find_hof_files()

        # Поиск корня
        root_candidate, implicit_buses = self._find_omsi_root_smart()

        if root_candidate:
            self.structure['root_path'] = root_candidate
            self.structure['implicit_buses'] = implicit_buses
            self.structure['type'] = self._determine_type_by_content(root_candidate, implicit_buses)
        else:
            # Если совсем ничего не нашли, проверяем на "голый" автобус
            if self._is_bus_dir(self.mod_path):
                self.structure['type'] = ModType.BUS
                self.structure['is_flat_bus'] = True
                self.structure['root_path'] = self.mod_path
            else:
                self.structure['type'] = ModType.UNKNOWN

        return self.structure

    def _find_hof_files(self):
        for path in self.mod_path.rglob('*.hof'):
            try:
                rel_path = path.relative_to(self.mod_path)
                self.structure['hof_files'].append(str(rel_path))
            except:
                pass

    def _is_bus_dir(self, path):
        """Проверяет, похоже ли содержимое папки на автобус (есть Model + Sound)"""
        has_model = False
        has_sound = False
        if not path.is_dir(): return False
        try:
            for item in path.iterdir():
                if item.is_dir():
                    if item.name.lower() == 'model': has_model = True
                    if item.name.lower() == 'sound': has_sound = True
        except:
            pass
        return has_model and has_sound

    def _find_omsi_root_smart(self):
        """
        Ищет корень, учитывая и стандартные папки, и папки-автобусы, лежащие рядом.
        Возвращает (Path root, List[str] implicit_buses)
        """
        max_score = 0
        best_root = None
        best_buses = []

        # Сканируем в глубину до 3 уровней
        for root, dirs, files in os.walk(self.mod_path):
            current_path = Path(root)
            # Защита от глубокого ухода
            try:
                if len(current_path.relative_to(self.mod_path).parts) > 3:
                    continue
            except:
                continue

            score = 0
            current_buses = []

            # 1. Проверяем наличие стандартных папок (Fonts, Vehicles, Maps...)
            for d in dirs:
                d_lower = d.lower()
                if d_lower in self.OMSI_ROOT_FOLDERS:
                    score += 2  # Стандартная папка — хороший знак
                    if d_lower == 'vehicles': score += 5
                    if d_lower == 'maps': score += 5

                # 2. Проверяем, не является ли папка "скрытым автобусом"
                # (То есть внутри неё есть Model/Sound, но сама она не Vehicles)
                elif self._is_bus_dir(current_path / d):
                    score += 3
                    current_buses.append(d)

            # Если мы нашли хоть что-то значимое
            if score > max_score:
                max_score = score
                best_root = current_path
                best_buses = current_buses

            # Если score одинаковый, предпочитаем тот путь, который короче (ближе к началу)
            elif score == max_score and score > 0:
                if best_root and len(str(current_path)) < len(str(best_root)):
                    best_root = current_path
                    best_buses = current_buses

        if max_score > 0:
            return best_root, best_buses

        return None, []

    def _determine_type_by_content(self, root_path, implicit_buses):
        has_vehicles = (root_path / 'vehicles').exists() or (root_path / 'Vehicles').exists() or len(implicit_buses) > 0
        has_maps = (root_path / 'maps').exists() or (root_path / 'Maps').exists()

        if has_vehicles and has_maps: return ModType.MIXED
        if has_vehicles: return ModType.BUS
        if has_maps: return ModType.MAP

        # Проверка на Scenery/Splines
        for folder in ['Sceneryobjects', 'Splines', 'Texture', 'Fonts']:
            if (root_path / folder).exists() or (root_path / folder.lower()).exists():
                return ModType.SCENERY

        return ModType.UNKNOWN