#!/bin/bash
# Launcher daemon de deploy no VPS.
#
# Uso: deploy-async.sh <loja> <tag|-> <run_id>
#
# Dispara /opt/stormlab/scripts/deploy.sh em background e escreve
# estado em /opt/stormlab/runs/<run_id>/:
#   state       running | ok | failed
#   pid         pid do subshell que executa o deploy
#   started_at  ISO-8601
#   ended_at    ISO-8601 (quando acabar)
#   rc          exit code (quando acabar)
#   output.log  stdout+stderr do deploy
#   cmd         comando reconstruído (debug)
#
# Retorna no stdout: "run_id=<id> pid=<pid>"
# O caller (MCP) SSH-exec este script e pega as duas linhas via grep.

set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "uso: $0 <loja> <tag|-> <run_id>" >&2
  exit 2
fi

LOJA="$1"
TAG_RAW="$2"
RUN_ID="$3"

case "$RUN_ID" in
  *..*|*/*|*' '*|'')
    echo "run_id inválido: $RUN_ID" >&2
    exit 2
    ;;
esac

RUNS_ROOT="/opt/stormlab/runs"
RUN_DIR="$RUNS_ROOT/$RUN_ID"
DEPLOY="/opt/stormlab/scripts/deploy.sh"

if [ ! -x "$DEPLOY" ]; then
  echo "deploy.sh não encontrado em $DEPLOY" >&2
  exit 3
fi

if [ -e "$RUN_DIR" ]; then
  echo "run_id já existe: $RUN_DIR" >&2
  exit 4
fi

mkdir -p "$RUN_DIR"

if [ "$TAG_RAW" = "-" ]; then
  TAG=""
else
  TAG="$TAG_RAW"
fi

if [ -n "$TAG" ]; then
  echo "$DEPLOY $LOJA $TAG" > "$RUN_DIR/cmd"
else
  echo "$DEPLOY $LOJA" > "$RUN_DIR/cmd"
fi

date -Iseconds > "$RUN_DIR/started_at"
echo "running" > "$RUN_DIR/state"

# Daemoniza: setsid desatacha do process group do SSH, redireciona IO.
# O subshell interno rastreia o rc do deploy e marca state final.
setsid bash -c '
  RUN_DIR="$1"; DEPLOY="$2"; LOJA="$3"; TAG="$4"
  if [ -n "$TAG" ]; then
    "$DEPLOY" "$LOJA" "$TAG" > "$RUN_DIR/output.log" 2>&1
  else
    "$DEPLOY" "$LOJA" > "$RUN_DIR/output.log" 2>&1
  fi
  RC=$?
  echo "$RC" > "$RUN_DIR/rc"
  date -Iseconds > "$RUN_DIR/ended_at"
  if [ "$RC" -eq 0 ]; then
    echo "ok" > "$RUN_DIR/state"
  else
    echo "failed" > "$RUN_DIR/state"
  fi
' _ "$RUN_DIR" "$DEPLOY" "$LOJA" "$TAG" </dev/null >/dev/null 2>&1 &

PID=$!
echo "$PID" > "$RUN_DIR/pid"
disown "$PID" 2>/dev/null || true

echo "run_id=$RUN_ID pid=$PID"
