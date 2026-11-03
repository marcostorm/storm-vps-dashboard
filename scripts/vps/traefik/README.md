# Traefik — config versionada

Snapshot do que roda em `/opt/stormlab/traefik/` do VPS. Não é deploy automatizado — serve de **referência versionada** pra:

1. Rastrear mudanças de config
2. Rollback rápido se o arquivo no VPS for perdido
3. Reproducibilidade (incluindo rebuild do VPS do zero)

**Arquivos sensíveis fora daqui:**
- `acme.json` (cert Let's Encrypt + chaves privadas) — fica só no VPS, perm 0600
- Hash SHA1 do basic auth do dashboard — vive em `/opt/stormlab/traefik/.env` como `TRAEFIK_DASHBOARD_AUTH`, nunca commitado

**Antes do primeiro deploy** (ou se perder o .env):

```bash
# Gera o hash a partir de uma senha nova:
printf "senha-nova" | openssl dgst -sha1 -binary | base64 -w0 && echo
# Grava no .env:
ssh root@187.127.249.58 "echo 'TRAEFIK_DASHBOARD_AUTH=admin:{SHA}<HASH-GERADO>' > /opt/stormlab/traefik/.env && chmod 600 /opt/stormlab/traefik/.env"
```

## Deploy manual

```bash
rsync -av scripts/vps/traefik/docker-compose.yml \
         scripts/vps/traefik/traefik.yml \
  root@187.127.249.58:/opt/stormlab/traefik/

ssh root@187.127.249.58 "cd /opt/stormlab/traefik && docker compose up -d && docker restart traefik-traefik-1"
```

**Gotcha**: `docker compose up -d` não recria o Traefik quando só o arquivo volume-mounted (`traefik.yml`) muda. Precisa `docker restart` separado.

## Arquitetura

```
Internet
   ↓ :80/:443
Traefik (container, network: stormlab + traefik-docker-proxy)
   │
   ├─ TRAEFIK_PROVIDERS_DOCKER_ENDPOINT = tcp://docker-socket-proxy:2375
   │     ↓
   │  docker-socket-proxy (container, network: traefik-docker-proxy internal:true)
   │     ↓ (read-only, CONTAINERS=1 NETWORKS=1 POST=0)
   │  /var/run/docker.sock (host, :ro)
   │
   └─ routes labels de containers na network `stormlab`
```

Defense in depth: RCE no Traefik não dá acesso ao Docker daemon do host — só a GET limitado via proxy.

## Baseline (2026-11-03)

- `traefik:v2.11`
- `tecnativa/docker-socket-proxy:0.3`
- Resolver: `letsencrypt` (HTTP challenge via entrypoint `web`)
- Email ACME: mhstorms@gmail.com
- Dashboard: `traefik.marcostorm.com.br` com basic auth

Ver [[project-storm-lab-security]] "Hardening 2026-11-03 (3ª onda)" na memória pra contexto da mudança.
