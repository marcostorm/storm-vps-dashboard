"""Guard do VPS_SKIP_HOST_KEY_CHECK: só vale pra loopback docker.

Teste mockando `paramiko.SSHClient.connect` pra garantir que o guard
dispara ANTES de qualquer tentativa de conexão. Se o guard falhar, o
skip de host key reaparece pra todo host — risco MITM silencioso.
"""
from __future__ import annotations

from pathlib import Path

import paramiko
import pytest

from storm_vps_dashboard.collector import _client
from storm_vps_dashboard.config import VPSConfig


def _cfg(host: str) -> VPSConfig:
    return VPSConfig(host=host, port=22, user="root", key_path=Path("/dev/null"))


class TestSkipHostKeyGuard:
    def test_skip_rejected_on_regular_host(self, monkeypatch):
        """VPS_SKIP_HOST_KEY_CHECK=1 com host real: deve levantar antes de
        conectar."""
        monkeypatch.setenv("VPS_SKIP_HOST_KEY_CHECK", "1")
        called = {"connect": False}

        def _fake_connect(self, *a, **kw):
            called["connect"] = True

        monkeypatch.setattr(paramiko.SSHClient, "connect", _fake_connect)

        with pytest.raises(RuntimeError, match="host.docker.internal"):
            with _client(_cfg("187.127.249.58")):
                pass
        assert called["connect"] is False, "connect() não deveria ser chamado"

    def test_skip_allowed_for_loopback(self, monkeypatch):
        """host.docker.internal com flag: aceita, segue pro connect."""
        monkeypatch.setenv("VPS_SKIP_HOST_KEY_CHECK", "1")
        called = {"connect": 0}

        def _fake_connect(self, *a, **kw):
            called["connect"] += 1

        monkeypatch.setattr(paramiko.SSHClient, "connect", _fake_connect)
        monkeypatch.setattr(paramiko.SSHClient, "close", lambda self: None)

        with _client(_cfg("host.docker.internal")):
            pass
        assert called["connect"] == 1

    def test_default_uses_strict_policy(self, monkeypatch, tmp_path):
        """Sem a flag: known_hosts carregado + RejectPolicy. Qualquer host
        desconhecido deve ser rejeitado no handshake (não aqui — aqui só
        valido que o policy é RejectPolicy)."""
        monkeypatch.delenv("VPS_SKIP_HOST_KEY_CHECK", raising=False)

        captured = {"policy": None}

        def _capture_policy(self, policy):
            captured["policy"] = policy

        monkeypatch.setattr(
            paramiko.SSHClient,
            "set_missing_host_key_policy",
            _capture_policy,
        )
        monkeypatch.setattr(paramiko.SSHClient, "connect", lambda s, *a, **kw: None)
        monkeypatch.setattr(paramiko.SSHClient, "close", lambda s: None)

        with _client(_cfg("187.127.249.58")):
            pass
        assert isinstance(captured["policy"], paramiko.RejectPolicy)
