#!/bin/bash
# backup-db.sh

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

docker run --rm \
    -v bot-data:/data \
    -v "$(pwd)/$BACKUP_DIR":/backup \
    alpine \
    sh -c "cp /data/bot.db /backup/bot_${TIMESTAMP}.db"

echo "✅ Backup created: $BACKUP_DIR/bot_${TIMESTAMP}.db"
