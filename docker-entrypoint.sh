#!/bin/sh
# Roda como root na partida pra copiar as chaves SSH mountadas
# (root:root 0600 vinda do host) pra um path acessível ao user `app`.
# Depois dropa privilégio via gosu e executa o CMD (streamlit).
#
# Motivação: evitar dashboard rodando como root dentro do container
# (defense in depth). Sem isso, user non-root não leria as chaves
# porque o bind mount preserva owner/perm do host.
set -e

# Qualquer arquivo em /secrets/ que termine com _ed25519 (ou similar) vira
# uma chave privada acessível ao user app. Suporta setup multi-VPS.
for key in /secrets/*_ed25519 /secrets/id_ed25519 /secrets/id_rsa; do
  [ -f "$key" ] || continue
  name="$(basename "$key")"
  install -o app -g app -m 0600 "$key" "/home/app/.ssh/$name"
done

if [ -f /secrets/known_hosts ]; then
  install -o app -g app -m 0644 /secrets/known_hosts /home/app/.ssh/known_hosts
fi

exec gosu app "$@"
