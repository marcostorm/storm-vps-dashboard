#!/usr/bin/env bash
# Deploy seguro para lojas Storm Commerce.
# Uso: ./scripts/deploy.sh <loja> [tag]
#   loja: nome da loja (ex: loja-demo)
#   tag:  versão da imagem (padrão: data/hora atual)
#
# O script:
#   1. Faz backup do banco antes de qualquer mudança
#   2. Constrói a imagem com tag versionada
#   3. Testa a imagem em container efêmero
#   4. Faz swap do container em produção
#   5. Verifica saúde via HTTP
#   6. Reverte automaticamente se falhar
set -euo pipefail

LOJA="${1:-}"
TAG="${2:-$(date +%Y%m%d-%H%M)}"
IMAGE="storm-commerce"
LOJA_DIR="/opt/stormlab/lojas/${LOJA}"
HEALTH_URL="http://localhost:3000"
HEALTH_RETRIES=20
HEALTH_INTERVAL=3   # segundos

# ─── Validação ────────────────────────────────────────────────────────────────
if [[ -z "$LOJA" ]]; then
  echo "Uso: $0 <loja> [tag]"
  echo "Exemplo: $0 loja-demo"
  exit 1
fi

if [[ ! -d "$LOJA_DIR" ]]; then
  echo "❌ Loja não encontrada: $LOJA_DIR"
  exit 1
fi

echo "▶ Deploy: ${LOJA}  imagem: ${IMAGE}:${TAG}"
echo "  Diretório: ${LOJA_DIR}"
echo ""

# ─── 1. Backup do banco ────────────────────────────────────────────────────────
BACKUP_DIR="/opt/stormlab/backups/${LOJA}"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/pre-deploy-${TAG}.sql.gz"

echo "1/5 Backup do banco..."
DB_CONTAINER="${LOJA}-database-1"
DB_NAME=$(docker exec "$DB_CONTAINER" printenv POSTGRES_DB 2>/dev/null || grep DB_NAME "${LOJA_DIR}/.env" | cut -d= -f2)
DB_USER=$(docker exec "$DB_CONTAINER" printenv POSTGRES_USER 2>/dev/null || echo "postgres")

docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" \
  | gzip > "$BACKUP_FILE"
echo "   ✓ Backup salvo em ${BACKUP_FILE} ($(du -sh "$BACKUP_FILE" | cut -f1))"

# Mantém apenas os 10 backups mais recentes
ls -t "${BACKUP_DIR}"/pre-deploy-*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm --
echo ""

# ─── 2. Build da imagem ────────────────────────────────────────────────────────
echo "2/5 Build da imagem ${IMAGE}:${TAG}..."
# BUILD_CONTEXT = diretório que contém o Dockerfile de storm-commerce.
# Default assume layout atual (/opt/stormlab/storm-commerce) e aceita override
# via env var pra multi-produto (lawork, paxiuba) sem editar o script.
BUILD_CONTEXT="${STORM_COMMERCE_DIR:-/opt/stormlab/storm-commerce}"

if [[ ! -f "${BUILD_CONTEXT}/Dockerfile" ]]; then
  echo "❌ Dockerfile não encontrado em ${BUILD_CONTEXT}/Dockerfile"
  echo "   defina STORM_COMMERCE_DIR apontando pro diretório que contém o Dockerfile"
  exit 1
fi

docker build -t "${IMAGE}:${TAG}" "$BUILD_CONTEXT" 2>&1 | tail -5
echo "   ✓ Imagem construída"
echo ""

# ─── 3. Smoke test ────────────────────────────────────────────────────────────
echo "3/5 Smoke test (container efêmero)..."
TEST_RESULT=$(docker run --rm \
  --entrypoint sh \
  "${IMAGE}:${TAG}" \
  -c "node -e \"require('/app/node_modules/@evershop/evershop/dist/bin/lib/app.js')\" 2>&1 | head -3" 2>&1 || true)

# Verifica se a imagem pelo menos inicia o Node sem erro de sintaxe
docker run --rm \
  --entrypoint node \
  "${IMAGE}:${TAG}" \
  --check /app/node_modules/@evershop/evershop/dist/bin/server.js 2>/dev/null \
  || { echo "   ❌ Smoke test falhou — deploy abortado"; docker rmi "${IMAGE}:${TAG}" 2>/dev/null; exit 1; }

echo "   ✓ Imagem válida"
echo ""

# ─── 4. Swap do container ─────────────────────────────────────────────────────
echo "4/5 Swap do container em produção..."
PREV_TAG=$(docker inspect "${LOJA}-app-1" \
  --format '{{index .Config.Image}}' 2>/dev/null \
  | sed "s|${IMAGE}:||" || echo "latest")

# Atualiza a imagem no compose e sobe o novo container
cd "$LOJA_DIR"
sed -i "s|image: ${IMAGE}:.*|image: ${IMAGE}:${TAG}|" docker-compose.yml
docker compose up -d app 2>&1 | grep -E "Starting|Started|Recreating|Recreated" || true
echo "   ✓ Container iniciado com ${IMAGE}:${TAG}"
echo ""

# ─── 5. Verificação de saúde ──────────────────────────────────────────────────
echo "5/5 Verificação de saúde..."
CONTAINER="${LOJA}-app-1"
HEALTHY=false

for i in $(seq 1 $HEALTH_RETRIES); do
  STATUS=$(docker exec "$CONTAINER" \
    wget -qO- --spider "${HEALTH_URL}" 2>&1 | grep -c "200 OK" || \
    curl -sf -o /dev/null -w "%{http_code}" "${HEALTH_URL}" 2>/dev/null || echo "0")

  if [[ "$STATUS" == "200" ]] || \
     docker exec "$CONTAINER" wget -q --spider "${HEALTH_URL}" 2>/dev/null; then
    HEALTHY=true
    break
  fi
  echo "   aguardando... (${i}/${HEALTH_RETRIES})"
  sleep $HEALTH_INTERVAL
done

if [[ "$HEALTHY" == "false" ]]; then
  echo ""
  echo "❌ Saúde não confirmada após $((HEALTH_RETRIES * HEALTH_INTERVAL))s — revertendo para ${IMAGE}:${PREV_TAG}..."
  sed -i "s|image: ${IMAGE}:${TAG}|image: ${IMAGE}:${PREV_TAG}|" docker-compose.yml
  docker compose up -d app 2>&1 | grep -E "Starting|Started|Recreating|Recreated" || true
  docker rmi "${IMAGE}:${TAG}" 2>/dev/null || true
  echo "↩ Revertido para ${IMAGE}:${PREV_TAG}"
  exit 1
fi

# ─── Sucesso ──────────────────────────────────────────────────────────────────
echo "   ✓ Aplicação respondendo"
echo ""
echo "✅ Deploy concluído!"
echo "   Loja:   ${LOJA}"
echo "   Imagem: ${IMAGE}:${TAG}"
echo "   Backup: ${BACKUP_FILE}"
echo ""

# Remove imagem antiga se diferente de latest (mantém 3 versões)
if [[ "$PREV_TAG" != "latest" && "$PREV_TAG" != "$TAG" ]]; then
  echo "   (mantendo ${IMAGE}:${PREV_TAG} como rollback)"
fi

# Lista versões disponíveis para rollback
echo "Versões disponíveis para rollback:"
docker images "$IMAGE" --format "  {{.Tag}}\t{{.CreatedAt}}" | grep -v "^  latest" | head -5
