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

## MCP tools (v1)

Leitura:
- `vps_health()` — snapshot (uptime, mem, disco, docker df, containers)
- `vps_list_containers()` — `docker ps --all`
- `vps_container_logs(name, tail=50)` — últimas N linhas

Destrutivas (confirm=False retorna dry-run):
- `vps_restart_container(name, confirm=False)` — `docker restart`
- `vps_prune_images(keep_tags=3, confirm=False)` — wrapper de `/opt/stormlab/scripts/prune-images.sh`
- `vps_deploy_project(loja, tag="", confirm=False)` — wrapper de `/opt/stormlab/scripts/deploy.sh` (backup → build → smoke test → swap → health check → auto-rollback)

## Fora do escopo

Histórico/série temporal, alertas, múltiplos VPS, logs streaming, deploy async/background.
