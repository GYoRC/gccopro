#!/bin/bash
# Interactive: store the SMTP password in config.toml, switch MAIL_BACKEND to "smtp"
# and restart the server. The password is typed without echo and never appears in
# a command line or shell history. From the PC:
#   ssh -t nas bash gccpro/app/deploy/set-smtp-password.sh
set -euo pipefail
. "$(dirname "$0")/env.sh"

"$VENV/bin/python" - "$GCCPRO_CONFIG" <<'EOF'
"""Replace SMTP_PASSWORD and MAIL_BACKEND lines in the TOML config, in place."""
import getpass
import json
import re
import sys

path = sys.argv[1]
password = getpass.getpass("Mot de passe SMTP (rien ne s'affiche) : ").strip()
if not password:
    sys.exit("Aucun mot de passe saisi, rien n'a été modifié.")
# Gmail shows app passwords as "abcd efgh ijkl mnop"; the spaces are not part of it.
if re.fullmatch(r"[a-z]{4}( [a-z]{4}){3}", password):
    password = password.replace(" ", "")

with open(path, encoding="utf-8") as fh:
    text = fh.read()
# json.dumps yields a valid TOML basic string (quotes and backslashes escaped).
for key, value in (("SMTP_PASSWORD", json.dumps(password)), ("MAIL_BACKEND", '"smtp"')):
    text, count = re.subn(rf"(?m)^{key} = .*$", lambda _m: f"{key} = {value}", text)
    if count == 0:
        text += f"\n{key} = {value}\n"
with open(path, "w", encoding="utf-8") as fh:  # keeps the file's chmod 600
    fh.write(text)
print("Configuration mise à jour.")
EOF

"$APP/deploy/stop.sh"
"$APP/deploy/start.sh"
echo "Serveur redémarré."
