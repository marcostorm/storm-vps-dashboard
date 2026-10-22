#!/usr/bin/env bash
# Reverte uma loja para uma versão anterior da imagem.
# Uso: ./scripts/rollback.sh <loja> <tag>
#   lista tags disponíveis: docker images storm-commerce
set -euo pipefail

LOJA="${1:-}"
TAG="${2:-}"
IMAGE="storm-commerce"
LOJA_DIR="/opt/stormlab/lojas/${LOJA}"

if [[ -z "$LOJA" || -z "$TAG" ]]; then
  echo "Uso: $0 <loja> <tag>"
  echo ""
  echo "Tags disponíveis:"
  docker images "$IMAGE" --format "  {{.Tag}}\t{{.CreatedAt}}" | grep -v "^  latest"
  exit 1
fi

if ! docker image inspect "${IMAGE}:${TAG}" &>/dev/null; then
  echo "❌ Imagem ${IMAGE}:${TAG} não encontrada."
  echo ""
  echo "Tags disponíveis:"
  docker images "$IMAGE" --format "  {{.Tag}}\t{{.CreatedAt}}" | grep -v "^  latest"
  exit 1
fi

echo "↩ Rollback: ${LOJA} → ${IMAGE}:${TAG}"
cd "$LOJA_DIR"
sed -i "s|image: ${IMAGE}:.*|image: ${IMAGE}:${TAG}|" docker-compose.yml
docker compose up -d app 2>&1 | grep -E "Starting|Started|Recreating|Recreated" || true
echo "✅ Rollback concluído para ${IMAGE}:${TAG}"
