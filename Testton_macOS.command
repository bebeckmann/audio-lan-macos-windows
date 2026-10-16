#!/bin/zsh
cd -- "${0:A:h}" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  echo "Bitte zuerst Installieren_macOS.command starten."
  read "?Enter zum Beenden."
  exit 1
fi
echo "30 Sekunden Testton, 1000 Hz, -24 dBFS. Vorher Mikrofon-Sender beenden."
.venv/bin/python -u audio_sender.py --test-tone 1000 --duration 30
read "?Enter zum Beenden."
