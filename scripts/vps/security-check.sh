#!/usr/bin/env bash
# Vigia semanal de segurança do VPS Storm Lab.
# Instalação: deploy via scripts/vps/security-check-deploy.sh (ou rsync manual).
# Agendamento: /etc/systemd/system/security-check.timer (weekly, Mon 05:00 BRT).
# Silêncio = tudo verde. Alerta via @storm_agents_bot se detectar regressão.
set -euo pipefail

# ─── Baselines (atualizar manualmente quando mudar config legítima) ───────────
EXPECTED_AUTHKEYS_HASH="4213966427a8e4529a6070d9ff96699a204735e917419ca9a72e31a64559d1f9"
EXPECTED_UFW_RULES=("22/tcp" "80/tcp" "443/tcp")
EXPECTED_PUBLIC_PORTS=("22" "80" "443")
EXPECTED_SSHD_CONFIG=(
  "permitrootlogin:without-password"
  "passwordauthentication:no"
  "kbdinteractiveauthentication:no"
  "permitemptypasswords:no"
)
MAX_LOGIN_FAILURES_7D=50
MAX_BACKUP_AGE_HOURS=48
STORM_AGENTS_ENV="/opt/stormlab/storm-agents/.env"
BACKUP_LOG="/var/log/storm-backup.log"

# ─── Setup ────────────────────────────────────────────────────────────────────
CRITICAL=()
WARNINGS=()

TELEGRAM_BOT_TOKEN=""
TELEGRAM_CHAT_ID=""
if [[ -r "$STORM_AGENTS_ENV" ]]; then
  TELEGRAM_BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$STORM_AGENTS_ENV" | cut -d= -f2- | tr -d '"')
  TELEGRAM_CHAT_ID=$(grep '^TELEGRAM_ADMIN_CHAT_ID=' "$STORM_AGENTS_ENV" | cut -d= -f2- | tr -d '"')
fi

# ─── Checks ───────────────────────────────────────────────────────────────────

check_ssh_config() {
  local effective key expected actual
  effective=$(sshd -T 2>/dev/null) || {
    CRITICAL+=("sshd -T falhou: config SSH não pode ser verificada")
    return
  }
  for entry in "${EXPECTED_SSHD_CONFIG[@]}"; do
    key=${entry%%:*}
    expected=${entry#*:}
    actual=$(echo "$effective" | awk -v k="$key" '$1==k {print $2; exit}')
    if [[ "$actual" != "$expected" ]]; then
      CRITICAL+=("sshd config: $key='$actual' (esperado '$expected')")
    fi
  done
}

check_ufw() {
  if ! ufw status 2>/dev/null | grep -q "^Status: active"; then
    CRITICAL+=("UFW não está active")
    return
  fi
  local extra
  extra=$(ufw status 2>/dev/null | awk '/^[0-9]+\/tcp/ {print $1}' | sort -u)
  while IFS= read -r rule; do
    [[ -z "$rule" ]] && continue
    local found=false
    for expected in "${EXPECTED_UFW_RULES[@]}"; do
      [[ "$rule" == "$expected" ]] && found=true && break
    done
    $found || CRITICAL+=("UFW regra extra: $rule")
  done <<< "$extra"
}

check_fail2ban() {
  systemctl is-active fail2ban >/dev/null 2>&1 \
    || CRITICAL+=("fail2ban não está active")
}

check_unattended() {
  systemctl is-active unattended-upgrades >/dev/null 2>&1 \
    || CRITICAL+=("unattended-upgrades não está active")
}

check_authorized_keys() {
  local actual
  actual=$(sha256sum /root/.ssh/authorized_keys 2>/dev/null | awk '{print $1}')
  if [[ "$actual" != "$EXPECTED_AUTHKEYS_HASH" ]]; then
    CRITICAL+=("authorized_keys do root mudou (hash=$actual, esperado=${EXPECTED_AUTHKEYS_HASH:0:16}…). Rodar /security-audit")
  fi
}

check_env_perms() {
  local offenders
  offenders=$(find /opt/stormlab -maxdepth 4 -name '.env' -type f ! -perm 600 2>/dev/null | head -5)
  if [[ -n "$offenders" ]]; then
    while IFS= read -r f; do
      CRITICAL+=(".env com perm != 0600: $f")
    done <<< "$offenders"
  fi
}

check_public_ports() {
  # Portas em 0.0.0.0 / :: fora da whitelist
  local offenders
  offenders=$( { ss -tlnp 2>/dev/null \
    | awk '{print $4}' \
    | grep -E '^(0\.0\.0\.0|\[::\]):[0-9]+$' \
    | sed -E 's/.*:([0-9]+)$/\1/' \
    | sort -u; } || true )
  while IFS= read -r port; do
    [[ -z "$port" ]] && continue
    local found=false
    for expected in "${EXPECTED_PUBLIC_PORTS[@]}"; do
      [[ "$port" == "$expected" ]] && found=true && break
    done
    $found || CRITICAL+=("Porta pública inesperada: $port (0.0.0.0 ou ::)")
  done <<< "$offenders"
}

check_docker_daemon() {
  if ss -tlnp 2>/dev/null | grep -qE ':237[56] '; then
    CRITICAL+=("Docker daemon exposto em 2375/2376")
  fi
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
      CRITICAL+=("Postgres bindado fora de 127.0.0.1: $bind")
    done <<< "$offenders"
  fi
}

check_security_updates() {
  local count
  count=$(apt list --upgradable 2>/dev/null | grep -ic 'security' || true)
  if [[ "$count" -gt 0 ]]; then
    WARNINGS+=("$count pacote(s) de security pending (unattended-upgrades falhou?)")
  fi
}

check_login_failures() {
  local count
  count=$(journalctl -u ssh --since '7 days ago' 2>/dev/null \
    | grep -cE 'Failed password|Invalid user' || true)
  if [[ "$count" -gt "$MAX_LOGIN_FAILURES_7D" ]]; then
    WARNINGS+=("$count falhas de login nos últimos 7d (fail2ban saturado?)")
  fi
}

check_backup_age() {
  if [[ ! -f "$BACKUP_LOG" ]]; then
    WARNINGS+=("$BACKUP_LOG inexistente — backup rodou alguma vez?")
    return
  fi
  local last_success_epoch now_epoch age_h
  last_success_epoch=$(stat -c %Y "$BACKUP_LOG" 2>/dev/null || echo 0)
  now_epoch=$(date +%s)
  age_h=$(( (now_epoch - last_success_epoch) / 3600 ))
  if [[ "$age_h" -gt "$MAX_BACKUP_AGE_HOURS" ]]; then
    WARNINGS+=("Último write em $BACKUP_LOG foi há ${age_h}h (esperado < ${MAX_BACKUP_AGE_HOURS}h)")
  fi
}

# ─── Run all checks ───────────────────────────────────────────────────────────
check_ssh_config
check_ufw
check_fail2ban
check_unattended
check_authorized_keys
check_env_perms
check_public_ports
check_docker_daemon
check_postgres_binds
check_security_updates
check_login_failures
check_backup_age

# ─── Report ───────────────────────────────────────────────────────────────────
TOTAL=$(( ${#CRITICAL[@]} + ${#WARNINGS[@]} ))

echo "[security-check $(date -Iseconds)] critical=${#CRITICAL[@]} warnings=${#WARNINGS[@]}"
for c in "${CRITICAL[@]:-}"; do [[ -n "$c" ]] && echo "  🔴 $c"; done
for w in "${WARNINGS[@]:-}"; do [[ -n "$w" ]] && echo "  🟡 $w"; done

[[ "$TOTAL" -eq 0 ]] && exit 0

# ─── Notify Telegram ──────────────────────────────────────────────────────────
if [[ -z "$TELEGRAM_BOT_TOKEN" || -z "$TELEGRAM_CHAT_ID" ]]; then
  echo "⚠ Telegram creds ausentes em $STORM_AGENTS_ENV — alertas não enviados"
  exit 1
fi

MSG="*\[Storm Lab Security\] $(date +%Y-%m-%d)*"$'\n'
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
