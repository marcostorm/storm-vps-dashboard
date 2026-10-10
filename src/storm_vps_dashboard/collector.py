from __future__ import annotations

import json
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
    if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ValueError(f"nome de container inválido: {name!r}")
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
