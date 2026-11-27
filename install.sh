#!/usr/bin/env bash
set -euo pipefail

# Ubuntu packages install modules for the distribution's Python interpreter.
python_bin=$(command -v python3 || true)
ubuntu=false
if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    if [[ ${ID:-} == ubuntu ]]; then
        ubuntu=true
        python_bin=/usr/bin/python3
    fi
fi

ready() {
    [[ -x "$python_bin" ]] &&
        "$python_bin" -c 'import sys, sqlite3, curses, tkinter, tkinter.ttk; sys.exit(sys.version_info < (3, 10))' &&
        command -v nano >/dev/null &&
        command -v ssh >/dev/null &&
        command -v ss >/dev/null &&
        { ! "$ubuntu" || command -v xauth >/dev/null; }
}

if ! ready 2>/dev/null; then
    if ! "$ubuntu" || [[ ${INSTALL_DEPS:-1} == 0 ]]; then
        echo "Requires Python 3.10+ with sqlite3, curses and Tk/ttk, nano, OpenSSH client, iproute2 (ss) and (Ubuntu) xauth." >&2
        exit 1
    fi
    elevate=()
    if (( EUID != 0 )); then
        command -v sudo >/dev/null || { echo "Run installer as root or install sudo." >&2; exit 1; }
        elevate=(sudo)
    fi
    "${elevate[@]}" apt-get update
    "${elevate[@]}" apt-get install -y --no-install-recommends python3 python3-tk libpython3-stdlib openssh-client iproute2 nano ncurses-base xauth
    ready || { echo "System Python requires version 3.10+ and working sqlite3, curses and Tk." >&2; exit 1; }
fi
src=$(cd -- "$(dirname -- "$0")" && pwd)
prefix=${PREFIX:-/usr/local}
mkdir -p -- "$prefix/bin" "$prefix/lib/30na"
dest=$(cd -- "$prefix/lib/30na" && pwd)
release=$(mktemp -d "$dest/release.XXXXXXXX")
cp -R -- "$src/thirtyna" "$src/30na" "$release/"
# Record the exact Git revision when available (no dependency for archive installs).
if [[ -e "$src/.git" ]] && command -v git >/dev/null; then
    revision=$(git -C "$src" rev-parse HEAD)
    if [[ "$revision" =~ ^[0-9a-f]{40}$ ]] && [[ -z $(git -C "$src" status --porcelain) ]]; then
        printf "%s\n" "$revision" > "$release/.revision"
    fi
fi
sed -i "1c\\#!$python_bin" "$release/30na"
chmod -R a+rX "$release"
chmod 755 "$release"
ln -s -- "$release/30na" "$release/launcher"
mv -Tf -- "$release/launcher" "$prefix/bin/30na"
echo "Installed $prefix/bin/30na using $python_bin."
if [[ -z ${DISPLAY:-} ]]; then
    echo "Interactive SSH: -gui opens the fullscreen terminal interface."
fi
