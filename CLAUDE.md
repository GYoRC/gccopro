# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language
- All code, comments, docs, commit messages and this file: English only.
- The user may chat in French or English; reply in the user's language in chat.

## Stack
- Backend: Python + SQLite, runs on the NAS.
- Frontend: Node.js is a build tool on the dev machine only; the NAS serves the built static output.

## Hosting constraints (Synology DS216j)
- NAS address: 192.168.1.49 (DSM web UI on HTTPS port 5001).
- Shell access: `ssh nas` (key-based, user `claude`, alias in `~/.ssh/config`). Never store passwords in this repo. The `claude` account has no passwordless sudo; ask the user to run root commands.
- DSM 7.1.1-42962 Update 9 (upgraded from 7.0.1 on 2026-10-17).
- Python on NAS: Python 3.12.13 from the SynoCommunity `python312` package, at `/var/packages/python312/target/bin/python3.12` (not on PATH). Target Python 3.12 for the backend.
  - Its `sqlite3` module links SQLite 3.45.2 (`RETURNING`, `STRICT` tables and JSON functions are available).
  - pip works inside a venv: `/var/packages/python312/target/bin/python3.12 -m venv <dir>`. Create venvs under the home folder or `/volume1`, never `/tmp` (mounted `noexec`).
  - Do not use or modify the system Python 3.8.12 (`/usr/bin/python3`, no pip); DSM depends on it.
- The `sqlite3` CLI (`/usr/bin/sqlite3`) is the system one, SQLite 3.34.1.
- Other DSM packages (not on the `claude` user's PATH; call by full path):
  - Git 2.33.0: `/var/packages/Git/target/bin/git` (package stopped, binary works).
  - Node.js 12.22.12: `/var/packages/Node.js_v12/target/usr/local/bin/node` (end-of-life; do not build on it).
  - `py3k` package ships an obsolete Python 3.5.1; ignore it.
- Hardware: 32-bit ARMv7 (`armv7l`; Marvell Armada 385, dual-core 1.0 GHz), ~500 MB RAM; ~300 MB available right after boot, dropping to ~170 MB with swap in use under normal load.
  - Many Python wheels and npm packages with native code have no 32-bit ARM build and will try to compile or fail. Use pure-Python / pure-JS dependencies for anything that runs on the NAS.
  - Recent Node.js releases have reduced 32-bit ARM support; do not plan on running Node on the NAS.
- Root actions (Package Center installs, services, ports) are done by the user in the DSM web UI.
  - With so little free memory, keep the backend single-process and memory-light.
- Keep dependencies minimal and lightweight; avoid heavy frameworks and native builds.

## Coding standards
- Every module, function and non-trivial block must be commented (docstrings for Python, JSDoc for JS).
- Small, reviewable changes; explain the plan before large edits.
- Write tests alongside features.

