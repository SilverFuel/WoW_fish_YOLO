#!/bin/bash
# Double-click this file to start WoW Fish YOLO.
# The first time it sets itself up, which takes a few minutes.
cd "$(dirname "$0")" || exit 1

stop() {
    echo
    echo "$1"
    echo
    read -r -p "Press Return to close this window."
    exit 1
}

# Use the first Python that is new enough.
python=""
for candidate in python3 python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        python="$candidate"
        break
    fi
done
[ -n "$python" ] || stop "WoW Fish YOLO needs Python 3.11 or newer, which is free.
  1. Get it from https://www.python.org/downloads/
  2. Double-click this file again."

# Set up again whenever the list of things it needs changes, not only the first time.
if ! cmp -s requirements.txt .venv/requirements.installed; then
    echo "Setting up WoW Fish YOLO. This happens once and takes a few minutes..."
    "$python" -m venv .venv &&
        .venv/bin/python -m pip install --quiet --disable-pip-version-check --upgrade pip &&
        .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt &&
        cp requirements.txt .venv/requirements.installed ||
        stop "Setting up did not finish. Check your internet connection, then double-click this file again.
If it keeps happening, see docs/help.md."
    echo "Done."
    echo
fi

exec .venv/bin/python bot.py "$@"
