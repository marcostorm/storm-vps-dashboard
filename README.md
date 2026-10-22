# storm-vps-dashboard

Dashboard local pra saúde do VPS Storm Lab (Hostinger). Coleta métricas via SSH on-demand e renderiza em Streamlit. Nada é instalado no VPS — só comandos SSH padrão (`docker ps`, `df`, `free`, `uptime`).

Pensado pra snapshot ao vivo. Sem persistência, sem histórico — adicionar só se virar necessidade real.

## Setup

```bash
cd ~/workspace/storm-vps-dashboard
python -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env   # ajustar se precisar
```

## Rodar

Dashboard (Streamlit, bind em `127.0.0.1:8501`):

```bash
. .venv/bin/activate
storm-vps-dash
```

Servidor MCP (stdio, consumido pelo Claude Code):

```bash
. .venv/bin/activate
storm-vps-mcp
```

## Métricas v0

- `docker ps` — containers (nome, status, uptime, portas)
- `df -h /` — disco raiz
- `free -m` — memória
- `uptime` — load avg
- `docker system df` — espaço do Docker

## MCP tools

Leitura:
- `vps_health()` — snapshot (uptime, mem, disco, docker df, containers)
- `vps_list_containers()` — `docker ps --all`
- `vps_container_logs(name, tail=50)` — últimas N linhas
- `vps_list_image_tags(image="storm-commerce")` — tags locais ordenadas desc

Destrutivas (confirm=False retorna dry-run):
- `vps_restart_container(name, confirm=False)` — `docker restart`
- `vps_prune_images(keep_tags=3, confirm=False)` — wrapper de `/opt/stormlab/scripts/prune-images.sh`
- `vps_deploy_project(loja, tag="", confirm=False)` — wrapper de `/opt/stormlab/scripts/deploy.sh` (backup → build → smoke test → swap → health check → auto-rollback)
- `vps_rollback_project(loja, tag, confirm=False)` — wrapper de `/opt/stormlab/scripts/rollback.sh`

Aditivas (rodam direto, sem confirm):
- `vps_backup_db(loja)` — wrapper de `/opt/stormlab/scripts/backup-db.sh` (pg_dump + upload Cloudflare R2)

## Deploy no VPS (24/7)

Opcional: subir o próprio dashboard no VPS pra ficar sempre on, atrás do Traefik + basic auth. Dashboard roda em container no VPS e SSH-logas via `host.docker.internal` → `127.0.0.1` do host (chave root do VPS montada read-only no container).

**Pré-requisitos no VPS:**
- Docker + docker compose
- Traefik existente com network externa (default `traefik_proxy`; ajustar `TRAEFIK_NETWORK_NAME` no `.env` se outro nome)
- A record DNS: `lab.marcostorm.com.br` → `187.127.249.58`

**Setup inicial (uma vez):**

```bash
# No VPS como root
curl -fsSL https://raw.githubusercontent.com/marcostorm/storm-vps-dashboard/main/scripts/vps/dashboard-deploy.sh -o /tmp/dashboard-deploy.sh
bash /tmp/dashboard-deploy.sh
# Script pede senha pro basic auth (user: marcos), gera htpasswd BCrypt,
# clona repo em /opt/stormlab/storm-vps-dashboard, cria /opt/stormlab/dashboard/.env,
# builda imagem e sobe.
```

**Updates seguintes:** mesmo comando. Script detecta `.env` existente e só puxa + rebuilda.

**Como funciona:**
- Streamlit sobe em `0.0.0.0:8501` no container.
- Traefik roteia `lab.marcostorm.com.br` → container na porta 8501, com TLS (Let's Encrypt via resolver `le`).
- Middleware basic auth exige user `marcos` + senha.
- `collector.py` SSH loopback via `host.docker.internal` com chave `/root/.ssh/id_ed25519` (bind mount read-only de `/root/.ssh/`).
- Flag `VPS_SKIP_HOST_KEY_CHECK=1` troca `RejectPolicy` por `AutoAddPolicy` só nesse container (default remoto segue estrito).

**Risco conhecido:** container com acesso à chave root do VPS. Se Streamlit for comprometido, atacante tem SSH root. Mitigação: Traefik basic auth na frente + container só na network interna do Traefik. Pra ambiente de produção com mais superfície, criar user `dashboard` dedicado com sudoers restrito.

## Fora do escopo

Histórico/série temporal, alertas, múltiplos VPS, logs streaming, deploy async/background.
