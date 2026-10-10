import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class VPSConfig:
    host: str
    user: str
    port: int
    key_path: Path


def load_config() -> VPSConfig:
    host = os.environ.get("VPS_HOST")
    user = os.environ.get("VPS_USER")
    if not host or not user:
        raise RuntimeError("VPS_HOST e VPS_USER são obrigatórios (ver .env.example)")
    key_path = Path(os.environ.get("VPS_KEY_PATH", "~/.ssh/id_ed25519")).expanduser()
    port = int(os.environ.get("VPS_PORT", "22"))
    return VPSConfig(host=host, user=user, port=port, key_path=key_path)
