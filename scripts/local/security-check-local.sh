#!/usr/bin/env bash
# Vigia semanal de segurança da workstation local do Marcos (laptop/desktop
# onde rodam RAG, MCPs, watchers que leem home). Complementa o
# security-check.sh do VPS cobrindo perímetro que o VPS não vê.
#
# Instalação: scripts/local/install.sh (systemd --user timer Mon 09:00 BRT).
# Silêncio = tudo verde. Alerta via @storm_agents_bot se detectar regressão.
set -euo pipefail

# ─── Baselines ────────────────────────────────────────────────────────────────
# Portas públicas esperadas na workstation. Zero. Qualquer bind em 0.0.0.0/::
# vira critical. Adicionar aqui só se for intencional e documentado.
EXPECTED_PUBLIC_PORTS=()
MAX_UPGRADABLE=50
AGENTS_ENV="${HOME}/workspace/storm-agents/.env"
MEMORY_DIR="${HOME}/.claude/projects/-home-marcos/memory"
SSH_DIR="${HOME}/.ssh"
WORKSPACE="${HOME}/workspace"

# ─── Setup ────────────────────────────────────────────────────────────────────
CRITICAL=()
WARNINGS=()

TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
if [[ -r "$AGENTS_ENV" ]]; then
  TELEGRAM_BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$AGENTS_ENV" | cut -d= -f2- | tr -d '"')
  TELEGRAM_CHAT_ID=$(grep '^TELEGRAM_ADMIN_CHAT_ID=' "$AGENTS_ENV" | cut -d= -f2- | tr -d '"')
fi

# ─── Checks ───────────────────────────────────────────────────────────────────

check_public_ports() {
  local offenders
  offenders=$( { ss -tlnp 2>/dev/null \
    | awk '{print $4}' \
    | grep -E '^(0\.0\.0\.0|\[::\]):[0-9]+$' \
    | sed -E 's/.*:([0-9]+)$/\1/' \
    | sort -u; } || true )
  while IFS= read -r port; do
    [[ -z "$port" ]] && continue
    local found=false
    for expected in "${EXPECTED_PUBLIC_PORTS[@]:-}"; do
      if [[ "$port" == "$expected" ]]; then found=true; break; fi
    done
    if ! $found; then
      CRITICAL+=("Porta exposta em 0.0.0.0/::: $port — rebindar pra 127.0.0.1")
    fi
  done <<< "$offenders"
  return 0
}

check_postgres_binds() {
  local offenders
  offenders=$( { ss -tlnp 2>/dev/null \
    | awk '{print $4}' \
    | grep -E ':54[0-9]{2}$' \
    | grep -vE '^127\.0\.0\.1:' \
    | sort -u; } || true )
  if [[ -n "$offenders" ]]; then
    while IFS= read -r bind; do
      CRITICAL+=("Postgres fora de 127.0.0.1: $bind")
    done <<< "$offenders"
  fi
  return 0
}

check_docker_daemon() {
  if ss -tlnp 2>/dev/null | grep -qE ':237[56] '; then
    CRITICAL+=("Docker daemon exposto em 2375/2376")
  fi
  return 0
}

check_ssh_dir_perms() {
  [[ -d "$SSH_DIR" ]] || return 0
  local mode
  mode=$(stat -c '%a' "$SSH_DIR")
  if [[ "$mode" != "700" ]]; then
    CRITICAL+=("$SSH_DIR com perm $mode (esperado 700)")
  fi
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    mode=$(stat -c '%a' "$key")
    if [[ "$mode" != "600" ]]; then
      CRITICAL+=("$key com perm $mode (esperado 600)")
    fi
  done < <(find "$SSH_DIR" -maxdepth 1 -type f ! -name '*.pub' ! -name 'known_hosts*' ! -name 'config' 2>/dev/null)
  return 0
}

check_ssh_passphrase() {
  [[ -d "$SSH_DIR" ]] || return 0
  local without=()
  while IFS= read -r key; do
    [[ -z "$key" ]] && continue
    # ssh-keygen -y -P '' succeeds only se a chave não tem passphrase
    if ssh-keygen -y -P '' -f "$key" </dev/null >/dev/null 2>&1; then
      without+=("$(basename "$key")")
    fi
  done < <(find "$SSH_DIR" -maxdepth 1 -type f -name 'id_*' ! -name '*.pub' 2>/dev/null)
  if [[ ${#without[@]} -gt 0 ]]; then
    WARNINGS+=("Chaves SSH sem passphrase: ${without[*]}")
  fi
  return 0
}

check_claude_perms() {
  [[ -d "${HOME}/.claude" ]] || return 0
  local target mode
  for target in "${HOME}/.claude" "${HOME}/.claude/projects" "${HOME}/.claude/skills"; do
    [[ -d "$target" ]] || continue
    mode=$(stat -c '%a' "$target")
    if [[ "$mode" != "700" && "$mode" != "750" ]]; then
      CRITICAL+=("$target com perm $mode (esperado 700 ou 750)")
    fi
  done
  return 0
}

check_secrets_in_memory() {
  [[ -d "$MEMORY_DIR" ]] || return 0
  local hits
  hits=$(grep -rElE 'sk-[a-zA-Z0-9_-]{20,}|ghp_[a-zA-Z0-9]{30,}|AKIA[A-Z0-9]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY' "$MEMORY_DIR" 2>/dev/null | head -5 || true)
  if [[ -n "$hits" ]]; then
    while IFS= read -r f; do
      CRITICAL+=("Possível secret em memória: $(basename "$f")")
    done <<< "$hits"
  fi
  return 0
}

check_trivial_passwords_in_compose() {
  [[ -d "$WORKSPACE" ]] || return 0
  local hits
  hits=$(grep -rlE 'POSTGRES_PASSWORD:\s*(rag|postgres|admin|password|123|changeme)\b' \
    "$WORKSPACE"/*/docker-compose*.yml 2>/dev/null | head -5 || true)
  if [[ -n "$hits" ]]; then
    while IFS= read -r f; do
      WARNINGS+=("Senha trivial em compose: ${f#"$HOME"/}")
    done <<< "$hits"
  fi
  return 0
}

check_env_perms_local() {
  [[ -d "$WORKSPACE" ]] || return 0
  local offenders
  offenders=$(find "$WORKSPACE" -maxdepth 3 -name '.env' -type f ! -perm 600 ! -perm 400 2>/dev/null | head -10 || true)
  if [[ -n "$offenders" ]]; then
    while IFS= read -r f; do
      WARNINGS+=(".env com perm != 0600/0400: ${f#"$HOME"/}")
    done <<< "$offenders"
  fi
  return 0
}

check_ufw() {
  if ! command -v ufw >/dev/null 2>&1; then
    WARNINGS+=("ufw não instalado — workstation sem firewall local")
    return 0
  fi
  if ! sudo -n ufw status 2>/dev/null | grep -q '^Status: active'; then
    WARNINGS+=("ufw inativo ou sem sudo -n — firewall local desligado")
  fi
  return 0
}

check_updates() {
  command -v apt >/dev/null 2>&1 || return 0
  local count security
  count=$(apt list --upgradable 2>/dev/null | grep -vc '^Listing' || true)
  security=$(apt list --upgradable 2>/dev/null | grep -ic 'security' || true)
  if [[ "$security" -gt 0 ]]; then
    CRITICAL+=("$security pacote(s) de security pendente(s) — rodar 'apt upgrade'")
  elif [[ "$count" -gt "$MAX_UPGRADABLE" ]]; then
    WARNINGS+=("$count pacotes upgradable (threshold=$MAX_UPGRADABLE)")
  fi
  return 0
}

check_watcher_service() {
  # Watcher do RAG deveria estar sempre ativo (indexa claude-memory etc)
  if systemctl --user is-active storm-rag-watch.service >/dev/null 2>&1; then
    return 0
  fi
  WARNINGS+=("storm-rag-watch.service inativo — RAG pode estar defasado")
  return 0
}

# ─── Run all checks ───────────────────────────────────────────────────────────
check_public_ports
check_postgres_binds
check_docker_daemon
check_ssh_dir_perms
check_ssh_passphrase
check_claude_perms
check_secrets_in_memory
check_trivial_passwords_in_compose
check_env_perms_local
check_ufw
check_updates
check_watcher_service

# ─── Report ───────────────────────────────────────────────────────────────────
TOTAL=$(( ${#CRITICAL[@]} + ${#WARNINGS[@]} ))

echo "[security-check-local $(date -Iseconds)] critical=${#CRITICAL[@]} warnings=${#WARNINGS[@]}"
for c in "${CRITICAL[@]:-}"; do [[ -n "$c" ]] && echo "  🔴 $c"; done
for w in "${WARNINGS[@]:-}"; do [[ -n "$w" ]] && echo "  🟡 $w"; done

[[ "$TOTAL" -eq 0 ]] && exit 0

# ─── Notify Telegram ──────────────────────────────────────────────────────────
if [[ -z "$TELEGRAM_BOT_TOKEN" || -z "$TELEGRAM_CHAT_ID" ]]; then
  echo "⚠ Telegram creds ausentes em $AGENTS_ENV — alertas não enviados"
  exit 1
fi

MSG="*\[Storm Lab Workstation\] $(date +%Y-%m-%d)*"$'\n'
MSG+="_host: $(hostname)_"$'\n'
if [[ ${#CRITICAL[@]} -gt 0 ]]; then
  MSG+=$'\n'"🔴 *Config drift (${#CRITICAL[@]})*"$'\n'
  for c in "${CRITICAL[@]}"; do MSG+="• $c"$'\n'; done
fi
if [[ ${#WARNINGS[@]} -gt 0 ]]; then
  MSG+=$'\n'"🟡 *Degradação (${#WARNINGS[@]})*"$'\n'
  for w in "${WARNINGS[@]}"; do MSG+="• $w"$'\n'; done
fi
MSG+=$'\n'"Deep-dive: /security-audit"

curl -sS --max-time 10 \
  -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${MSG}" \
  --data-urlencode "parse_mode=Markdown" \
  >/dev/null \
  && echo "✓ alert enviado ($TOTAL achados)" \
  || echo "⚠ envio Telegram falhou"
