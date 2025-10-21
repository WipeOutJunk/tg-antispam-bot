#!/bin/bash
set -e

echo "🚀 Развёртывание Anti-Spam Telegram Bot"

# Проверка app/.env
if [ ! -f app/.env ]; then
    echo "Файл app/.env не найден!"
    exit 1
fi

# Создание директорий
mkdir -p logs

# Первый запуск - копируем ru_curse_words.txt в volume
if [ ! "$(docker volume ls -q -f name=bot-words)" ]; then
    echo "Создание volume для словарей..."
    docker volume create bot-words
    
    # Временный контейнер для копирования файла
    docker run --rm -v bot-words:/data -v $(pwd):/host alpine sh -c "cp /host/ru_curse_words.txt /data/"
    echo "Файл ru_curse_words.txt скопирован в volume"
fi

# Остановка старого контейнера
echo "🛑 Остановка старых контейнеров..."
docker-compose down 2>/dev/null || true

# Сборка и запуск
echo "🔨 Сборка образа..."
docker-compose build

echo "▶️  Запуск бота..."
docker-compose up -d

# Проверка статуса
sleep 3
docker-compose ps
docker-compose logs --tail=20

echo ""
echo "✅ Бот запущен!"
echo "📊 Volumes:"
docker volume ls | grep bot
