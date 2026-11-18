#!/usr/bin/env bash
# PreToolUse hook: reject large edits to code files.
# All implementation code must go through worker models (cheap cloud or local).
# Coordinator sessions (PM, Dev Lead, Tech Writer) coordinate, verify, and
# apply worker output — they don't write implementation code themselves.
#
# Prose (.md, .txt) is exempt — coordinators handle prose better than most
# worker models.
# Config (.toml, .json, .yaml, .yml) is exempt — small by nature, often
# hand-edited.
#
# Install: copy this file into your project's .claude/hooks/ (or equivalent
# hook directory). Wire it in settings.json as a PreToolUse hook on Edit
# and Write. See the settings.json template alongside this file.
#
# Reads the tool input JSON from stdin (Claude Code convention).
# Exits 0 to allow, exits 2 to block with a message on stderr.
#
# Tuning: adjust MAX_LINES (default 20) and the extension list to fit your
# project. 20 lines lets coordinators apply worker output in chunks, fix
# compile errors, and make wiring one-liners.

set -euo pipefail

MAX_LINES="${ENFORCE_WORKER_MAX_LINES:-20}"

INPUT=$(cat)

TOOL_NAME="${CLAUDE_TOOL_NAME:-}"

case "$TOOL_NAME" in
  Edit|Write) ;;
  *) exit 0 ;;
esac

FILE_PATH=$(echo "$INPUT" | python3 -Ic "
import json, sys
d = json.load(sys.stdin)
print(d.get('file_path', '') or '')
")

# Code files: blocked above MAX_LINES
# Add or remove extensions for your stack
case "$FILE_PATH" in
  *.rs|*.py|*.sh|*.sql|*.lua|*.js|*.ts|*.jsx|*.tsx|*.css|*.html|*.go|*.rb|*.java|*.kt|*.c|*.cpp|*.h|*.hpp|*.cs|*.swift|*.zig) ;;
  *) exit 0 ;;
esac

LINE_COUNT=$(echo "$INPUT" | python3 -Ic "
import json, sys
d = json.load(sys.stdin)
text = d.get('new_string', '') or d.get('content', '') or ''
print(len(text.splitlines()))
")

if [ "$LINE_COUNT" -gt "$MAX_LINES" ]; then
  EXT="${FILE_PATH##*.}"
  echo "BLOCKED: Writing $LINE_COUNT lines to a .$EXT file exceeds the $MAX_LINES line limit." >&2
  echo "All implementation code must go through worker models (e.g., beam:cloud, gpt-oss, local models)." >&2
  echo "Generate the code with a worker, then apply its output in chunks <= $MAX_LINES lines." >&2
  exit 2
fi

exit 0
