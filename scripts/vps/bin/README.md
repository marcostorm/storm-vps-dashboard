# Wrappers SSH restritivos — `/opt/stormlab/bin/`

Scripts referenciados em `/root/.ssh/authorized_keys` via `command=` pra transformar chaves de CI em "disparadores de um deploy específico" em vez de SSH genérico.

Defense in depth: se a chave privada do CI vazar, o atacante não consegue shell, docker, rsync arbitrário, ou leitura/escrita fora do escopo do script.

## `paxiuba-deploy.sh`

- **Chave:** `github-actions-paxiuba-deploy` (comment no authorized_keys)
- **Workflow:** `marcos-storm/paxiuba-literaria → .github/workflows/deploy.yml`
- **Protocolo:** cliente envia `deploy <sha40>`
- **O que executa:** `git reset --hard <sha>` em `/opt/stormlab/paxiuba/` + `bash scripts/deploy/remote.sh`

Rejeita qualquer outra forma de comando (incluindo shell interativo).

## Deploy manual (quando o script muda)

```bash
rsync -av scripts/vps/bin/paxiuba-deploy.sh \
  root@187.127.249.58:/opt/stormlab/bin/
ssh root@187.127.249.58 "chmod 755 /opt/stormlab/bin/paxiuba-deploy.sh"
```

## Testar standalone (antes de aplicar command=)

```bash
ssh root@187.127.249.58 '
  # ✔ válido
  SSH_ORIGINAL_COMMAND="deploy $(git -C /opt/stormlab/paxiuba rev-parse HEAD)" \
    /opt/stormlab/bin/paxiuba-deploy.sh

  # ✘ cmd arbitrário — deve rejeitar
  SSH_ORIGINAL_COMMAND="rm -rf /" /opt/stormlab/bin/paxiuba-deploy.sh || echo "OK rejeitado"

  # ✘ sem cmd — deve rejeitar
  /opt/stormlab/bin/paxiuba-deploy.sh || echo "OK rejeitado"
'
```

## Relacionado

- `github-actions-marcostorm-site-deploy` usa `rrsync` direto (não precisa de wrapper custom)
- `github-actions-deploy` (storm-commerce) ainda sem wrapper — deploy baseado em `docker save | ssh ... "docker load"` precisa refator pra registry antes de fechar.
