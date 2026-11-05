#!/usr/bin/env bash
# Q3TUI installer — installs the `q3tui` command with `uv tool` (the same way a developer install works here):
#
#   curl -fsSL https://raw.githubusercontent.com/nguyenquanicd/VLSIT_Q3TUI_ASIC_AI_FLOW/main/install.sh | bash
#                                one line, no clone: installs the latest from git (Q3TUI_REF=<tag|branch> picks another,
#                                Q3TUI_REPO_URL=<git url> another repository). Re-run it to update.
#   ./install.sh                 from a checkout: install (editable: `git pull` updates it) into ~/.local/bin
#   ./install.sh --no-editable   install a copy (an update needs ./install.sh again)
#   ./install.sh --uninstall     remove the command
#   ./install.sh --dry-run       print what would be done, change nothing
#
# Needs: bash, curl or an existing `uv` (the script can install uv for you), network access for the Python packages
# (or an internal PyPI mirror: UV_INDEX_URL=...). Python >= 3.12 is fetched by uv when the system one is older.
# Also installs the LLM gateway (LiteLLM, in its own uv environment) used by the OpenAI providers.
# Not installed by this script: any EDA tool (yours: on PATH or loaded through tools.json) and LLM access (a login or a key).

set -euo pipefail

# A checkout when the script sits beside pyproject.toml; otherwise (`curl … | bash`) install from git.
SELF="${BASH_SOURCE[0]:-}"
REPO=""
if [ -n "$SELF" ] && [ -f "$(dirname "$SELF")/pyproject.toml" ]; then
  REPO="$(cd "$(dirname "$SELF")" && pwd)"
fi
GIT_URL="${Q3TUI_REPO_URL:-https://github.com/nguyenquanicd/VLSIT_Q3TUI_ASIC_AI_FLOW.git}"
GIT_REF="${Q3TUI_REF:-}"
EDITABLE=1
DRY=0
UNINSTALL=0
ASSUME_YES=0
PYTHON_REQ=">=3.12"

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --no-editable) EDITABLE=0 ;;
    --editable)    EDITABLE=1 ;;
    --uninstall)   UNINSTALL=1 ;;
    --dry-run|-n)  DRY=1 ;;
    --yes|-y)      ASSUME_YES=1 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m ✔\033[0m %s\n' "$*"; }
warn() { printf '\033[33m !\033[0m %s\n' "$*"; }
die()  { printf '\033[31m ✖\033[0m %s\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY" = 1 ]; then printf '   [dry-run] %s\n' "$*"; else "$@"; fi; }

# --- uv ---------------------------------------------------------------------------------------------------------------
ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    ok "uv $(uv --version | awk '{print $2}')"
    return
  fi
  warn "uv is not installed (https://docs.astral.sh/uv/)"
  if [ "$ASSUME_YES" != 1 ] && [ "$DRY" != 1 ]; then
    read -r -p "    install uv now with the official installer (curl | sh)? [y/N] " a
    case "$a" in y|Y|yes) ;; *) die "uv is required: install it (e.g. 'pip install uv' or your site's package) and run again" ;; esac
  fi
  command -v curl >/dev/null 2>&1 || die "curl is needed to fetch the uv installer (or install uv yourself)"
  if [ "$DRY" = 1 ]; then
    printf '   [dry-run] curl -LsSf https://astral.sh/uv/install.sh | sh\n'
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv >/dev/null 2>&1 || die "uv was installed but is not on PATH: open a new shell and run again"
  fi
}

# --- uninstall --------------------------------------------------------------------------------------------------------
if [ "$UNINSTALL" = 1 ]; then
  command -v uv >/dev/null 2>&1 || die "uv not found: nothing to uninstall with"
  say "removing the q3tui command"
  run uv tool uninstall q3tui
  [ "$DRY" = 1 ] || ok "removed (your ~/.q3tui settings and your projects are untouched)"
  exit 0
fi

# --- checks -----------------------------------------------------------------------------------------------------------
if [ -n "$REPO" ]; then
  say "installing Q3TUI from $REPO"
  SOURCE="$REPO"
else
  SOURCE="git+${GIT_URL}${GIT_REF:+@$GIT_REF}"
  say "installing Q3TUI from $SOURCE"
  EDITABLE=0   # nothing to edit without a checkout
fi
[ "$(uname -s)" = "Linux" ] || warn "tested on Linux only (EDA tools are Linux tools)"
ensure_uv

# --- install ----------------------------------------------------------------------------------------------------------
say "installing the 'q3tui' command (uv tool, Python $PYTHON_REQ)"
args=(tool install --force --python "$PYTHON_REQ")
if [ "$EDITABLE" = 1 ]; then args+=(--editable "$SOURCE"); else args+=("$SOURCE"); fi
run uv "${args[@]}"

BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
case ":$PATH:" in
  *":$BIN_DIR:"*) ok "$BIN_DIR is on PATH" ;;
  *) warn "$BIN_DIR is not on PATH — run 'uv tool update-shell' (or add 'export PATH=\"$BIN_DIR:\$PATH\"' to your shell profile) and open a new shell" ;;
esac

# --- user settings ----------------------------------------------------------------------------------------------------
CONF_DIR="${Q3TUI_HOME:-$HOME/.q3tui}"
if [ -f "$CONF_DIR/q3tui.yaml" ]; then
  ok "keeping your settings: $CONF_DIR/q3tui.yaml"
elif [ -n "$REPO" ] && [ -f "$REPO/q3tui.example.yaml" ]; then
  say "writing a starting configuration: $CONF_DIR/q3tui.yaml (edit the model, tool modules, flow)"
  run mkdir -p "$CONF_DIR"
  run cp "$REPO/q3tui.example.yaml" "$CONF_DIR/q3tui.yaml"
else
  warn "no starting configuration written (none needed: the defaults work; see q3tui.example.yaml in the repository to set EDA tool modules)"
fi

# --- what the script cannot do for you --------------------------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
  ok "Claude Code found: $(command -v claude) (log in with 'claude' once; or pick another provider: Settings → Provider, 'q3tui gateway status')"
else
  warn "Claude Code CLI not found — Q3TUI's LLM calls go through the Claude Agent SDK: install Claude Code and log in, or pick another provider (Settings → Provider)"
fi
if command -v module >/dev/null 2>&1 || [ -f /etc/profile.d/modules.sh ]; then
  ok "environment modules available (EDA tools can be loaded through tools.json 'modules')"
else
  warn "no 'module' command: EDA tools must be on PATH, or set 'setup_script' in tools.json"
fi

# --- verify -----------------------------------------------------------------------------------------------------------
if [ "$DRY" != 1 ]; then
  say "checking the install"
  export PATH="$BIN_DIR:$PATH"
  command -v q3tui >/dev/null 2>&1 || die "the q3tui command is not on PATH yet (see the PATH note above)"
  q3tui --version
  q3tui flow list
  # the gateway of the OpenAI providers (llm.provider: openai | openai_api): LiteLLM in its own environment
  # (~/.q3tui/gateway/venv), made now so the first stage or login that needs it does not wait for the install
  say "installing the LLM gateway (LiteLLM) for the OpenAI providers"
  q3tui gateway install || warn "the LLM gateway did not install now; Q3TUI installs it on first use (only the OpenAI providers need it)"
fi

cat <<EOF

$(printf '\033[1m')Next steps$(printf '\033[0m')
  mkdir my_block && cd my_block
  q3tui tools init        # tools.json: a suggested reference set of tool roles — adapt it to the EDA tools of your site
  q3tui tools check       # are the tools found?
  q3tui init              # spec/intent.md skeleton (or put your spec in spec/); \`q3tui\` alone opens the TUI (r runs, ? for keys)
Docs: docs/user_guide.md · design: docs/spec/README.md · examples/ (in the repository)
EOF
