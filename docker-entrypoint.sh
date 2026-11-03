#!/bin/sh
# Roda como root na partida pra copiar a chave SSH mountada
# (root:root 0600 vinda do host) pra um path acessível ao user `app`.
# Depois dropa privilégio via gosu e executa o CMD (streamlit).
#
# Motivação: evitar dashboard rodando como root dentro do container
# (defense in depth). Sem isso, user non-root não leria /secrets/id_ed25519
# porque o bind mount preserva owner/perm do host.
set -e

if [ -f /secrets/id_ed25519 ]; then
  install -o app -g app -m 0600 /secrets/id_ed25519 /home/app/.ssh/id_ed25519
fi

if [ -f /secrets/known_hosts ]; then
  install -o app -g app -m 0644 /secrets/known_hosts /home/app/.ssh/known_hosts
fi

exec gosu app "$@"
