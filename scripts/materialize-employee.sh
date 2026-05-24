#!/usr/bin/env bash
# Materialize a checked-in employee spec into a hermes-agent profile.
#
#   scripts/materialize-employee.sh <role>
#   DRY_RUN=1 scripts/materialize-employee.sh <role>   # show changes, do nothing
#   HERMES_BASE=/tmp/test-hermes scripts/materialize-employee.sh <role>  # test
#
# Copies employees/<role>/{SOUL.md,config.yaml} into the profile dir
# (~/.hermes/profiles/<role>/), backing up anything it overwrites to *.bak and
# showing a diff, and seeds .env from env.example only if absent. It NEVER
# touches sessions/, memories/, or runtime state. Idempotent; safe to re-run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_BASE="${HERMES_BASE:-$HOME/.hermes}"
DRY_RUN="${DRY_RUN:-}"

die() { echo "error: $*" >&2; exit 1; }
run() { if [ -n "$DRY_RUN" ]; then echo "  [dry-run] $*"; else "$@"; fi; }

role="${1:-}"
[ -n "$role" ] || die "usage: $0 <role>  (e.g. autonomous-coder)"

SRC="$REPO_ROOT/employees/$role"
[ -d "$SRC" ] || die "no employee spec at employees/$role"
[ -f "$SRC/SOUL.md" ] || die "employees/$role/SOUL.md missing"
[ -f "$SRC/config.yaml" ] || die "employees/$role/config.yaml missing"

DEST="$HERMES_BASE/profiles/$role"
echo ">> materializing '$role'"
echo "   from: $SRC"
echo "   into: $DEST${DRY_RUN:+   (DRY RUN)}"

# 1. Ensure the profile directory exists. Prefer the hermes CLI when it's the
#    real default base, so hermes seeds bundled skills; otherwise just mkdir.
if [ ! -d "$DEST" ]; then
  if command -v hermes >/dev/null 2>&1 && [ "$HERMES_BASE" = "$HOME/.hermes" ]; then
    run hermes profile create "$role" --description "Dolios fleet employee: $role" \
      || run mkdir -p "$DEST"
  else
    [ "$HERMES_BASE" = "$HOME/.hermes" ] && echo "   (hermes CLI not found — creating dir directly)"
    run mkdir -p "$DEST"
  fi
fi

# 2. Copy SOUL.md + config.yaml, backing up + diffing any existing copy.
copy_file() {
  local name="$1" src="$SRC/$1" dst="$DEST/$1"
  if [ -f "$dst" ] && ! diff -q "$src" "$dst" >/dev/null 2>&1; then
    echo "   ~ $name differs from installed copy:"
    diff -u "$dst" "$src" | sed 's/^/       /' || true
    run cp "$dst" "$dst.bak"
    echo "     (backed up existing → $name.bak)"
  elif [ ! -f "$dst" ]; then
    echo "   + $name (new)"
  else
    echo "   = $name (unchanged)"
  fi
  run cp "$src" "$dst"
}
copy_file SOUL.md
copy_file config.yaml

# 3. Seed .env from env.example only if it does not already exist.
if [ -f "$SRC/env.example" ]; then
  if [ -f "$DEST/.env" ]; then
    echo "   = .env (kept existing — secrets untouched)"
  else
    echo "   + .env (seeded from env.example — fill in secrets)"
    run cp "$SRC/env.example" "$DEST/.env"
    run chmod 600 "$DEST/.env"
  fi
fi

echo ">> done${DRY_RUN:+ (dry run — nothing written)}"
[ -z "$DRY_RUN" ] && echo "   review/edit secrets: $DEST/.env"
exit 0
