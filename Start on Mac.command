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

# The newest Python that the parts it needs are built for. Intel Macs stop one version earlier.
newest=14
[ "$(uname -sm)" = "Darwin x86_64" ] && newest=13

# Prefer a Python that is known to work. Failing that, try a newer one rather than give up.
python=""
known=""
for limit in "$newest" 99; do
    for candidate in python3.13 python3.12 python3.11 python3.14 python3; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c "import sys; sys.exit(not (3, 11) <= sys.version_info[:2] <= (3, $limit))" 2>/dev/null; then
            python="$candidate"
            [ "$limit" = 99 ] || known=yes
            break 2
        fi
    done
done
[ -n "$python" ] || stop "WoW Fish YOLO needs Python 3.13, which is free.
  1. Get Python 3.13 from https://www.python.org/downloads/
  2. Double-click this file again."

# Set up again whenever the list of things it needs changes, not only the first time.
if ! cmp -s requirements.txt .venv/requirements.installed; then
    echo "Setting up WoW Fish YOLO. This happens once and takes a few minutes..."
    "$python" -m venv --clear .venv &&
        .venv/bin/python -m pip install --quiet --disable-pip-version-check --upgrade pip &&
        .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt &&
        cp requirements.txt .venv/requirements.installed || {
        hint=""
        [ -n "$known" ] || hint="
It used $("$python" -c 'import sys; print("Python %d.%d" % sys.version_info[:2])'), which may be too new. Python 3.13 is known to work:
install it as well, then double-click this file again."
        stop "Setting up did not finish. Check your internet connection, then double-click this file again.$hint
More help: docs/help.md"
    }
    echo "Done."
    echo
fi

exec .venv/bin/python bot.py "$@"
