import os
from pathlib import Path


def print_smart_tree(path_to_scan, depth=0, max_depth=3):
    path = Path(path_to_scan)
    if depth == 0:
        print(f"\n📦 КОРЕНЬ: {path.absolute()}")
        print("—" * 60)

    try:
        items = sorted(list(path.iterdir()), key=lambda x: (x.is_file(), x.name))
    except PermissionError:
        return

    dirs = [i for i in items if i.is_dir()]
    files = [i for i in items if i.is_file()]

    indent = "  " * depth

    # 1. Показываем файлы в текущей папке (только уникальные расширения, чтобы не спамить)
    if files:
        exts = set(f.suffix.lower() for f in files if f.suffix)
        files_str = f"{len(files)} файл(ов) {list(exts)}"
        print(f"{indent}  📄 {files_str}")

    # 2. Логика для папок
    if not dirs:
        return

    # Если мы глубоко или папок мало — выводим всё
    # Если папок много (больше 3) — выводим только ОДНУ для примера
    if len(dirs) > 11 and depth > 0:
        example_dir = dirs[0]
        print(f"{indent}  📁 [{example_dir.name}] (Пример: 1 из {len(dirs)} похожих папок)")
        if depth < max_depth:
            print_smart_tree(example_dir, depth + 1, max_depth)
    else:
        for d in dirs:
            print(f"{indent}  📁 [{d.name}]")
            if depth < max_depth:
                print_smart_tree(d, depth + 1, max_depth)


# --- ЗАПУСК ---
# 1. Проверь на папке с игрой
# target_omsi = r'D:\Games\OMSI 2 Steam Edition'
# if os.path.exists(target_omsi):
#     print("СТРУКТУРА ИГРЫ:")
#     print_smart_tree(target_omsi)

# 2. Проверь на папке с модом (распакованным)
target_mod = r'D:\omsitemp\3mod'
if os.path.exists(target_mod):
    print("\nСТРУКТУРА МОДА:")
    print_smart_tree(target_mod)