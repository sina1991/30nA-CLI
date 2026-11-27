#!/usr/bin/env bash
set -euo pipefail

REPOSITORY=https://github.com/sina1991/30nA-CLI.git

fail() { echo "30na installer: $*" >&2; exit 1; }

platform_setup() {
    python_bin=$(command -v python3 || true)
    ubuntu=false
    if [[ -r /etc/os-release ]]; then
        . /etc/os-release
        if [[ ${ID:-} == ubuntu ]]; then
            ubuntu=true
            python_bin=/usr/bin/python3
        fi
    fi
}

ready() {
    [[ -x "$python_bin" ]] &&
        "$python_bin" -c 'import sys, sqlite3, curses, tkinter, tkinter.ttk; sys.exit(sys.version_info < (3, 10))' &&
        command -v nano >/dev/null &&
        command -v git >/dev/null &&
        command -v ssh >/dev/null &&
        command -v ssh-keygen >/dev/null &&
        command -v ssh-copy-id >/dev/null &&
        command -v ss >/dev/null &&
        { ! "$ubuntu" || command -v xauth >/dev/null; }
}

apt_prepare() {
    local -a elevate=() missing=()
    local package
    if (( EUID != 0 )); then
        command -v sudo >/dev/null || fail "Run as root or install sudo."
        elevate=(sudo)
    fi
    # Refresh package indexes; install missing prerequisites only, not a
    # distribution upgrade or an indiscriminate upgrade of running services.
    "${elevate[@]}" apt-get update
    for package in "$@"; do
        if [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true) != "install ok installed" ]]; then
            missing+=("$package")
        fi
    done
    if (( ${#missing[@]} )); then
        "${elevate[@]}" env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l \
            apt-get install -y --no-install-recommends "${missing[@]}"
    fi
}

check_sshd() {
    # Fresh installs may not have created the volatile privsep directory yet.
    [[ -d /run/sshd ]] || install -d -m 0755 /run/sshd
    /usr/sbin/sshd -t
}

prepare_ssh() {
    command -v systemctl >/dev/null || fail "systemd is required for the SSH server."
    check_sshd
    # Preserve Ubuntu's socket activation and existing active SSH sessions.
    if systemctl is-active --quiet ssh.socket; then
        systemctl is-enabled --quiet ssh.socket || systemctl enable ssh.socket
    elif systemctl is-active --quiet ssh.service; then
        systemctl is-enabled --quiet ssh.service || systemctl enable ssh.service
    else
        systemctl enable --now ssh.service
    fi
    if ! systemctl is-active --quiet ssh.socket && ! systemctl is-active --quiet ssh.service; then
        fail "SSH server activation was not confirmed."
    fi
    echo "SSH server ready (existing active service not restarted)."
}

prepare_keys() {
    # Only the root operator's existing files, never downloaded keys.
    (cd "$1" && PYTHONDONTWRITEBYTECODE=1 "$python_bin" - <<'PY'
import os
from pathlib import Path
import stat
from thirtyna.ssh_identity import import_identity

home = Path("/root")
source = home / "30na_windows"
public = source.with_suffix(".pub")
present = [p.exists() or p.is_symlink() for p in (source, public)]
if not any(present):
    print("NOTICE: no legacy key pair; Host enrollment can prepare a management identity.")
elif not all(present):
    raise SystemExit("Incomplete /root/30na_windows key pair; supply both files.")
else:
    try:
        for path, mode in ((source, 0o600), (public, 0o644)):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
                    raise RuntimeError("Key must be a root-owned regular file without additional hard links")
                os.fchmod(fd, mode)
            finally:
                os.close(fd)
        import_identity(home)
        print("Management key pair validated and copied locally.")
    except (OSError, RuntimeError) as exc:
        raise SystemExit("Management key preparation failed: " + str(exc))
PY
    )
}

bootstrap_checkout() {
    local checkout="$1"
    if [[ -e "$checkout" || -L "$checkout" ]]; then
        [[ ! -L "$checkout" && -d "$checkout/.git" && ! -L "$checkout/.git" ]] || fail "Existing checkout path is not an ordinary Git checkout."
        [[ $(git -C "$checkout" remote get-url origin) == "$REPOSITORY" ]] || fail "Existing checkout has a different origin."
        [[ $(git -C "$checkout" branch --show-current) == main ]] || fail "Existing checkout is not on main."
        [[ -z $(git -C "$checkout" status --porcelain) ]] || fail "Existing checkout has local changes."
        git -C "$checkout" pull --ff-only origin main
        [[ $(git -C "$checkout" rev-parse HEAD) == "$(git -C "$checkout" rev-parse origin/main)" ]] || fail "Existing checkout is not exactly origin/main."
    else
        git clone --branch main --single-branch "$REPOSITORY" "$checkout"
    fi
}

main() {
    platform_setup
    local src prefix dest release revision
    local -a packages=(git ca-certificates python3 python3-tk libpython3-stdlib openssh-client iproute2 nano ncurses-base xauth)
    src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    if [[ ${1:-} == --bootstrap ]]; then
        [[ $# == 1 && $EUID == 0 ]] || fail "--bootstrap requires root and no additional arguments."
        [[ ${INSTALL_DEPS:-1} == 1 ]] || fail "--bootstrap requires dependency preparation."
        "$ubuntu" || fail "--bootstrap currently supports Ubuntu."
        if ! command -v git >/dev/null || [[ $(dpkg-query -W -f='${Status}' ca-certificates 2>/dev/null || true) != "install ok installed" ]]; then
            apt_prepare git ca-certificates
        fi
        bootstrap_checkout /root/30nA-CLI
        exec bash /root/30nA-CLI/install.sh
    fi
    [[ $# == 0 ]] || fail "Use ./install.sh or --bootstrap."
    [[ -f "$src/30na" && -d "$src/thirtyna" ]] || fail "Standalone installer requires --bootstrap."
    [[ ${INSTALL_DEPS:-1} == 0 || ${INSTALL_DEPS:-1} == 1 ]] || fail "INSTALL_DEPS must be 0 or 1."
    if [[ ${INSTALL_DEPS:-1} == 1 ]] && "$ubuntu"; then
        if (( EUID == 0 )); then
            packages+=(openssh-server)
        fi
        apt_prepare "${packages[@]}"
    fi
    ready || fail "Requires Python 3.10+ with sqlite3, curses and Tk/ttk, Git, nano, OpenSSH client/key tools, iproute2 and (Ubuntu) xauth."
    if [[ ${INSTALL_DEPS:-1} == 1 ]] && "$ubuntu" && (( EUID == 0 )); then
        prepare_ssh
        prepare_keys "$src"
    fi

    prefix=${PREFIX:-/usr/local}
    mkdir -p -- "$prefix/bin" "$prefix/lib/30na"
    dest=$(cd -- "$prefix/lib/30na" && pwd)
    release=$(mktemp -d "$dest/release.XXXXXXXX")
    cp -R -- "$src/thirtyna" "$src/30na" "$release/"
    # Record the exact Git revision when available.
    if [[ -e "$src/.git" ]] && command -v git >/dev/null; then
        revision=$(git -C "$src" rev-parse HEAD)
        if [[ "$revision" =~ ^[0-9a-f]{40}$ ]] && [[ -z $(git -C "$src" status --porcelain) ]]; then
            printf '%s\n' "$revision" > "$release/.revision"
        fi
    fi
    sed -i "1c\\#!$python_bin" "$release/30na"
    chmod -R a+rX "$release"
    chmod 755 "$release"
    PYTHONDONTWRITEBYTECODE=1 "$release/30na" -help >/dev/null
    ln -s -- "$release/30na" "$release/launcher"
    mv -Tf -- "$release/launcher" "$prefix/bin/30na"
    echo "Installed $prefix/bin/30na using $python_bin."
    [[ ! -f "$release/.revision" ]] || echo "Revision: $(cat "$release/.revision")"
    if [[ -z ${DISPLAY:-} ]]; then
        echo "Interactive SSH: -gui opens the fullscreen terminal interface."
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
