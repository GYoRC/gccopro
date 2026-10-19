#!/bin/bash
# Print a one-time login link for a resident, without sending any email. From the PC:
#   ssh nas bash gccpro/app/deploy/login-link.sh someone@example.org
. "$(dirname "$0")/env.sh"
cd "$APP"
"$VENV/bin/flask" login-link "$@"
