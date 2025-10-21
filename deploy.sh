#!/bin/bash
set -e

echo "🚀 Развёртывание Anti-Spam Telegram Bot"

# Проверка app/.env
if [ ! -f app/.env ]; then
    echo "❌ Файл app/.env не найден!"
    exit 1
fi

# Создание директорий
mkdir -p logs

# Проверка существования volumes
if [ ! "$(docker volume ls -q -f name=bot-data)" ]; then
    echo "📦 Volume bot-data будет создан при первом запуске"
fi

# Остановка БЕЗ удаления volumes
echo "🛑 Остановка старых контейнеров..."
docker-compose down 2>/dev/null || true

# Сборка (данные в volume сохранятся)
echo "🔨 Сборка образа..."
docker-compose build

echo "▶️ Запуск бота..."
docker-compose up -d

# Проверка
sleep 3
docker-compose ps
docker-compose logs --tail=20

echo ""
echo "✅ Бот запущен!"
echo "📊 Volumes:"
docker volume ls | grep bot
