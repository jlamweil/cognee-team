#!/usr/bin/env bash
# Client installer for PEOPLE and AGENTS who only CONSUME the team memory.
#
#   ./install_client.sh http://<server-host>:8000 <api-key>
#
# No cognee, no venv, no server code. Installs:
#   - uv + cognee-mcp (official MCP bridge, usable as MCP server or CLI)
#   - `cogctl` wrapper: store / recall / list / me against the team server
#   - ~/.config/cogctl.json (chmod 600) with endpoint + key
# Exit: 0 ok, 1 bad args, 2 server unreachable or key rejected.
set -euo pipefail

[[ $# -eq 2 ]] || { echo "usage: $0 http://<server-host>:8000 <api-key>" >&2; exit 1; }
URL="${1%/}"
KEY="$2"

say() { printf '\n== %s ==\n' "$*"; }

# 0) reachability + auth (X-Api-Key) --------------------------------------
say "0/3 check server"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "X-Api-Key: $KEY" "$URL/api/v1/datasets") || code=000
if [[ "$code" != "200" ]]; then
  echo "FAIL: $URL/api/v1/datasets -> HTTP $code (need 200: server up + valid key)" >&2
  exit 2
fi
echo "  authenticated: $URL"

# 1) uv + cognee-mcp -------------------------------------------------------
say "1/3 uv + cognee-mcp"
if ! command -v uvx >/dev/null 2>&1; then
  command -v pipx >/dev/null 2>&1 && pipx install uv || curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uvx --from cognee-mcp cognee-mcp --help >/dev/null 2>&1 || true  # warm the cache

# 2) config ------------------------------------------------------------------
say "2/3 config"
CFG="$HOME/.config/cogctl.json"
mkdir -p "$(dirname "$CFG")"
cat > "$CFG" <<EOF
{"url": "$URL", "api_key": "$KEY"}
EOF
chmod 600 "$CFG"

# 3) cogctl wrapper ----------------------------------------------------------
say "3/3 cogctl"
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
cat > "$BIN/cogctl" <<'WRAPPER'
#!/usr/bin/env bash
# Team-memory client. Usage:
#   cogctl list                        datasets visible to you
#   cogctl recall "question" <uuid>    search a dataset (UUID from list; no LLM)
#   cogctl store <file> <uuid-or-name> add a document (your own or public)
#   cogctl me                          who the server thinks you are
set -euo pipefail
CFG="$HOME/.config/cogctl.json"
URL=$(python3 -c "import json;print(json.load(open('$CFG'))['url'])")
KEY=$(python3 -c "import json;print(json.load(open('$CFG'))['api_key'])")
H=(-H "X-Api-Key: $KEY")
c() { curl -s -m 120 "${H[@]}" "$@"; }
case "${1:-help}" in
  list) c "$URL/api/v1/datasets" | python3 -m json.tool;;
  me)   c "$URL/api/v1/auth/me" | python3 -m json.tool;;
  recall)
    [[ $# -eq 3 ]] || { echo "usage: cogctl recall \"query\" <dataset-uuid>" >&2; exit 1; }
    python3 - "$URL" "$KEY" "$2" "$3" <<'PY'
import json, sys, urllib.request
url, key, query, ds = sys.argv[1:5]
req = urllib.request.Request(url + "/api/v1/search", method="POST",
    data=json.dumps({"query": query, "search_type": "CHUNKS", "dataset_ids": [ds]}).encode(),
    headers={"X-Api-Key": key, "Content-Type": "application/json"})
try:
    body = json.load(urllib.request.urlopen(req, timeout=120))
except urllib.error.HTTPError as e:
    sys.exit(f"HTTP {e.code}: {e.read().decode()[:300]}")
print(json.dumps(body, indent=2)[:2000])
PY
    ;;
  store)
    [[ $# -eq 3 ]] || { echo "usage: cogctl store <file> <dataset-uuid-or-name>" >&2; exit 1; }
    file="$2"; target="$3"
    [[ -f "$file" ]] || { echo "no such file: $file" >&2; exit 1; }
    if [[ "$target" =~ ^[0-9a-fA-F-]{36}$ ]]; then dsid="$target"; else
      dsid=$(c "$URL/api/v1/datasets" | TARGET="$target" python3 -c "
import json,sys,os
t=os.environ['TARGET']
try: print(next(d['id'] for d in json.load(sys.stdin) if d['name']==t))
except StopIteration: sys.exit('no visible dataset named '+t)")
    fi
    c -X POST "$URL/api/v1/add" -F "data=@$file" -F "datasetId=$dsid" >/dev/null
    echo "stored $file -> $dsid (cognify happens on the server's schedule)"
    ;;
  *) grep '^#' "$0" | sed 's/^# \{0,1\}//';;
esac
WRAPPER
chmod +x "$BIN/cogctl"

say "CLIENT OK"
echo "  cogctl list | recall \"q\" <uuid> | store <file> <uuid> | me"
echo "  MCP config for agents: see cognee-team/mcp/README.md"
