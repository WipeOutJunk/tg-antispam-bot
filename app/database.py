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
from .models.base import Base
from .models.chat import Chat
from .models.user import User
from .models.warning import Warning
from .models.ban import Ban
from .models.spam_words import SpamWord
from .models.spam_link import SpamLink
from .models.message_log import MessageLog
from .models.statistic import Statistic
from .models.admin_notification import AdminNotification, AdminNotificationMessage
from .models.allowed_adder import AllowedAdder
from .models.profanity_word import ProfanityWord
models = {
    "Chat": Chat,
    "User": User,
    "Warning": Warning,
    "Ban": Ban,
    "SpamWord": SpamWord,
    "SpamLink": SpamLink,
    "MessageLog": MessageLog,
    "Statistic": Statistic,
    "AdminNotification": AdminNotification,
    "AdminNotificationMessage": AdminNotificationMessage,
    "AllowedAdder": AllowedAdder,
    "ProfanityWord": ProfanityWord,

}


def init_db():
    # Импортируем все модели, чтобы DeclarativeBase их зарегистрировал
    from .models import chat, user, warning, ban, spam_words, spam_link, message_log, statistic, admin_notification, allowed_adder, profanity_word


    # Создаём все таблицы
    Base.metadata.create_all(bind=engine)
