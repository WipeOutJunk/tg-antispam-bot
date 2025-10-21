#!/bin/bash
# restore-db.sh

BACKUP_FILE="$1"

docker run --rm \
    -v bot-data:/data \
    -v "$(pwd)/$(dirname $BACKUP_FILE)":/backup \
    alpine \
    sh -c "cp /backup/$(basename $BACKUP_FILE) /data/bot.db"

echo "✅ Database restored from $BACKUP_FILE"
