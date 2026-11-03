#!/bin/bash
# Wrapper SSH restritivo da chave github-actions-paxiuba-deploy.
#
# Ativado em /root/.ssh/authorized_keys via:
#   command="/opt/stormlab/bin/paxiuba-deploy.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAA... github-actions-paxiuba-deploy
#
# Com o command= acima, sshd ignora o que o cliente enviar e sempre
# executa ESTE script. O comando original chega em $SSH_ORIGINAL_COMMAND.
#
# Protocolo aceito:
#   deploy <sha40>
#
# Qualquer outro input é rejeitado — a chave do CI só serve pra disparar
# o deploy do paxiuba. Se vazar, não dá shell, não dá rsync, não dá nada.
set -euo pipefail

APP_DIR=/opt/stormlab/paxiuba

log() { printf '[paxiuba-wrapper] %s\n' "$*"; }
deny() { log "DENIED: $*" >&2; exit 1; }

if [[ -z "${SSH_ORIGINAL_COMMAND:-}" ]]; then
  deny "no command (interactive shell not allowed)"
fi

if [[ ! "$SSH_ORIGINAL_COMMAND" =~ ^deploy[[:space:]]+([a-f0-9]{40})$ ]]; then
  deny "invalid command. Expected 'deploy <sha40>'. Got: $SSH_ORIGINAL_COMMAND"
fi

SHA="${BASH_REMATCH[1]}"
log "target SHA: $SHA"

cd "$APP_DIR"
PREV_SHA="$(git rev-parse HEAD)"
log "snapshot deploy-prev -> $PREV_SHA"
git tag -f deploy-prev "$PREV_SHA" >/dev/null
git fetch --prune origin
git reset --hard "$SHA"

export PREV_SHA
exec bash scripts/deploy/remote.sh
