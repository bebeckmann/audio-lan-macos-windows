#!/bin/zsh
cd -- "${0:A:h}" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  echo "Bitte zuerst Installieren_macOS.command starten."
  read "?Enter zum Beenden."
  exit 1
fi
.venv/bin/python -u audio_sender.py "$@"
read "?Enter zum Beenden."
