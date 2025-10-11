from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models.base import Base
import os

# Путь к SQLite-файлу (или URL для другой БД)
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./bot.db")

# Создаём движок
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False}  # для SQLite
)

# Создаём сессию
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

def init_db():
    # Импортируем все модели, чтобы DeclarativeBase их зарегистрировал
    from .models import chat, user, warning, ban, spam_words, spam_link, message_log, statistic


    # Создаём все таблицы
    Base.metadata.create_all(bind=engine)
