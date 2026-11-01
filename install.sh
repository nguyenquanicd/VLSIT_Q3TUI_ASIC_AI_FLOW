#!/usr/bin/env bash
# Q3TUI installer — installs the `q3tui` command with `uv tool` (the same way a developer install works here):
#
#   ./install.sh                 install (editable: `git pull` updates it) into ~/.local/bin
#   ./install.sh --no-editable   install a copy (an update needs ./install.sh again)
#   ./install.sh --uninstall     remove the command
#   ./install.sh --dry-run       print what would be done, change nothing
#
# Needs: bash, curl or an existing `uv` (the script can install uv for you), network access for the Python packages
# (or an internal PyPI mirror: UV_INDEX_URL=...). Python >= 3.11 is fetched by uv when the system one is older.
# Not installed by this script: Synopsys tools (VCS, Design Compiler — your site's modules) and Claude access.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EDITABLE=1
DRY=0
UNINSTALL=0
ASSUME_YES=0
PYTHON_REQ=">=3.11"

usage() { sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; }

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
  [ "$DRY" = 1 ] || ok "removed (your \$Q3TUI_HOME and your projects are untouched)"
  exit 0
fi

# --- checks -----------------------------------------------------------------------------------------------------------
[ -f "$REPO/pyproject.toml" ] || die "run this script from a Q3TUI checkout (pyproject.toml not found in $REPO)"
say "installing Q3TUI from $REPO"
[ "$(uname -s)" = "Linux" ] || warn "tested on Linux only (EDA tools are Linux tools)"
ensure_uv

# --- install ----------------------------------------------------------------------------------------------------------
say "installing the 'q3tui' command (uv tool, Python $PYTHON_REQ)"
args=(tool install --force --python "$PYTHON_REQ")
if [ "$EDITABLE" = 1 ]; then args+=(--editable "$REPO"); else args+=("$REPO"); fi
run uv "${args[@]}"

BIN_DIR="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
case ":$PATH:" in
  *":$BIN_DIR:"*) ok "$BIN_DIR is on PATH" ;;
  *) warn "$BIN_DIR is not on PATH — run 'uv tool update-shell' (or add 'export PATH=\"$BIN_DIR:\$PATH\"' to your shell profile) and open a new shell" ;;
esac

# --- user config (spec/config.md "Defaults and installation") ---------------------------------------------------------
TOOL_PY="$(uv tool dir 2>/dev/null)/q3tui/bin/python"
if [ "$DRY" = 1 ]; then
  printf '   [dry-run] create %s/config.yaml if it is missing (llm.model, llm.effort, pipeline.flow)\n' "${Q3TUI_HOME:-$HOME/.q3tui}"
else
  "$TOOL_PY" -c '
from q3tui.config import install_user_config
from q3tui.paths import user_config_file
path = user_config_file()
print(" \033[32m✔\033[0m", "created" if install_user_config(path) else "keeping your", "user config:", path)
'
fi

# --- the default flow (spec/config.md "Defaults and installation") ----------------------------------------------------
# The site `vlsit`, at the newest tag of its repository when it is installed; one already installed is kept (update it
# from Settings ▸ Sites & packages).
FLOW_SITE=vlsit
FLOW_GIT=https://github.com/nguyenquanicd/VLSIT_Q3CORE_ASIC_AI_FLOW
if [ "$DRY" = 1 ]; then
  printf '   [dry-run] install the flow site %s from %s at its newest tag, if it is not installed\n' "$FLOW_SITE" "$FLOW_GIT"
else
  FLOW_SITE="$FLOW_SITE" FLOW_GIT="$FLOW_GIT" "$TOOL_PY" -c '
import os
from q3tui.paths import q3tui_home
from q3tui.workspace.sites import SiteError, Sites, latest_tag
name, git = os.environ["FLOW_SITE"], os.environ["FLOW_GIT"]
sites = Sites(q3tui_home())
if name in sites.read():
    print(f" \033[32m✔\033[0m keeping the flow site {name} at {sites.installed_ref(name)}")
    raise SystemExit
try:
    tag = latest_tag(git)
    if tag is None:
        raise SiteError(f"{git} has no tag yet")
    sites.install(name, git, tag)
    print(f" \033[32m✔\033[0m installed the flow site {name} from {git} at {tag}")
except SiteError as exc:
    print(f" \033[33m!\033[0m the flow site {name} is not installed: {exc}")
    print(f"   install it later: rerun ./install.sh, or clone {git} and link it into {q3tui_home()}")
'
fi

# --- what the script cannot do for you --------------------------------------------------------------------------------
if command -v claude >/dev/null 2>&1; then
  ok "Claude Code found: $(command -v claude) (Q3TUI uses the Claude Agent SDK: log in with 'claude' once, or set ANTHROPIC_API_KEY)"
else
  warn "Claude Code CLI not found: Q3TUI's LLM calls go through the Claude Agent SDK; install Claude Code and log in, or set ANTHROPIC_API_KEY"
fi
if command -v module >/dev/null 2>&1 || [ -f /etc/profile.d/modules.sh ]; then
  ok "environment modules available (the tools load them through tools.modules in the config)"
else
  warn "no 'module' command: the tools must be on PATH, or set tools.setup_script in the config"
fi

# --- verify -----------------------------------------------------------------------------------------------------------
if [ "$DRY" != 1 ]; then
  say "checking the install"
  export PATH="$BIN_DIR:$PATH"
  command -v q3tui >/dev/null 2>&1 || die "the q3tui command is not on PATH yet (see the PATH note above)"
  q3tui --help >/dev/null && ok "q3tui runs"
fi

cat <<EOF

$(printf '\033[1m')Next steps$(printf '\033[0m')
  Install a flow (a site linked into \$Q3TUI_HOME: spec/workspace.md "Sites"), then:
  mkdir my_block && cd my_block
  q3tui                   # opens the TUI: write the intent on Home, then run (Ctrl+R)
Spec: $REPO/spec/
EOF
