#!/bin/sh
# Turns on the repo's git hooks (.githooks/) for this clone. Run once after cloning:
#   sh scripts/install-hooks.sh
set -e
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

# Cloud coding sessions commit as "Claude <noreply@anthropic.com>" by default.
# In this repo, commit as the owner instead.
if [ "$(git config user.email)" = "noreply@anthropic.com" ]; then
  git config user.name "Emre Hekimoğlu"
  git config user.email "emrehekimoglu2005@gmail.com"
fi
echo "Git hooks installed (.githooks)."
