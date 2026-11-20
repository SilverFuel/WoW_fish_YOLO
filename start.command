#!/bin/bash
# macOS: double-click this file to start the bot. The first run sets things up (a few minutes).
cd "$(dirname "$0")" || exit 1

stop() {
    echo
    echo "$1"
    read -r -p "Press Return to close."
    exit 1
}

command -v python3 >/dev/null 2>&1 ||
    stop "Python 3 was not found. Install Python 3.11 or newer from https://www.python.org/downloads/ and run this again."
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
    stop "Python 3.11 or newer is needed; this is $(python3 --version 2>&1). Install a newer one from https://www.python.org/downloads/"

# Set up again whenever the requirements change, not only the first time.
if ! cmp -s requirements.txt .venv/requirements.installed; then
    echo "Setting up. The first time takes a few minutes."
    python3 -m venv .venv &&
        .venv/bin/python -m pip install --upgrade pip &&
        .venv/bin/python -m pip install -r requirements.txt &&
        cp requirements.txt .venv/requirements.installed ||
        stop "Setup failed. See the messages above."
fi

exec .venv/bin/python bot.py "$@"
