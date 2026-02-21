#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 "$ROOT_DIR/agent.py" init >/dev/null
python3 "$ROOT_DIR/agent.py" refresh-alerts >/dev/null

ARGS=()
if [[ -n "${PE_AGENT_SLACK_WEBHOOK:-}" ]]; then
  ARGS+=("--notify-slack-env" "PE_AGENT_SLACK_WEBHOOK")
fi
if [[ -n "${PE_AGENT_TEAMS_WEBHOOK:-}" ]]; then
  ARGS+=("--notify-teams-env" "PE_AGENT_TEAMS_WEBHOOK")
fi

python3 "$ROOT_DIR/agent.py" daily-brief "${ARGS[@]}"
