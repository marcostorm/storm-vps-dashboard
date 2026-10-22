from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import paramiko

from .config import VPSConfig


@dataclass(frozen=True)
class Container:
    name: str
    image: str
    status: str
    state: str
    ports: str
    running_for: str


@dataclass(frozen=True)
class DiskRoot:
    total: str
    used: str
    avail: str
    use_percent: int


@dataclass(frozen=True)
class Memory:
    total_mb: int
    used_mb: int
    free_mb: int
    available_mb: int
    use_percent: float


@dataclass(frozen=True)
class Uptime:
    raw: str
    load_1m: float
    load_5m: float
    load_15m: float


@dataclass(frozen=True)
class DockerSystemDf:
    images_total_size: str
    images_reclaimable: str
    containers_total_size: str
    volumes_total_size: str
    build_cache_total_size: str


@contextmanager
def _client(cfg: VPSConfig) -> Iterator[paramiko.SSHClient]:
    c = paramiko.SSHClient()
    known_hosts = Path("~/.ssh/known_hosts").expanduser()
    if known_hosts.exists():
        c.load_host_keys(str(known_hosts))
    if os.environ.get("VPS_SKIP_HOST_KEY_CHECK") == "1":
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        c.set_missing_host_key_policy(paramiko.RejectPolicy())
    c.connect(
        hostname=cfg.host,
        port=cfg.port,
        username=cfg.user,
        key_filename=str(cfg.key_path),
        timeout=10,
        auth_timeout=10,
        banner_timeout=10,
    )
    try:
        yield c
    finally:
        c.close()


def _run(c: paramiko.SSHClient, cmd: str) -> str:
    stdin, stdout, stderr = c.exec_command(cmd, timeout=15)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    if rc != 0:
        raise RuntimeError(f"comando '{cmd}' falhou (rc={rc}): {err.strip()}")
    return out


def list_containers(c: paramiko.SSHClient) -> list[Container]:
    out = _run(
        c,
        "docker ps --all --format '{{json .}}'",
    )
    containers: list[Container] = []
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        containers.append(
            Container(
                name=d.get("Names", ""),
                image=d.get("Image", ""),
                status=d.get("Status", ""),
                state=d.get("State", ""),
                ports=d.get("Ports", ""),
                running_for=d.get("RunningFor", ""),
            )
        )
    return containers


def disk_root(c: paramiko.SSHClient) -> DiskRoot:
    out = _run(c, "df -h / | tail -n 1")
    parts = out.split()
    return DiskRoot(
        total=parts[1],
        used=parts[2],
        avail=parts[3],
        use_percent=int(parts[4].rstrip("%")),
    )


def memory(c: paramiko.SSHClient) -> Memory:
    out = _run(c, "free -m | awk 'NR==2'")
    parts = out.split()
    total = int(parts[1])
    used = int(parts[2])
    free = int(parts[3])
    available = int(parts[6]) if len(parts) >= 7 else free
    use_percent = (used / total * 100) if total else 0.0
    return Memory(
        total_mb=total,
        used_mb=used,
        free_mb=free,
        available_mb=available,
        use_percent=round(use_percent, 1),
    )


def uptime(c: paramiko.SSHClient) -> Uptime:
    raw = _run(c, "uptime").strip()
    load_part = raw.rsplit("load average:", 1)[-1].strip()
    l1, l5, l15 = (float(x.strip().rstrip(",")) for x in load_part.split(","))
    return Uptime(raw=raw, load_1m=l1, load_5m=l5, load_15m=l15)


def docker_system_df(c: paramiko.SSHClient) -> DockerSystemDf:
    out = _run(c, "docker system df --format '{{json .}}'")
    rows = {}
    for line in out.strip().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        rows[d.get("Type", "").lower()] = d
    img = rows.get("images", {})
    con = rows.get("containers", {})
    vol = rows.get("local volumes", {})
    cache = rows.get("build cache", {})
    return DockerSystemDf(
        images_total_size=img.get("Size", "?"),
        images_reclaimable=img.get("Reclaimable", "?"),
        containers_total_size=con.get("Size", "?"),
        volumes_total_size=vol.get("Size", "?"),
        build_cache_total_size=cache.get("Size", "?"),
    )


def container_logs(cfg: VPSConfig, name: str, tail: int = 50) -> str:
    _validate_container_name(name)
    tail = max(1, min(tail, 2000))
    with _client(cfg) as c:
        stdin, stdout, stderr = c.exec_command(
            f"docker logs --tail {tail} --timestamps {name} 2>&1", timeout=20
        )
        rc = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        if rc != 0:
            raise RuntimeError(f"docker logs falhou (rc={rc}): {out.strip()[:500]}")
        return out


def _validate_container_name(name: str) -> None:
    if not name or not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"nome de container inválido: {name!r}")


def _validate_loja_name(name: str) -> None:
    if not name or not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"nome de loja inválido: {name!r}")


def _validate_tag(tag: str) -> None:
    if not tag or not tag.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"tag inválida: {tag!r}")


def _validate_run_id(run_id: str) -> None:
    if not run_id or not run_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"run_id inválido: {run_id!r}")


def _exec_capture(c: paramiko.SSHClient, cmd: str, timeout: int) -> tuple[int, str]:
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    rc = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    combined = out + (f"\n[stderr]\n{err}" if err.strip() else "")
    return rc, combined


def container_state(c: paramiko.SSHClient, name: str) -> dict:
    """Retorna {state, status, running_for, image} do container ou {error}."""
    _validate_container_name(name)
    rc, out = _exec_capture(
        c,
        f"docker inspect {name} --format '{{{{.State.Status}}}}|{{{{.State.StartedAt}}}}|{{{{.Config.Image}}}}'",
        timeout=10,
    )
    if rc != 0:
        return {"error": out.strip()[:300]}
    parts = out.strip().split("|")
    return {
        "state": parts[0] if len(parts) > 0 else "unknown",
        "started_at": parts[1] if len(parts) > 1 else "",
        "image": parts[2] if len(parts) > 2 else "",
    }


def restart_container(cfg: VPSConfig, name: str) -> dict:
    _validate_container_name(name)
    with _client(cfg) as c:
        before = container_state(c, name)
        if "error" in before:
            raise RuntimeError(f"container não encontrado: {before['error']}")
        rc, out = _exec_capture(c, f"docker restart {name}", timeout=60)
        if rc != 0:
            raise RuntimeError(f"docker restart falhou (rc={rc}): {out.strip()[:300]}")
        after = container_state(c, name)
        return {
            "restarted": name,
            "before": before,
            "after": after,
        }


def list_lojas(cfg: VPSConfig) -> list[str]:
    with _client(cfg) as c:
        rc, out = _exec_capture(
            c, "ls -1 /opt/stormlab/lojas 2>/dev/null", timeout=10
        )
        if rc != 0:
            return []
        return [l.strip() for l in out.splitlines() if l.strip()]


def list_image_tags(cfg: VPSConfig, image: str = "storm-commerce") -> list[dict]:
    _validate_tag(image)
    with _client(cfg) as c:
        rc, out = _exec_capture(
            c,
            f"docker images {image} --format '{{{{.Tag}}}}|{{{{.CreatedAt}}}}|{{{{.Size}}}}'",
            timeout=10,
        )
        if rc != 0:
            return []
        rows: list[dict] = []
        for line in out.splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 3 and parts[0]:
                rows.append({"tag": parts[0], "created_at": parts[1], "size": parts[2]})
        return rows


def run_script(cfg: VPSConfig, script_path: str, args: list[str], timeout: int) -> dict:
    """Executa um script shell no VPS e captura output. Timeout em segundos."""
    for a in args:
        if not a.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise ValueError(f"argumento inválido: {a!r}")
    cmd = script_path + ("" if not args else " " + " ".join(args))
    with _client(cfg) as c:
        rc, out = _exec_capture(c, cmd, timeout=timeout)
        return {"rc": rc, "output": out, "command": cmd}


RUNS_ROOT = "/opt/stormlab/runs"
DEPLOY_ASYNC = "/opt/stormlab/scripts/deploy-async.sh"


def _gen_run_id(loja: str) -> str:
    from datetime import datetime
    return f"deploy-{loja}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def deploy_project_async(cfg: VPSConfig, loja: str, tag: str = "") -> dict:
    """Dispara deploy.sh em background no VPS via deploy-async.sh.

    Retorna {run_id, pid} na hora. Deploy continua rodando desatachado;
    acompanhe com get_run_status(cfg, run_id).
    """
    _validate_loja_name(loja)
    if tag:
        _validate_tag(tag)
    run_id = _gen_run_id(loja)
    tag_arg = tag if tag else "-"
    cmd = f"{DEPLOY_ASYNC} {loja} {tag_arg} {run_id}"
    with _client(cfg) as c:
        rc, out = _exec_capture(c, cmd, timeout=15)
    if rc != 0:
        raise RuntimeError(f"deploy-async.sh falhou (rc={rc}): {out.strip()[:300]}")

    pid = None
    for line in out.splitlines():
        if line.startswith("run_id="):
            for part in line.split():
                if part.startswith("pid="):
                    try:
                        pid = int(part.split("=", 1)[1])
                    except ValueError:
                        pass
            break
    return {"run_id": run_id, "pid": pid, "command": cmd}


_RUN_FIELD_SEP = "::FILE:"
_RUN_FIELDS = ("state", "pid", "started_at", "ended_at", "rc", "cmd")


def get_run_status(cfg: VPSConfig, run_id: str, tail: int = 200) -> dict:
    """Lê estado + tail do output.log de um run em /opt/stormlab/runs/<run_id>/.

    Retorna {run_id, state, pid, started_at, ended_at, rc, cmd, output_tail,
    output_lines_total, exists}. Se o run não existir, {exists: False}.
    """
    _validate_run_id(run_id)
    tail = max(1, min(int(tail), 5000))
    run_dir = f"{RUNS_ROOT}/{run_id}"
    # Script bash inline com separador único por arquivo.
    reader = (
        f'set -e; d={run_dir}; '
        f'if [ ! -d "$d" ]; then echo "{_RUN_FIELD_SEP}MISSING::"; exit 0; fi; '
        + "; ".join(
            f'echo "{_RUN_FIELD_SEP}{f}::"; cat "$d/{f}" 2>/dev/null || true'
            for f in _RUN_FIELDS
        )
        + f'; echo "{_RUN_FIELD_SEP}output::"; tail -n {tail} "$d/output.log" 2>/dev/null || true'
        + f'; echo "{_RUN_FIELD_SEP}lines::"; wc -l < "$d/output.log" 2>/dev/null || echo 0'
    )
    with _client(cfg) as c:
        rc, out = _exec_capture(c, reader, timeout=20)
    if rc != 0:
        raise RuntimeError(f"leitura do run falhou (rc={rc}): {out.strip()[:300]}")

    if f"{_RUN_FIELD_SEP}MISSING::" in out:
        return {"run_id": run_id, "exists": False}

    chunks: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in out.splitlines():
        if line.startswith(_RUN_FIELD_SEP) and line.endswith("::"):
            if current is not None:
                chunks[current] = "\n".join(buf).rstrip("\n")
            current = line[len(_RUN_FIELD_SEP):-2]
            buf = []
        else:
            buf.append(line)
    if current is not None:
        chunks[current] = "\n".join(buf).rstrip("\n")

    def _opt_int(s: str) -> int | None:
        s = s.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None

    return {
        "run_id": run_id,
        "exists": True,
        "state": chunks.get("state", "").strip() or "unknown",
        "pid": _opt_int(chunks.get("pid", "")),
        "started_at": chunks.get("started_at", "").strip() or None,
        "ended_at": chunks.get("ended_at", "").strip() or None,
        "rc": _opt_int(chunks.get("rc", "")),
        "cmd": chunks.get("cmd", "").strip() or None,
        "output_tail": chunks.get("output", ""),
        "output_lines_total": _opt_int(chunks.get("lines", "")) or 0,
    }


def list_runs(
    cfg: VPSConfig, limit: int = 20, state_filter: str | None = None
) -> list[dict]:
    """Lista runs ordenados por mtime desc. state_filter: running|ok|failed."""
    limit = max(1, min(int(limit), 200))
    if state_filter and state_filter not in {"running", "ok", "failed"}:
        raise ValueError(f"state_filter inválido: {state_filter!r}")
    # Para cada subdir, serializa linha única: id|state|started|ended|rc
    reader = (
        f'set -e; cd {RUNS_ROOT} 2>/dev/null || exit 0; '
        f'for d in $(ls -1t 2>/dev/null | head -n {limit}); do '
        f'  [ -d "$d" ] || continue; '
        f'  s=$(cat "$d/state" 2>/dev/null); '
        f'  st=$(cat "$d/started_at" 2>/dev/null); '
        f'  et=$(cat "$d/ended_at" 2>/dev/null); '
        f'  rc=$(cat "$d/rc" 2>/dev/null); '
        f'  echo "$d|$s|$st|$et|$rc"; '
        f'done'
    )
    with _client(cfg) as c:
        rc, out = _exec_capture(c, reader, timeout=15)
    if rc != 0:
        raise RuntimeError(f"list_runs falhou (rc={rc}): {out.strip()[:300]}")

    rows: list[dict] = []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 5 or not parts[0]:
            continue
        state = parts[1] or "unknown"
        if state_filter and state != state_filter:
            continue
        rc_str = parts[4].strip()
        try:
            rc_val: int | None = int(rc_str) if rc_str else None
        except ValueError:
            rc_val = None
        rows.append(
            {
                "run_id": parts[0],
                "state": state,
                "started_at": parts[2] or None,
                "ended_at": parts[3] or None,
                "rc": rc_val,
            }
        )
    return rows


@dataclass(frozen=True)
class Snapshot:
    containers: list[Container]
    disk: DiskRoot
    memory: Memory
    uptime: Uptime
    docker_df: DockerSystemDf


def collect(cfg: VPSConfig) -> Snapshot:
    with _client(cfg) as c:
        return Snapshot(
            containers=list_containers(c),
            disk=disk_root(c),
            memory=memory(c),
            uptime=uptime(c),
            docker_df=docker_system_df(c),
        )
