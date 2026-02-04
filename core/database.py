from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, inspect, text, Text, \
    UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
import enum

Base = declarative_base()


# --- ПЕРЕЧИСЛЕНИЯ ---
class ModType(enum.Enum):
    UNKNOWN = "unknown"
    BUS = "bus"
    MAP = "map"
    SCENERY = "scenery"
    REPAINT = "repaint"
    MIXED = "mixed"
    HOF_ONLY = "hof_only"


# --- МОДЕЛИ ---

class GameProfile(Base):
    __tablename__ = 'game_profiles'
    game_path = Column(String, primary_key=True)
    mods_state_json = Column(Text, default="{}")


class Mod(Base):
    __tablename__ = 'mods'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    mod_type = Column(Enum(ModType), default=ModType.UNKNOWN)
    storage_path = Column(String, unique=True, nullable=False)
    is_enabled = Column(Boolean, default=False)
    priority = Column(Integer, default=0)
    install_date = Column(DateTime, default=datetime.now)
    files = relationship("ModFile", back_populates="mod", cascade="all, delete-orphan")
    hof_files = relationship("HofFile", back_populates="mod", cascade="all, delete-orphan")


class ModFile(Base):
    __tablename__ = 'mod_files'
    id = Column(Integer, primary_key=True)
    mod_id = Column(Integer, ForeignKey('mods.id'))
    source_rel_path = Column(String, nullable=False)
    target_game_path = Column(String, nullable=True)
    is_hof = Column(Boolean, default=False)
    file_hash = Column(String)
    mod = relationship("Mod", back_populates="files")


class HofFile(Base):
    __tablename__ = 'hof_files'
    id = Column(Integer, primary_key=True)
    mod_id = Column(Integer, ForeignKey('mods.id'))
    filename = Column(String, nullable=False)
    full_source_path = Column(String, nullable=False)
    description = Column(String, nullable=True)
    mod = relationship("Mod", back_populates="hof_files")
    installs = relationship("HofInstall", back_populates="hof_file", cascade="all, delete-orphan")


class HofInstall(Base):
    __tablename__ = 'hof_installs'
    id = Column(Integer, primary_key=True)
    hof_file_id = Column(Integer, ForeignKey('hof_files.id'))
    bus_folder_name = Column(String, nullable=False)
    game_rel_path = Column(String, nullable=False)
    backup_path = Column(String, nullable=True)
    install_date = Column(DateTime, default=datetime.now)
    hof_file = relationship("HofFile", back_populates="installs")


class InstalledFile(Base):
    __tablename__ = 'game_file_state'
    id = Column(Integer, primary_key=True)
    game_path = Column(String, nullable=False)
    root_path = Column(String, nullable=False, default="")
    active_mod_id = Column(Integer, ForeignKey('mods.id'))
    backup_path = Column(String, nullable=True)
    original_hash = Column(String, nullable=True)

    # Теперь уникальность проверяется по ПАРЕ (путь файла + папка игры)
    __table_args__ = (UniqueConstraint('game_path', 'root_path', name='_game_file_uc'),)


class AppSetting(Base):
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(String)


# --- ИНИЦИАЛИЗАЦИЯ И МИГРАЦИЯ ---

def init_db(db_path='manager.db'):
    # Добавляем таймаут, чтобы SQLite подождал, если база занята
    engine = create_engine(
        f'sqlite:///{db_path}',
        echo=False,
        connect_args={'timeout': 30}
    )

    # 1. Сначала создаем таблицы (те, которых еще нет)
    Base.metadata.create_all(engine)

    # 2. Миграции через активное соединение
    with engine.connect() as conn:
        # ВАЖНО: передаем 'conn' вместо 'engine' в inspect
        inspector = inspect(conn)

        # Проверяем и добавляем колонки в mods
        cols_mods = [c['name'] for c in inspector.get_columns('mods')]
        if 'priority' not in cols_mods:
            conn.execute(text("ALTER TABLE mods ADD COLUMN priority INTEGER DEFAULT 0"))

        # Проверяем и добавляем колонки в game_file_state
        cols_inst = [c['name'] for c in inspector.get_columns('game_file_state')]
        if 'root_path' not in cols_inst:
            conn.execute(text("ALTER TABLE game_file_state ADD COLUMN root_path VARCHAR DEFAULT ''"))

        # Лечение пустых root_path
        res = conn.execute(text("SELECT value FROM settings WHERE key='game_path'")).fetchone()
        if res and res[0]:
            current_path = res[0]
            conn.execute(
                text("UPDATE game_file_state SET root_path = :p WHERE root_path = '' OR root_path IS NULL"),
                {"p": current_path}
            )

        # Проверяем и добавляем колонки в hof_installs
        cols_hof = [c['name'] for c in inspector.get_columns('hof_installs')]
        if 'game_rel_path' not in cols_hof:
            conn.execute(text("ALTER TABLE hof_installs ADD COLUMN game_rel_path VARCHAR DEFAULT 'legacy'"))
        if 'backup_path' not in cols_hof:
            conn.execute(text("ALTER TABLE hof_installs ADD COLUMN backup_path VARCHAR"))

        # Сохраняем все изменения миграции
        conn.commit()

    Session = sessionmaker(bind=engine)
    return Session()