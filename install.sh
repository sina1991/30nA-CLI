#!/usr/bin/env bash
set -euo pipefail
command -v ssh >/dev/null || { echo "OpenSSH client required" >&2; exit 1; }
python3 -c 'import sqlite3, sys; sys.exit(sys.version_info < (3,10))' || { echo "Python 3.10+ with sqlite3 required" >&2; exit 1; }
src=$(cd -- "$(dirname -- "$0")" && pwd)
prefix=${PREFIX:-/usr/local}
mkdir -p -- "$prefix/bin" "$prefix/lib/30na"
dest=$(cd -- "$prefix/lib/30na" && pwd)
release=$(mktemp -d "$dest/release.XXXXXXXX")
cp -R -- "$src/thirtyna" "$src/30na" "$release/"
chmod -R a+rX "$release"
chmod 755 "$release"
ln -s -- "$release/30na" "$release/launcher"
mv -Tf -- "$release/launcher" "$prefix/bin/30na"
