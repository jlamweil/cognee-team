#!/usr/bin/env bash
# One-shot installer for the cognee-team memory server.
#
#   ./install_server.sh --root /srv/cognee-team
#
# Idempotent: re-run to upgrade/reconfigure. What it does:
#   1. installs uv (pipx fallback) if missing
#   2. syncs this repo's cognee-team/ to --root (excl. venv/data/credentials/.env)
#   3. python3.11 venv + `cognee[api]` + fastembed via uv
#   4. materializes .env from .env.template with generated secrets + host paths
#   5. (optional) Ollama model pull when --ollama given
#   6. runs bootstrap.py (server stopped), installs + starts the systemd unit
#   7. runs verify.py; nonzero exit on any failure
set -euo pipefail

ROOT=""
WITH_OLLAMA=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="${2:?}"; shift 2;;
    --ollama) WITH_OLLAMA=1; shift;;
    *) echo "usage: $0 --root /srv/cognee-team [--ollama]" >&2; exit 1;;
  esac
done
[[ -n "$ROOT" ]] || { echo "usage: $0 --root /srv/cognee-team [--ollama]" >&2; exit 1; }
mkdir -p "$ROOT"

SRC="$(cd "$(dirname "$0")" && pwd)"

say() { printf '\n== %s ==\n' "$*"; }

# 1) uv ------------------------------------------------------------------
say "1/7 uv"
if ! command -v uv >/dev/null 2>&1; then
  command -v pipx >/dev/null 2>&1 && pipx install uv || curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

# 2) sync code -------------------------------------------------------------
say "2/7 sync code -> $ROOT"
mkdir -p "$ROOT"
rsync -a --delete \
  --exclude '.venv/' --exclude 'data/' --exclude 'credentials/' \
  --exclude '.env' --exclude '__pycache__/' \
  "$SRC"/ "$ROOT"/

# 3) venv + deps -----------------------------------------------------------
say "3/7 venv + cognee[api] + fastembed"
cd "$ROOT"
[[ -d .venv ]] || uv venv .venv --python 3.11
uv pip install --python .venv/bin/python "cognee[api]" fastembed

# 4) .env ------------------------------------------------------------------
say "4/7 .env from template"
gen() { python3 -c 'import secrets;print(secrets.token_urlsafe(48))'; }
if [[ -f .env ]]; then
  echo "  .env exists — keeping it (secrets preserved). Update manually from .env.template."
else
  sed -e "s|__DATA_ROOT__|$ROOT|g" \
      -e "s|__GENERATE__|$(gen)|g" \
      .env.template > .env
  chmod 600 .env
  echo "  wrote .env (JWT secrets generated)"
fi

# 5) ollama (optional) -----------------------------------------------------
if [[ $WITH_OLLAMA -eq 1 ]]; then
  say "5/7 ollama models"
  command -v ollama >/dev/null 2>&1 || { echo "ollama not found; install https://ollama.com first" >&2; exit 1; }
  ollama pull qwen2.5:7b-instruct
else
  say "5/7 ollama — skipped (--ollama to pull qwen2.5:7b-instruct)"
fi

# 6) bootstrap + systemd ---------------------------------------------------
say "6/7 bootstrap (server stopped)"
SYSTEMD_UNIT=/home/$(id -un)/.config/systemd/user/cognee-team-api.service
if systemctl --user is-active --quiet cognee-team-api.service 2>/dev/null; then
  systemctl --user stop cognee-team-api.service
fi
mkdir -p "$ROOT/data/databases" "$ROOT/data/logs" "$ROOT/data/repos" "$ROOT/credentials"
chmod 700 "$ROOT/credentials"
.venv/bin/python bootstrap.py

mkdir -p "$(dirname "$SYSTEMD_UNIT")"
cat > "$SYSTEMD_UNIT" <<EOF
[Unit]
Description=cognee team memory API (multi-tenant, auth enforced, tiered)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT
ExecStart=$ROOT/run_api.sh
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now cognee-team-api.service
sleep 8

# 7) verify ------------------------------------------------------------------
say "7/7 verify (19 checks)"
if .venv/bin/python verify.py; then
  say "INSTALL OK — server on :8000, tiers enforced"
  echo "Credentials: $ROOT/credentials/*.json (chmod 600; share per-person)"
  echo "Next: edit roster.json (real emails + member_agents), stop server, re-run bootstrap.py, verify.py"
else
  say "VERIFY FAILED — see output above"; exit 1
fi
