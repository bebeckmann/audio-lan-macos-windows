#!/bin/zsh
cd -- "${0:A:h}" || exit 1
python3 -m venv .venv || exit 1
.venv/bin/python -m pip install -r requirements.txt || exit 1
echo "Installation abgeschlossen. Sender_macOS.command starten."
read "?Enter zum Beenden."
