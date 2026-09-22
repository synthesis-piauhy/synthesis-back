#!/bin/sh
set -eu
umask 077

if [ "$#" -ne 3 ]; then
    echo "uso: backup.sh DIRETORIO_BACKUP MEDIA_ROOT PGSERVICE" >&2
    exit 2
fi

backup_dir=$1
media_root=$2
pg_service=$3
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
destination="$backup_dir/$timestamp"
mkdir -p "$backup_dir"
mkdir "$destination"
trap 'rm -rf -- "$destination"' EXIT
trap 'exit 1' HUP INT TERM
pg_dump --dbname="service=$pg_service" --format=custom --file="$destination/database.dump"
tar -C "$media_root" -czf "$destination/media.tar.gz" .
(cd "$destination" && sha256sum database.dump media.tar.gz > SHA256SUMS)
trap - EXIT HUP INT TERM
echo "$destination"
