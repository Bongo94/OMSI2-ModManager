from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, inspect, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
import enum

Base = declarative_base()


# --- ПЕРЕЧИСЛЕНИЯ (ENUMS) ---

class ModType(enum.Enum):
    """Типы модов для классификации"""
    UNKNOWN = "unknown"
    BUS = "bus"
    MAP = "map"
    SCENERY = "scenery"  # Объекты/Сплайны
    REPAINT = "repaint"  # Перекраски
    MIXED = "mixed"  # Карта + Автобус + еще что-то (как Борисов)
    HOF_ONLY = "hof_only"  # Только хоф файл


# --- МОДЕЛИ ---

class Mod(Base):
    """Установленный мод (архив, распакованный в библиотеку)"""
    __tablename__ = 'mods'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    mod_type = Column(Enum(ModType), default=ModType.UNKNOWN)
    storage_path = Column(String, unique=True, nullable=False)
    is_enabled = Column(Boolean, default=False)

    # НОВОЕ: Приоритет загрузки (чем больше число, тем важнее мод)
    priority = Column(Integer, default=0)

    install_date = Column(DateTime, default=datetime.now)
    files = relationship("ModFile", back_populates="mod", cascade="all, delete-orphan")
    hof_files = relationship("HofFile", back_populates="mod", cascade="all, delete-orphan")


class ModFile(Base):
    """
    Физический файл внутри мода.
    Хранит информацию о том, где он лежит в библиотеке и куда должен попасть в игру.
    """
    __tablename__ = 'mod_files'

    id = Column(Integer, primary_key=True)
    mod_id = Column(Integer, ForeignKey('mods.id'))

    # Путь файла внутри папки мода в библиотеке (например: "Vehicles/MAN/model.cfg")
    source_rel_path = Column(String, nullable=False)

    # Планируемый путь в игре (например: "Vehicles/MAN/model.cfg")
    # Если это HOF файл, здесь может быть пусто или дефолтный путь
    target_game_path = Column(String, nullable=True)

    # Тип файла (обычный, конфиг, или hof)
    is_hof = Column(Boolean, default=False)

    file_hash = Column(String)  # MD5 хеш

    mod = relationship("Mod", back_populates="files")


class HofFile(Base):
    """
    Отдельный каталог найденных HOF файлов.
    Нужен, чтобы в UI быстро показать список всех доступных хофов для 'инжектора'.
    """
    __tablename__ = 'hof_files'

    id = Column(Integer, primary_key=True)
    mod_id = Column(Integer, ForeignKey('mods.id'))

    # Имя файла (например "Borisov.hof")
    filename = Column(String, nullable=False)

    # Полный путь к файлу внутри ModLibrary (чтобы мы могли его взять и скопировать)
    full_source_path = Column(String, nullable=False)

    # Описание (можно парсить первую строку файла, там часто пишут название депо)
    description = Column(String, nullable=True)

    mod = relationship("Mod", back_populates="hof_files")
    installs = relationship("HofInstall", back_populates="hof_file", cascade="all, delete-orphan")


class HofInstall(Base):
    """
    Таблица отслеживания: какой HOF куда был закинут.
    """
    __tablename__ = 'hof_installs'

    id = Column(Integer, primary_key=True)
    hof_file_id = Column(Integer, ForeignKey('hof_files.id'))

    # Имя папки автобуса в Vehicles, куда мы закинули этот файл (например "MAN_SD200")
    bus_folder_name = Column(String, nullable=False)

    install_date = Column(DateTime, default=datetime.now)

    hof_file = relationship("HofFile", back_populates="installs")


class InstalledFile(Base):
    """Таблица 'Журнал изменений'. Хранит, что мы поменяли в папке игры."""
    __tablename__ = 'game_file_state'

    id = Column(Integer, primary_key=True)

    # Относительный путь в игре (Vehicles/Man/sound.cfg)
    game_path = Column(String, unique=True, nullable=False)

    # ID мода, чей файл сейчас установлен (победитель в конфликте)
    active_mod_id = Column(Integer, ForeignKey('mods.id'))

    # Если мы заменили ОРИГИНАЛЬНЫЙ файл игры, здесь лежит путь к нашему бэкапу
    # (Например: X:/OMSI Library/Backups/sound.cfg_original_hash123)
    backup_path = Column(String, nullable=True)

    # Хеш оригинального файла (для проверки целостности при восстановлении)
    original_hash = Column(String, nullable=True)


class AppSetting(Base):
    """Настройки приложения"""
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(String)


# --- ИНИЦИАЛИЗАЦИЯ ---

def init_db(db_path='manager.db'):
    engine = create_engine(f'sqlite:///{db_path}', echo=False)

    # 1. Сначала создаем таблицы, если их нет (стандартный метод)
    Base.metadata.create_all(engine)

    # 2. Проверяем, нужна ли миграция (добавление колонки priority)
    inspector = inspect(engine)
    columns = [c['name'] for c in inspector.get_columns('mods')]

    if 'priority' not in columns:
        print("Migrating database: adding 'priority' column to 'mods' table...")
        with engine.connect() as conn:
            # SQLite позволяет добавлять колонки простой командой ALTER TABLE
            conn.execute(text("ALTER TABLE mods ADD COLUMN priority INTEGER DEFAULT 0"))
            conn.commit()
            print("Migration successful!")

    # 3. Создаем сессию
    Session = sessionmaker(bind=engine)
    return Session()