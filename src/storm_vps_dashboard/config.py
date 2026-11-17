import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class VPSConfig:
    name: str
    label: str
    host: str
    user: str
    port: int
    key_path: Path
    skip_host_key: bool = False


def load_hosts() -> dict[str, VPSConfig]:
    """Multi-host via VPS_HOSTS=foo,bar + VPS_FOO_HOST / VPS_FOO_USER etc.
    Fallback: VPS_HOST etc continua funcionando como host único "default"."""
    hosts_raw = os.environ.get("VPS_HOSTS", "").strip()
    if hosts_raw:
        names = [n.strip() for n in hosts_raw.split(",") if n.strip()]
        return {n: _load_prefixed(n) for n in names}
    return {"default": _load_legacy()}


def load_config(name: str | None = None) -> VPSConfig:
    """Retorna a config de um host. Sem `name`, retorna o primeiro — mantém
    compat pra MCP e scripts que não conhecem múltiplos hosts."""
    hosts = load_hosts()
    if name:
        if name not in hosts:
            raise RuntimeError(f"Host '{name}' não configurado. Disponíveis: {list(hosts)}")
        return hosts[name]
    return next(iter(hosts.values()))


def _load_prefixed(name: str) -> VPSConfig:
    prefix = f"VPS_{name.upper()}_"
    host = os.environ.get(prefix + "HOST")
    user = os.environ.get(prefix + "USER")
    if not host or not user:
        raise RuntimeError(
            f"{prefix}HOST e {prefix}USER obrigatórios (ver .env.example)"
        )
    label = os.environ.get(prefix + "LABEL", name)
    port = int(os.environ.get(prefix + "PORT", "22"))
    key_path = Path(
        os.environ.get(prefix + "KEY_PATH", "~/.ssh/id_ed25519")
    ).expanduser()
    # skip host key check é opt-in por host (default: False, exige known_hosts).
    # Fallback pra VPS_SKIP_HOST_KEY_CHECK global quando não setado por host.
    skip = (
        os.environ.get(prefix + "SKIP_HOST_KEY_CHECK")
        or os.environ.get("VPS_SKIP_HOST_KEY_CHECK")
        or "0"
    ) == "1"
    return VPSConfig(
        name=name, label=label, host=host, user=user,
        port=port, key_path=key_path, skip_host_key=skip,
    )


def _load_legacy() -> VPSConfig:
    host = os.environ.get("VPS_HOST")
    user = os.environ.get("VPS_USER")
    if not host or not user:
        raise RuntimeError(
            "VPS_HOST e VPS_USER obrigatórios (ou use VPS_HOSTS=foo,bar; ver .env.example)"
        )
    port = int(os.environ.get("VPS_PORT", "22"))
    key_path = Path(os.environ.get("VPS_KEY_PATH", "~/.ssh/id_ed25519")).expanduser()
    label = os.environ.get("VPS_LABEL", host)
    skip = os.environ.get("VPS_SKIP_HOST_KEY_CHECK") == "1"
    return VPSConfig(
        name="default", label=label, host=host, user=user,
        port=port, key_path=key_path, skip_host_key=skip,
    )
