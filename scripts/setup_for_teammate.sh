#!/usr/bin/env bash
# One-shot setup for a teammate receiving this project as a zip (code + a Postgres
# dump of the already-tagged data). Run this from inside the unzipped project folder:
#   ./scripts/setup_for_teammate.sh
#
# What it does, in order:
#   1. Checks for `uv` and Postgres, with install hints if either is missing.
#   2. `uv sync` — installs Python dependencies.
#   3. Creates a local Postgres role+database (idempotent — skips if it already exists).
#   4. Restores the bundled saad_gpt_handoff.dump into that database.
#   5. Writes a minimal .env (just SAAD_GPT_DATABASE_URL — nothing else is needed to
#      query already-tagged content).
#   6. Copies the Claude Code skill to ~/.claude/skills/saad-sales-gpt/, baking in
#      this machine's actual project path (no shell profile editing required).
#   7. Registers the MCP server in Claude Desktop's config, preserving any other
#      servers already configured there.
#
# Safe to re-run: every step checks before it acts rather than blindly overwriting.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DUMP_FILE="$PROJECT_DIR/saad_gpt_handoff.dump"
DB_NAME="saad_gpt"
DB_USER="saad_gpt"
DB_PASS="saad_gpt"

echo "==> Project directory: $PROJECT_DIR"

# --- 1. Check prerequisites -------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' is not installed. Install it first:"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "ERROR: PostgreSQL client tools not found. Install Postgres first"
  echo "  (e.g. 'brew install postgresql@16' on macOS), then re-run this script."
  exit 1
fi

if [ ! -f "$DUMP_FILE" ]; then
  echo "ERROR: $DUMP_FILE not found."
  echo "  Make sure saad_gpt_handoff.dump is in the same folder as this project"
  echo "  before running this script."
  exit 1
fi

# --- 2. Python deps ----------------------------------------------------------
echo "==> Installing Python dependencies (uv sync)..."
(cd "$PROJECT_DIR" && uv sync)

# --- 3. Postgres role + database ---------------------------------------------
echo "==> Setting up Postgres role and database..."

# Postgres's default superuser varies by how it was installed: Homebrew makes the
# current Unix user a superuser with no 'postgres' role at all, while apt/Debian-style
# installs create a 'postgres' role instead. Try both rather than assuming one.
ADMIN_USER=""
for candidate in "$(whoami)" postgres; do
  if psql -h localhost -U "$candidate" -d postgres -tc "SELECT 1" >/dev/null 2>&1; then
    ADMIN_USER="$candidate"
    break
  fi
done

if [ -z "$ADMIN_USER" ]; then
  echo "  ERROR: couldn't find a working Postgres superuser (tried '$(whoami)' and 'postgres')."
  echo "  Create the role and database yourself, then re-run this script:"
  echo "    createuser -s $DB_USER && createdb -O $DB_USER $DB_NAME"
  exit 1
fi
echo "  using Postgres admin role '$ADMIN_USER'"

if ! psql -h localhost -U "$ADMIN_USER" -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" 2>/dev/null | grep -q 1; then
  psql -h localhost -U "$ADMIN_USER" -d postgres -c "CREATE ROLE $DB_USER LOGIN SUPERUSER PASSWORD '$DB_PASS';"
  echo "  created role '$DB_USER'"
else
  echo "  role '$DB_USER' already exists, skipping"
fi

if ! psql -h localhost -U "$ADMIN_USER" -d postgres -lqt 2>/dev/null | cut -d '|' -f 1 | grep -qw "$DB_NAME"; then
  createdb -h localhost -U "$ADMIN_USER" -O "$DB_USER" "$DB_NAME"
  echo "  created database '$DB_NAME'"
else
  echo "  database '$DB_NAME' already exists — skipping restore to avoid clobbering it."
  echo "  If you want a clean restore: dropdb -U $ADMIN_USER $DB_NAME, then re-run this script."
  SKIP_RESTORE=1
fi

# --- 4. Restore the dump -------------------------------------------------
if [ -z "${SKIP_RESTORE:-}" ]; then
  echo "==> Restoring tagged data from saad_gpt_handoff.dump..."
  pg_restore -h localhost -U "$DB_USER" -d "$DB_NAME" --no-owner "$DUMP_FILE"
  echo "  restore complete"
fi

# --- 5. .env -------------------------------------------------------------
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "==> Writing .env..."
  cat > "$ENV_FILE" <<EOF
SAAD_GPT_DATABASE_URL=postgresql+psycopg://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME
EOF
else
  echo "==> .env already exists, leaving it alone"
fi

# --- 6. Claude Code skill --------------------------------------------------
SKILL_SRC="$PROJECT_DIR/.claude/skills/saad-sales-gpt/SKILL.md"
SKILL_DEST_DIR="$HOME/.claude/skills/saad-sales-gpt"
if [ -f "$SKILL_SRC" ]; then
  echo "==> Installing the Claude Code skill (global, for any session)..."
  mkdir -p "$SKILL_DEST_DIR"
  # Bake this machine's actual project path in as the default, so no shell
  # profile / env var setup is needed.
  sed "s|\${SAAD_GPT_PROJECT_DIR:-/Users/amlannttripathy/Downloads/Saad}|$PROJECT_DIR|g" \
    "$SKILL_SRC" > "$SKILL_DEST_DIR/SKILL.md"
  echo "  installed to $SKILL_DEST_DIR/SKILL.md"
else
  echo "  WARNING: skill file not found at $SKILL_SRC, skipping"
fi

# --- 7. Claude Desktop MCP config -----------------------------------------
DESKTOP_CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
UV_PATH="$(command -v uv)"
if [ -f "$DESKTOP_CONFIG" ]; then
  echo "==> Registering the MCP server in Claude Desktop's config..."
  python3 - "$DESKTOP_CONFIG" "$UV_PATH" "$PROJECT_DIR" <<'PYEOF'
import json
import sys

config_path, uv_path, project_dir = sys.argv[1:4]
with open(config_path) as f:
    config = json.load(f)

config.setdefault("mcpServers", {})["saad-sales-gpt"] = {
    "command": uv_path,
    "args": ["run", "--directory", project_dir, "saad-gpt", "mcp-serve"],
}

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"  added 'saad-sales-gpt' to {config_path}")
PYEOF
else
  echo "  Claude Desktop config not found at $DESKTOP_CONFIG"
  echo "  (is Claude Desktop installed? Have you run it at least once?)"
  echo "  You can add this manually once it exists:"
  echo "  \"saad-sales-gpt\": {\"command\": \"$UV_PATH\", \"args\": [\"run\", \"--directory\", \"$PROJECT_DIR\", \"saad-gpt\", \"mcp-serve\"]}"
fi

echo ""
echo "==> Done! Now fully quit and reopen Claude Desktop (Cmd+Q, not just closing"
echo "    the window) so it picks up the new MCP server."
echo "    Then just ask a sales/cold-calling question in a normal chat message."
echo "    In Claude Code (any session, any project), the skill is available too —"
echo "    ask a sales question there, or say 'use the saad-sales-gpt skill'."
