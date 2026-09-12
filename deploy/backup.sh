#!/bin/sh
set -eu

if [ "$#" -ne 3 ]; then
    echo "uso: backup.sh DIRETORIO_BACKUP MEDIA_ROOT PGSERVICE" >&2
    exit 2
fi

backup_dir=$1
media_root=$2
pg_service=$3
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
destination="$backup_dir/$timestamp"
mkdir -p "$destination"
pg_dump --dbname="service=$pg_service" --format=custom --file="$destination/database.dump"
tar -C "$media_root" -czf "$destination/media.tar.gz" .
sha256sum "$destination/database.dump" "$destination/media.tar.gz" > "$destination/SHA256SUMS"
echo "$destination"
