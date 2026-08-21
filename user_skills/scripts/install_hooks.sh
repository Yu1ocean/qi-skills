#!/bin/bash
# Install qi-skills Git hooks.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$repo_root" ]; then
  echo "❌ Not inside a Git repository."
  exit 1
fi

cd "$repo_root"

source_hook="user_skills/scripts/pre-push"
target_hook=".git/hooks/pre-push"

if [ ! -f "$source_hook" ]; then
  echo "❌ Hook template not found: $source_hook"
  exit 1
fi

mkdir -p .git/hooks
cp "$source_hook" "$target_hook"
chmod +x "$target_hook"

echo "✅ pre-push hook installed: $repo_root/$target_hook"
echo "   Guard 1: blocks any single file larger than 50MB."
echo "   Guard 2: circuit-breaks when one push adds more than 100MB in total."
echo "   Bypass:  ALLOW_BIG_PUSH=1 git push ..."
