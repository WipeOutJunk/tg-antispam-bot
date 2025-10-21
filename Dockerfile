FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем структуру проекта
COPY app/ ./app/
COPY main.py .

# Явно копируем ML модель
COPY ml_models/ ./ml_models/

# Копируем файл словаря в правильное место
COPY ru_curse_words.txt ./data/

ENV DATABASE_URL=sqlite:///./data/bot.db

CMD ["python", "main.py"]
