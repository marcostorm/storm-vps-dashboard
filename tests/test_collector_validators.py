"""Regressão: após migrar validators pro `storm-mcp-common`, os aliases
re-exportados em `collector` têm que preservar o contrato exato (nome do
tipo no erro, chars aceitos). Essas asserções travam pra qualquer refactor
futuro que quisesse afrouxar.
"""
from __future__ import annotations

import pytest

from storm_vps_dashboard.collector import (
    _validate_container_name,
    _validate_loja_name,
    _validate_run_id,
    _validate_tag,
    run_script,
)


class TestValidatorsAliases:
    def test_container_accepts_normal(self):
        _validate_container_name("loja-demo-app-1")

    def test_container_mentions_container_in_error(self):
        with pytest.raises(ValueError, match="container"):
            _validate_container_name("a;b")

    def test_loja_rejects_dot(self):
        with pytest.raises(ValueError, match="loja"):
            _validate_loja_name("foo.bar")

    def test_loja_accepts_underscore_dash(self):
        _validate_loja_name("loja_demo-1")

    def test_tag_rejects_slash(self):
        """Garantia explícita contra break-out do `sed -i` do deploy.sh."""
        with pytest.raises(ValueError, match="tag"):
            _validate_tag("a/b")

    def test_tag_accepts_timestamp(self):
        _validate_tag("20261105-1430")

    def test_run_id_rejects_dot(self):
        with pytest.raises(ValueError, match="run_id"):
            _validate_run_id("deploy.run.1")


class TestRunScriptArgValidation:
    """`run_script` valida cada arg em `args` antes de concatenar no cmd SSH.
    Se validação afrouxar, qualquer ArgumentInjection pode escapar."""

    def test_rejects_arg_with_space(self):
        with pytest.raises(ValueError, match="argumento inválido"):
            run_script(
                cfg=None,  # nunca chega no SSH, erro vem antes
                script_path="/opt/stormlab/scripts/dummy.sh",
                args=["loja ok", "tag"],
                timeout=10,
            )

    def test_rejects_arg_with_semicolon(self):
        with pytest.raises(ValueError, match="argumento inválido"):
            run_script(
                cfg=None,
                script_path="/opt/stormlab/scripts/dummy.sh",
                args=["loja;rm", "tag"],
                timeout=10,
            )

    def test_rejects_arg_with_backtick(self):
        with pytest.raises(ValueError, match="argumento inválido"):
            run_script(
                cfg=None,
                script_path="/opt/stormlab/scripts/dummy.sh",
                args=["loja`whoami`"],
                timeout=10,
            )
