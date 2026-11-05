# scripts/local

Vigia de segurança da **workstation do Marcos** (laptop/desktop onde rodam RAG,
MCPs, watchers que leem home). Irmão paridade de `scripts/vps/security-check.sh`,
que cobre o VPS Hostinger. Os dois perímetros são complementares — o skill
`/security-audit` cruza ambos.

## Instalar

```bash
./install.sh
```

Cria symlinks em `~/.config/systemd/user/` apontando pros units dentro do repo
(pull atualiza o conteúdo), habilita o timer e mostra o status. Log em
`~/.local/state/storm-security-local.log`.

## Rodar manualmente (pra testar sem esperar o timer)

```bash
systemctl --user start storm-security-local.service
tail -f ~/.local/state/storm-security-local.log
```

## O que o script checa

| Check | Severidade | O que flagga |
|---|---|---|
| Portas em `0.0.0.0`/`::` | 🔴 | Qualquer bind não-localhost na máquina |
| Postgres fora de `127.0.0.1` | 🔴 | Caso específico (RAG, Paxiúba, etc) |
| Docker daemon 2375/2376 | 🔴 | Daemon TCP sem TLS |
| Perms `~/.ssh` + chaves privadas | 🔴 | `~/.ssh` != 700 ou chave priv != 600 |
| Perms `~/.claude` + subdirs | 🔴 | != 700/750 |
| Secrets em `~/.claude/.../memory/` | 🔴 | Regex de API keys / private keys |
| Pacotes de security pendentes | 🔴 | `apt list --upgradable` filtrando `security` |
| Chaves SSH sem passphrase | 🟡 | Qualquer `id_*` que abre com passphrase vazia |
| Senhas triviais em `docker-compose*.yml` | 🟡 | `rag`, `postgres`, `admin`, `password`, `123`, `changeme` |
| `.env` em `~/workspace/*` com perm != 600/400 | 🟡 | find em até 3 níveis |
| UFW ausente ou inativo | 🟡 | Firewall local desligado |
| Pacotes upgradable > 50 | 🟡 | Backlog de updates |
| `storm-rag-watch.service` inativo | 🟡 | RAG está defasando |

Silêncio = verde. Alerta pro `@storm_agents_bot` só se houver finding.
Credenciais do bot vêm de `~/workspace/storm-agents/.env` (mesmo arquivo do
watchdog local — não duplica secret).

## Baseline / falsos positivos

- `EXPECTED_PUBLIC_PORTS` no topo do script: lista vazia por default. Workstation
  não deveria publicar nada. Se um serviço legítimo precisa bind global, adicione
  a porta aqui com comentário do porquê.
- `MAX_UPGRADABLE=50` — threshold de warning pra backlog de updates comum. Tunar
  conforme ritmo de `apt upgrade`.

## Diferenças vs. o script do VPS

- Não checa `fail2ban`, `unattended-upgrades`, nem `authorized_keys` (workstation
  não expõe SSH).
- Adiciona checks que só fazem sentido localmente: perms `~/.claude`, secrets em
  memória, senhas triviais em compose do workspace, watcher do RAG.
- Roda via `systemd --user` (sem precisar de root).
- Timer Mon 09:00 (VPS roda Mon 05:00 UTC — defasados pra não concorrerem na mesma janela).
