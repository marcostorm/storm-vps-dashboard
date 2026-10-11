"""MCP server que expõe operações no VPS Hostinger (Storm Commerce).

Servidor usa a mesma camada SSH (collector.py) do dashboard Streamlit.
Tools de leitura (health, list, logs, image_tags) + destrutivas (restart,
prune, deploy, rollback) com confirm=False por padrão retornando dry-run,
e tool aditiva (backup_db) que roda direto.
"""
from __future__ import annotations

from dataclasses import asdict

from mcp.server.mcpserver import MCPServer

from .collector import (
    collect,
    container_logs as _container_logs,
    container_state,
    list_image_tags,
    list_lojas,
    restart_container,
    run_script,
    _client,
    _validate_container_name,
    _validate_loja_name,
    _validate_tag,
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


@mcp.tool()
def vps_restart_container(name: str, confirm: bool = False) -> dict:
    """Reinicia um container do VPS (`docker restart <name>`).

    Sem `confirm=True`, retorna dry-run com estado atual + comando que
    seria executado. Chame novamente com `confirm=True` pra executar.

    Args:
        name: nome exato do container. Alfanumérico + `-_.` apenas.
        confirm: `True` executa; `False` (default) retorna dry-run.

    Returns:
        Dry-run: {would_do, current_state, hint}.
        Execução: {restarted, before: {...}, after: {...}}.
        Erro: {error}.
    """
    try:
        _validate_container_name(name)
    except ValueError as e:
        return {"error": str(e)}

    try:
        with _client(load_config()) as c:
            state = container_state(c, name)
    except Exception as e:
        return {"error": f"falha SSH: {e}"}
    if "error" in state:
        return {"error": f"container não encontrado: {state['error']}"}

    if not confirm:
        return {
            "would_do": f"docker restart {name}",
            "current_state": state,
            "hint": "chame novamente com confirm=True pra executar",
        }

    try:
        return restart_container(load_config(), name)
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}


@mcp.tool()
def vps_prune_images(keep_tags: int = 3, confirm: bool = False) -> dict:
    """Remove imagens antigas de `storm-commerce` no VPS, mantendo as
    últimas `keep_tags` tags (ordenadas por data). Wrapper de
    `/opt/stormlab/scripts/prune-images.sh`.

    Sem `confirm=True`, lista as tags que SERIAM removidas sem executar.

    Args:
        keep_tags: quantas tags mais recentes manter (1-10, default 3).
        confirm: `True` executa; `False` retorna dry-run.

    Returns:
        Dry-run: {would_keep, would_remove, total_tags}.
        Execução: {rc, output, command}.
        Erro: {error}.
    """
    if not isinstance(keep_tags, int) or keep_tags < 1 or keep_tags > 10:
        return {"error": "keep_tags deve ser int entre 1 e 10"}

    try:
        tags = list_image_tags(load_config(), "storm-commerce")
    except Exception as e:
        return {"error": f"falha SSH: {e}"}

    non_latest = [t for t in tags if t["tag"] != "latest"]
    non_latest.sort(key=lambda t: t["tag"], reverse=True)
    keep = non_latest[:keep_tags]
    remove = non_latest[keep_tags:]

    if not confirm:
        return {
            "would_keep": keep,
            "would_remove": remove,
            "total_tags": len(non_latest),
            "hint": f"chame com confirm=True pra remover {len(remove)} tag(s)",
        }

    try:
        return run_script(
            load_config(),
            "/opt/stormlab/scripts/prune-images.sh",
            [str(keep_tags)],
            timeout=120,
        )
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}


@mcp.tool()
def vps_deploy_project(loja: str, tag: str = "", confirm: bool = False) -> dict:
    """Deploy de uma loja Storm Commerce. Wrapper de
    `/opt/stormlab/scripts/deploy.sh <loja> [tag]`. Fluxo do script:
    backup do banco → build da imagem → smoke test → swap do container
    → health check → auto-rollback se falhar.

    Sem `confirm=True`, valida que a loja existe e retorna preview.

    Args:
        loja: nome da loja (ex: 'loja-demo'). Deve existir em
              `/opt/stormlab/lojas/<loja>`.
        tag: versão da imagem (ex: '20261010-1430'). Vazio = timestamp
             atual gerado pelo script.
        confirm: `True` executa; `False` retorna dry-run.

    Returns:
        Dry-run: {would_do, loja, target_tag, current_image, lojas_available}.
        Execução: {rc, output, command}. Deploy pode levar 2-5min.
        Erro: {error}.
    """
    try:
        _validate_loja_name(loja)
        if tag:
            _validate_tag(tag)
    except ValueError as e:
        return {"error": str(e)}

    try:
        cfg = load_config()
        lojas = list_lojas(cfg)
        if loja not in lojas:
            return {
                "error": f"loja {loja!r} não encontrada em /opt/stormlab/lojas",
                "available": lojas,
            }

        with _client(cfg) as c:
            state = container_state(c, f"{loja}-app-1")
    except Exception as e:
        return {"error": f"falha SSH: {e}"}

    target_tag = tag or "<timestamp-atual>"
    current_image = state.get("image", "unknown") if "error" not in state else "unknown"

    if not confirm:
        return {
            "would_do": f"/opt/stormlab/scripts/deploy.sh {loja} {tag}".strip(),
            "loja": loja,
            "target_tag": target_tag,
            "current_image": current_image,
            "lojas_available": lojas,
            "hint": "chame com confirm=True pra executar (pode levar 2-5min)",
        }

    try:
        args = [loja] + ([tag] if tag else [])
        return run_script(
            cfg,
            "/opt/stormlab/scripts/deploy.sh",
            args,
            timeout=600,
        )
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}


@mcp.tool()
def vps_list_image_tags(image: str = "storm-commerce") -> dict:
    """Lista as tags locais de uma imagem Docker no VPS, ordenadas por
    nome desc (tags do formato `YYYYMMDD-HHMM` ordenam cronologicamente
    na prática).

    Use ANTES de `vps_rollback_project` pra escolher uma tag válida.

    Args:
        image: nome da imagem (default 'storm-commerce').

    Returns:
        {image, tags: [{tag, created_at, size}, ...]}.
        Erro: {error}.
    """
    try:
        _validate_tag(image)
    except ValueError as e:
        return {"error": str(e)}
    try:
        tags = list_image_tags(load_config(), image)
    except Exception as e:
        return {"error": f"falha SSH: {e}"}
    tags.sort(key=lambda t: t["tag"], reverse=True)
    return {"image": image, "tags": tags}


@mcp.tool()
def vps_rollback_project(loja: str, tag: str, confirm: bool = False) -> dict:
    """Reverte uma loja Storm Commerce pra uma tag anterior da imagem.
    Wrapper de `/opt/stormlab/scripts/rollback.sh <loja> <tag>`.

    Sem `confirm=True`, valida que a loja + tag existem e retorna preview.

    Pra descobrir tags disponíveis, chame `vps_list_image_tags()`.

    Args:
        loja: nome da loja (ex: 'loja-demo'). Deve existir em
              `/opt/stormlab/lojas/<loja>`.
        tag: versão da imagem (ex: '20261010-1430'). Deve existir
             localmente no VPS (`docker images storm-commerce`).
        confirm: `True` executa; `False` retorna dry-run.

    Returns:
        Dry-run: {would_do, loja, current_image, target_image, tags_available}.
        Execução: {rc, output, command}.
        Erro: {error}.
    """
    try:
        _validate_loja_name(loja)
        _validate_tag(tag)
    except ValueError as e:
        return {"error": str(e)}

    try:
        cfg = load_config()
        lojas = list_lojas(cfg)
        if loja not in lojas:
            return {
                "error": f"loja {loja!r} não encontrada em /opt/stormlab/lojas",
                "available": lojas,
            }

        tags = list_image_tags(cfg, "storm-commerce")
        tag_names = {t["tag"] for t in tags}
        if tag not in tag_names:
            tags_sorted = sorted(tag_names, reverse=True)
            return {
                "error": f"tag {tag!r} não existe localmente no VPS",
                "available": tags_sorted,
                "hint": "use vps_list_image_tags() pra ver tags válidas",
            }

        with _client(cfg) as c:
            state = container_state(c, f"{loja}-app-1")
    except Exception as e:
        return {"error": f"falha SSH: {e}"}

    current_image = state.get("image", "unknown") if "error" not in state else "unknown"
    target_image = f"storm-commerce:{tag}"

    if current_image == target_image:
        return {
            "error": f"loja já está em {target_image} — rollback é no-op",
            "current_image": current_image,
        }

    if not confirm:
        return {
            "would_do": f"/opt/stormlab/scripts/rollback.sh {loja} {tag}",
            "loja": loja,
            "current_image": current_image,
            "target_image": target_image,
            "hint": "chame com confirm=True pra executar",
        }

    try:
        return run_script(
            cfg,
            "/opt/stormlab/scripts/rollback.sh",
            [loja, tag],
            timeout=120,
        )
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}


@mcp.tool()
def vps_backup_db(loja: str) -> dict:
    """Backup pontual do Postgres de uma loja Storm Commerce pro Cloudflare R2.
    Wrapper de `/opt/stormlab/scripts/backup-db.sh <loja>`. O script já roda
    automaticamente embutido em `vps_deploy_project`; esta tool expõe o
    backup ad-hoc (ex: antes de uma mudança manual arriscada).

    Operação aditiva (não destrói estado da loja), por isso roda direto
    sem `confirm`. Valida que a loja existe em `/opt/stormlab/lojas` antes
    de disparar.

    Args:
        loja: nome da loja (ex: 'loja-demo'). Alfanumérico + `-_`.

    Returns:
        Sucesso: {rc, output, command}. Output traz path local + status do
        upload R2 conforme o script escreve em stdout.
        Erro: {error, available?} se loja inválida/inexistente ou SSH falhar.
    """
    try:
        _validate_loja_name(loja)
    except ValueError as e:
        return {"error": str(e)}

    try:
        cfg = load_config()
        lojas = list_lojas(cfg)
        if loja not in lojas:
            return {
                "error": f"loja {loja!r} não encontrada em /opt/stormlab/lojas",
                "available": lojas,
            }
        return run_script(
            cfg,
            "/opt/stormlab/scripts/backup-db.sh",
            [loja],
            timeout=300,
        )
    except (ValueError, RuntimeError) as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"falha SSH: {e}"}


def run() -> None:
    """Entry point do servidor (stdio transport)."""
    mcp.run()


if __name__ == "__main__":
    run()
