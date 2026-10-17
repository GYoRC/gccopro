#!/bin/bash
# Run on the PC (Git Bash): copy the code to the NAS, then install and restart there.
#   deploy/deploy.sh            REMOTE=nas and REMOTE_DIR=gccpro by default
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE="${REMOTE:-nas}"
REMOTE_DIR="${REMOTE_DIR:-gccpro}"

# Replace app/ entirely so deleted files do not linger; data/ is never touched.
tar czf - --exclude=__pycache__ gccpro deploy requirements.txt \
  | ssh "$REMOTE" "set -e; mkdir -p '$REMOTE_DIR/app'; cd '$REMOTE_DIR/app'; rm -rf gccpro deploy; tar xzf -"
ssh "$REMOTE" "bash '$REMOTE_DIR/app/deploy/install.sh'"
