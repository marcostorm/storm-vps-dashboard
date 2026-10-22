#!/usr/bin/env bash
# Backup diário de todas as lojas Storm Commerce.
# Instalação: crontab -e → 0 3 * * * /opt/stormlab/scripts/backup-db.sh >> /var/log/storm-backup.log 2>&1
set -euo pipefail

LOJAS_DIR="/opt/stormlab/lojas"
BACKUP_BASE="/opt/stormlab/backups"
RETENTION_DAYS=14
DATE=$(date +%Y%m%d-%H%M)
ERRORS=0

for loja_dir in "${LOJAS_DIR}"/*/; do
  loja=$(basename "$loja_dir")
  DB_CONTAINER="${loja}-database-1"

  if ! docker ps --format "{{.Names}}" | grep -q "^${DB_CONTAINER}$"; then
    echo "⚠ ${loja}: container do banco não está rodando, pulando"
    continue
  fi

  BACKUP_DIR="${BACKUP_BASE}/${loja}"
  mkdir -p "$BACKUP_DIR"

  DB_NAME=$(grep "^DB_NAME=" "${loja_dir}/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "")
  DB_USER=$(grep "^DB_USER=" "${loja_dir}/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "postgres")
  DB_NAME="${DB_NAME:-${loja//-/_}}"

  R2_BUCKET=$(grep "^R2_BUCKET=" "${loja_dir}/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "")
  HEALTHCHECK_URL=$(grep "^HEALTHCHECK_PING_URL=" "${loja_dir}/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' || echo "")

  BACKUP_FILE="${BACKUP_DIR}/daily-${DATE}.sql.gz"

  if docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" \
      | gzip > "$BACKUP_FILE" 2>/dev/null; then
    SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
    echo "✓ ${loja}: backup local (${SIZE})"

    # Upload para R2
    if [[ -n "$R2_BUCKET" ]] && command -v rclone &>/dev/null; then
      if rclone copy "$BACKUP_FILE" "r2:${R2_BUCKET}/${loja}/" 2>/dev/null; then
        echo "✓ ${loja}: upload R2 ok"
      else
        echo "⚠ ${loja}: upload R2 falhou (backup local mantido)"
        ERRORS=$((ERRORS + 1))
      fi
    fi

    # Ping healthchecks.io (não bloqueante, mas registra falhas)
    if [[ -n "$HEALTHCHECK_URL" ]]; then
      if curl -fsS --retry 5 --retry-delay 5 --max-time 30 \
          "$HEALTHCHECK_URL" > /dev/null 2>&1; then
        echo "✓ ${loja}: ping healthcheck ok"
      else
        echo "⚠ ${loja}: ping healthcheck falhou (backup ok, alerta espúrio possível)"
      fi
    fi
  else
    echo "❌ ${loja}: falha no backup"
    rm -f "$BACKUP_FILE"
    ERRORS=$((ERRORS + 1))
    if [[ -n "$HEALTHCHECK_URL" ]]; then
      curl -fsS --retry 3 --max-time 30 "${HEALTHCHECK_URL}/fail" > /dev/null 2>&1 || true
    fi
  fi

  # Remove backups locais mais antigos que RETENTION_DAYS dias
  find "$BACKUP_DIR" -name "daily-*.sql.gz" -mtime +${RETENTION_DAYS} -delete
done

# Sumário
TOTAL=$(find "$BACKUP_BASE" -name "daily-${DATE}.sql.gz" | wc -l)
echo ""
echo "Backup concluído: ${TOTAL} loja(s), ${ERRORS} erro(s)"
[[ $ERRORS -gt 0 ]] && exit 1 || exit 0
