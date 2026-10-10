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

## Fora do escopo v0

Histórico/série temporal, alertas, ações (restart), múltiplos VPS, logs streaming.
