#!/bin/bash
set -euo pipefail

# Production deploy script for Azad E-School
REMOTE_USER=azad
REMOTE_HOST=azad.school
REMOTE_DIR=/opt/azad-e-school

ssh "${REMOTE_USER}@${REMOTE_HOST}" "
  set -e
  cd ${REMOTE_DIR}
  git pull origin main
  source .venv/bin/activate
  pip install -r requirements.txt
  python scripts/build_css.py
  pybabel compile -d app/translations
  flask db upgrade
  sudo systemctl restart azad-e-school
  echo 'Deploy complete'
"