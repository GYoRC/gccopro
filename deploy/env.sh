#!/bin/bash
# Shared paths for the NAS scripts; sourced, not run. Layout under the base folder:
#   app/   code (replaced on each deploy)    venv/  Python 3.12 virtualenv
#   data/  config.toml, gccpro.db, backups/, logs/  (never touched by deploys)

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$(dirname "$APP")"
VENV="$BASE/venv"
DATA="$BASE/data"
LOGS="$DATA/logs"
PIDFILE="$DATA/server.pid"
PYTHON312=/var/packages/python312/target/bin/python3.12
PORT=8090

export GCCPRO_CONFIG="$DATA/config.toml"
export FLASK_APP=gccpro
export PYTHONIOENCODING=utf-8
