#!/usr/bin/env bash
# Fail if any tracked or staged file contains a term from a private denylist.
# The denylist lives outside the repository so the protected terms are never published.
# Path: $GROUNDGATE_DENYLIST, default ../../.groundgate-denylist relative to the repo root.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
list="${GROUNDGATE_DENYLIST:-$root/../../.groundgate-denylist}"

if [[ ! -f "$list" ]]; then
  if [[ -n "${CI:-}" ]]; then exit 0; fi
  echo "denylist not found at $list (set GROUNDGATE_DENYLIST)" >&2
  exit 1
fi

patterns="$(grep -v -e '^#' -e '^[[:space:]]*$' "$list" || true)"
[[ -z "$patterns" ]] && exit 0

hits="$(git -C "$root" grep --cached -n -I -i -F -f <(printf '%s\n' "$patterns") -- ':!scripts/check-denylist.sh' || true)"
msgs=""
if [[ "${1:-}" == "--range" && -n "${2:-}" ]]; then
  msgs="$(git -C "$root" log --format=%B "$2" | grep -n -i -F -f <(printf '%s\n' "$patterns") || true)"
fi

if [[ -n "$hits$msgs" ]]; then
  echo "denylist: private terms found; nothing was pushed or committed." >&2
  [[ -n "$hits" ]] && printf '%s\n' "$hits" | cut -d: -f1,2 >&2
  [[ -n "$msgs" ]] && echo "(also in commit messages)" >&2
  exit 1
fi
