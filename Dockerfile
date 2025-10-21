# Используем официальный образ Python
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

ENV DATABASE_URL=sqlite:///./data/bot.db
# Открываем порт (если планируете веб-интерфейс)
# EXPOSE 8000
# Запускаем бота
CMD ["python", "main.py"]
