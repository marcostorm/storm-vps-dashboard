#!/usr/bin/env bash
# Deploy / update do storm-vps-dashboard no VPS.
# Idempotente: primeira run faz setup (pede senha, cria .env);
# runs seguintes só puxam o main, rebuildam e reiniciam.
#
# Rodar no VPS como root:
#   bash /opt/stormlab/storm-vps-dashboard/scripts/vps/dashboard-deploy.sh
#
# Pré-requisitos: docker + docker compose + git + apache2-utils (pra htpasswd).

set -euo pipefail

REPO_URL="https://github.com/marcostorm/storm-vps-dashboard.git"
REPO_DIR="/opt/stormlab/storm-vps-dashboard"
RUN_DIR="/opt/stormlab/dashboard"
AUTH_USER="marcos"

log() { echo "[dashboard-deploy] $*"; }

# 1. apache2-utils (htpasswd) presente?
if ! command -v htpasswd >/dev/null 2>&1; then
  log "instalando apache2-utils (htpasswd)"
  apt-get update -qq
  apt-get install -y apache2-utils
fi

# 2. clone/pull do repo
if [[ ! -d "$REPO_DIR/.git" ]]; then
  log "clonando repo em $REPO_DIR"
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone "$REPO_URL" "$REPO_DIR"
else
  log "atualizando repo em $REPO_DIR"
  git -C "$REPO_DIR" fetch origin main --quiet
  git -C "$REPO_DIR" reset --hard origin/main --quiet
fi

mkdir -p "$RUN_DIR"

# 3. setup inicial do .env (uma vez só)
if [[ ! -f "$RUN_DIR/.env" ]]; then
  log "primeira run — gerando $RUN_DIR/.env"
  read -r -s -p "Senha pro basic auth (user: $AUTH_USER): " PASSWD
  echo
  if [[ -z "$PASSWD" ]]; then
    log "senha vazia; abortando"
    exit 1
  fi
  # BCrypt + escape $$ pro compose
  HASH=$(htpasswd -nbB "$AUTH_USER" "$PASSWD" | sed 's/\$/\$\$/g')
  cp "$REPO_DIR/scripts/vps/dashboard.env.example" "$RUN_DIR/.env"
  # delimitador alternativo pra evitar colisão com $
  sed -i "s|^TRAEFIK_BASIC_AUTH_USERS=.*|TRAEFIK_BASIC_AUTH_USERS=$HASH|" "$RUN_DIR/.env"
  chmod 600 "$RUN_DIR/.env"
  log "$RUN_DIR/.env criado (chmod 600)"
else
  log "$RUN_DIR/.env já existe — mantendo"
fi

# 4. sincroniza compose atual
cp "$REPO_DIR/scripts/vps/dashboard-compose.yml" "$RUN_DIR/docker-compose.yml"

# 5. build + up
log "build + up"
cd "$RUN_DIR"
docker compose build
docker compose up -d

# 6. snapshot do estado
log "container:"
docker ps --filter name=storm-vps-dashboard --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

DOMAIN=$(grep -E '^DASHBOARD_DOMAIN=' "$RUN_DIR/.env" | cut -d= -f2)
log "ok — acesso: https://$DOMAIN/ (basic auth: $AUTH_USER)"
