#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${HOME}/.gemini/config/plugins/agy-context"

echo "Installing Antigravity Context Insight to ${TARGET_DIR} ..."

mkdir -p "${TARGET_DIR}/assets" "${TARGET_DIR}/skills/context" "${TARGET_DIR}/ui/src"
cp "${REPO_DIR}/plugin.json" "${TARGET_DIR}/plugin.json"
cp "${REPO_DIR}/analytics.py" "${TARGET_DIR}/analytics.py"
cp "${REPO_DIR}/server.py" "${TARGET_DIR}/server.py"
cp "${REPO_DIR}/requirements.txt" "${TARGET_DIR}/requirements.txt"
cp "${REPO_DIR}/assets/logo.svg" "${TARGET_DIR}/assets/logo.svg"
cp "${REPO_DIR}/skills/context/SKILL.md" "${TARGET_DIR}/skills/context/SKILL.md"
cp "${REPO_DIR}/ui/app.html" "${TARGET_DIR}/ui/app.html"
cp "${REPO_DIR}/ui/src/app.ts" "${TARGET_DIR}/ui/src/app.ts"

VENV_DIR="${TARGET_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"

if command -v uv >/dev/null 2>&1; then
  echo "Creating Python venv with uv..."
  uv venv "${VENV_DIR}" --python 3.12
  uv pip install --python "${PYTHON_BIN}" -r "${TARGET_DIR}/requirements.txt"
elif command -v python3 >/dev/null 2>&1; then
  echo "Creating Python venv with python3..."
  python3 -m venv "${VENV_DIR}"
  "${PYTHON_BIN}" -m pip install -r "${TARGET_DIR}/requirements.txt"
else
  echo "Error: Neither 'uv' nor 'python3' found in PATH." >&2
  exit 1
fi

cat > "${TARGET_DIR}/mcp_config.json" <<EOF
{
  "mcpServers": {
    "context": {
      "command": "${PYTHON_BIN}",
      "args": [
        "${TARGET_DIR}/server.py"
      ]
    }
  }
}
EOF

echo ""
echo "Installed successfully!"
echo "Open Antigravity -> side pane '+' menu, left sidebar -> Context Insight, or type /context in chat."
