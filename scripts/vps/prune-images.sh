#!/usr/bin/env bash
# Remove imagens antigas do storm-commerce, mantendo as últimas KEEP_TAGS.
# Instalação: crontab -e → 0 4 * * 0 /opt/stormlab/scripts/prune-images.sh >> /var/log/storm-prune.log 2>&1
set -euo pipefail

IMAGE="storm-commerce"
KEEP_TAGS="${1:-3}"

echo "=== $(date '+%Y-%m-%d %H:%M') — Pruning imagens ${IMAGE} ==="

# Lista tags ordenadas por data de criação (mais recente primeiro), exclui 'latest'
ALL_TAGS=$(docker images --format "{{.Tag}}" "$IMAGE" \
  | grep -v "^latest$" \
  | sort -r)

TOTAL=$(echo "$ALL_TAGS" | grep -c . || echo 0)

if [[ $TOTAL -le $KEEP_TAGS ]]; then
  echo "Nada a remover: ${TOTAL} tag(s), limite ${KEEP_TAGS}"
  exit 0
fi

TO_REMOVE=$(echo "$ALL_TAGS" | tail -n +$((KEEP_TAGS + 1)))
COUNT=$(echo "$TO_REMOVE" | grep -c . || echo 0)

for tag in $TO_REMOVE; do
  if docker rmi "${IMAGE}:${tag}" 2>/dev/null; then
    echo "  ✓ Removida: ${IMAGE}:${tag}"
  else
    echo "  ⚠ Em uso, pulando: ${IMAGE}:${tag}"
  fi
done

# Build cache — remove layers não referenciados por nenhuma imagem
FREED=$(docker builder prune -f --filter until=24h 2>/dev/null \
  | grep "Total reclaimed" | grep -oP '[\d.]+\s*\w+B' || echo "0B")

echo "  Cache liberado: ${FREED}"
echo "Pruning concluído: ${COUNT} imagem(ns) removida(s)"
