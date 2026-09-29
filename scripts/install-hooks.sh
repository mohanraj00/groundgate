#!/usr/bin/env bash
# Install the denylist check as pre-commit and pre-push hooks.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
hooks="$(git -C "$root" rev-parse --git-path hooks)"
mkdir -p "$hooks"
printf '#!/usr/bin/env bash\nexec "%s/scripts/check-denylist.sh"\n' "$root" > "$hooks/pre-commit"
cat > "$hooks/pre-push" <<HOOK
#!/usr/bin/env bash
set -euo pipefail
while read -r local_ref local_sha remote_ref remote_sha; do
  [[ "\$local_sha" =~ ^0+\$ ]] && continue
  if [[ "\$remote_sha" =~ ^0+\$ ]]; then range="\$local_sha"; else range="\$remote_sha..\$local_sha"; fi
  "$root/scripts/check-denylist.sh" --range "\$range"
done
HOOK
chmod +x "$hooks/pre-commit" "$hooks/pre-push"
echo "hooks installed"
