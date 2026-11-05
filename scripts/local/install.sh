#!/usr/bin/env bash
# Instala o vigia de segurança da workstation local como systemd --user timer.
# Idempotente: pode rodar várias vezes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_SYSTEMD="${HOME}/.config/systemd/user"
STATE_DIR="${HOME}/.local/state"

mkdir -p "$USER_SYSTEMD" "$STATE_DIR"

chmod +x "$SCRIPT_DIR/security-check-local.sh"

# Symlink em vez de copy pra que git pull atualize o conteúdo automaticamente.
ln -sf "$SCRIPT_DIR/systemd/storm-security-local.service" "$USER_SYSTEMD/storm-security-local.service"
ln -sf "$SCRIPT_DIR/systemd/storm-security-local.timer"   "$USER_SYSTEMD/storm-security-local.timer"

systemctl --user daemon-reload
systemctl --user enable --now storm-security-local.timer

echo "✓ instalado. Status:"
systemctl --user list-timers storm-security-local.timer --no-pager
echo
echo "Rodar agora pra testar: systemctl --user start storm-security-local.service"
echo "Ver log:               tail -f ~/.local/state/storm-security-local.log"
