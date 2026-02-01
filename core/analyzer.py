import os
from pathlib import Path
from core.database import ModType


class ModAnalyzer:
    """
    Класс анализирует распакованную папку и определяет:
    1. Тип мода.
    2. Где находится 'Корневая папка' (которую надо совмещать с игрой).
    3. Список всех файлов и HOF файлов.
    """

    # Папки, которые точно относятся к корню игры
    OMSI_ROOT_FOLDERS = {
        'vehicles', 'maps', 'sceneryobjects', 'splines',
        'fonts', 'texture', 'sound', 'inputs', 'gui',
        'drivers', 'ticketpacks', 'money'
    }

    def __init__(self, mod_path):
        self.mod_path = Path(mod_path)
        self.structure = {
            'type': ModType.UNKNOWN,
            'root_path': None,  # Путь внутри мода, который является 'корнем'
            'hof_files': [],  # Список найденных HOF
            'is_flat_bus': False  # Флаг: если в корне сразу лежат папки Model/Sound (кривой мод)
        }

    def analyze(self):
        # 1. Сначала ищем HOF файлы по всему моду
        self._find_hof_files()

        # 2. Пытаемся найти корень игры
        root_candidate, depth = self._find_omsi_root()

        if root_candidate:
            self.structure['root_path'] = root_candidate
            self.structure['type'] = self._determine_type_by_content(root_candidate)
        else:
            # Если явного корня нет, проверяем, не является ли это "голым" автобусом
            if self._check_flat_bus_structure(self.mod_path):
                self.structure['type'] = ModType.BUS
                self.structure['is_flat_bus'] = True
                self.structure['root_path'] = self.mod_path
            else:
                self.structure['type'] = ModType.UNKNOWN

        return self.structure

    def _find_hof_files(self):
        for path in self.mod_path.rglob('*.hof'):
            # Сохраняем путь относительно корня мода
            rel_path = path.relative_to(self.mod_path)
            self.structure['hof_files'].append(str(rel_path))

    def _find_omsi_root(self):
        """
        Ищет папку, содержащую ключевые папки OMSI (Vehicles, Maps и т.д.)
        Возвращает (Path, depth)
        """
        # Сначала проверим сам корень
        if self._count_omsi_folders(self.mod_path) >= 1:
            return self.mod_path, 0

        # Если нет, идем вглубь (но не слишком глубоко)
        max_score = 0
        best_candidate = None

        for root, dirs, files in os.walk(self.mod_path):
            current_path = Path(root)
            # Защита от слишком глубокого поиска
            if len(current_path.relative_to(self.mod_path).parts) > 3:
                continue

            score = self._count_omsi_folders(current_path)

            # Если нашли Vehicles - это очень сильный сигнал
            for d in dirs:
                if d.lower() == 'vehicles':
                    score += 5
                if d.lower() == 'maps':
                    score += 3

            if score > max_score:
                max_score = score
                best_candidate = current_path

        if max_score > 0:
            return best_candidate, max_score
        return None, 0

    def _count_omsi_folders(self, path):
        count = 0
        try:
            for item in path.iterdir():
                if item.is_dir() and item.name.lower() in self.OMSI_ROOT_FOLDERS:
                    count += 1
        except:
            pass
        return count

    def _check_flat_bus_structure(self, path):
        """Проверяет, не лежат ли папки Model/Sound прямо здесь"""
        required = {'model', 'sound', 'script'}
        found = set()
        try:
            for item in path.iterdir():
                if item.is_dir() and item.name.lower() in required:
                    found.add(item.name.lower())
                # Или если есть .bus/.ovh файл прямо тут
                if item.is_file() and item.suffix.lower() in ['.bus', '.ovh']:
                    return True
        except:
            pass
        return len(found) >= 2

    def _determine_type_by_content(self, root_path):
        """Определяет тип на основе того, какие папки есть в найденном корне"""
        has_vehicles = (root_path / 'Vehicles').exists() or (root_path / 'vehicles').exists()
        has_maps = (root_path / 'maps').exists() or (root_path / 'Maps').exists()

        if has_vehicles and has_maps:
            return ModType.MIXED
        if has_vehicles:
            return ModType.BUS
        if has_maps:
            return ModType.MAP

        # Проверка на Scenery
        has_scenery = False
        for folder in ['Sceneryobjects', 'Splines', 'Texture']:
            if (root_path / folder).exists() or (root_path / folder.lower()).exists():
                has_scenery = True

        if has_scenery:
            return ModType.SCENERY

        return ModType.UNKNOWN