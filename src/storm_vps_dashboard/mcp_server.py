"""MCP server que expõe operações de leitura do VPS Hostinger (Storm Commerce).

Servidor usa a mesma camada SSH (collector.py) do dashboard Streamlit.
Só tools de LEITURA — nada destrutivo (restart, deploy, prune) na v0.
"""
from __future__ import annotations

from dataclasses import asdict

from mcp.server.mcpserver import MCPServer

from .collector import (
    collect,
    container_logs as _container_logs,
)
from .config import load_config


mcp = MCPServer("storm-vps")


@mcp.tool()
def vps_list_containers() -> list[dict]:
    """Lista todos os containers do VPS Hostinger (`187.127.249.58`),
    incluindo parados. Equivalente a `docker ps --all`.

    Use pra ver estado operacional das lojas Storm Commerce e serviços
    (Traefik, Postgres das lojas). Projetos tipicamente rodando:
    `loja-demo-app-1`, `loja-demo-database-1`, `traefik-traefik-1`.

    Returns:
        Lista de containers, cada um: name, image, status, state
        ('running'|'exited'|'restarting'|...), ports, running_for.
    """
    snap = collect(load_config())
    return [asdict(c) for c in snap.containers]


@mcp.tool()
def vps_container_logs(name: str, tail: int = 50) -> dict:
    """Lê as últimas N linhas de log de um container do VPS. Combina
    stdout+stderr, com timestamps. Use pra investigar erro específico
    ou verificar o que uma loja está servindo agora.

    Pra descobrir nomes de containers válidos, chame `vps_list_containers()`
    antes.

    Args:
        name: nome exato do container (ex: 'loja-demo-app-1'). Só aceita
              alfanumérico + `-_.` — bloqueia shell meta por segurança.
        tail: nº de linhas, default 50, max 2000.

    Returns:
        {container, tail, logs} em caso de sucesso.
        {error} em caso de nome inválido ou falha SSH.
    """
    try:
        logs = _container_logs(load_config(), name, tail=tail)
        return {
            "container": name,
            "tail": min(max(1, tail), 2000),
            "logs": logs,
        }
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}


@mcp.tool()
def vps_health() -> dict:
    """Snapshot consolidado de saúde do VPS Hostinger. Equivale a chamar
    `uptime`, `free -m`, `df -h /`, `docker ps`, `docker system df` em
    uma única passada SSH.

    Use ANTES de propor qualquer deploy/mudança no VPS, pra confirmar
    que o host está saudável e que os containers esperados estão rodando.

    Returns:
        {
          host, user,
          uptime: {raw, load_1m, load_5m, load_15m},
          memory: {total_mb, used_mb, free_mb, available_mb, use_percent},
          disk_root: {total, used, avail, use_percent},
          docker_df: {images_total_size, images_reclaimable,
                      containers_total_size, volumes_total_size,
                      build_cache_total_size},
          containers: {total, running, by_state: {running: N, exited: M, ...}}
        }
    """
    cfg = load_config()
    snap = collect(cfg)

    by_state: dict[str, int] = {}
    for c in snap.containers:
        by_state[c.state] = by_state.get(c.state, 0) + 1

    return {
        "host": cfg.host,
        "user": cfg.user,
        "uptime": asdict(snap.uptime),
        "memory": asdict(snap.memory),
        "disk_root": asdict(snap.disk),
        "docker_df": asdict(snap.docker_df),
        "containers": {
            "total": len(snap.containers),
            "running": by_state.get("running", 0),
            "by_state": by_state,
        },
    }


def run() -> None:
    """Entry point do servidor (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    run()
