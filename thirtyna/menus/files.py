"""Filesystem actions for the Linux terminal file manager."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile


def named(folder, name):
    if not name or name in (".", "..") or "/" in name or "\0" in name:
        raise ValueError("Enter one file or directory name")
    return folder / name


def relocate(source, target):
    if os.path.lexists(target):
        raise FileExistsError(f"Destination exists: {target}")
    result = subprocess.run(["mv", "-nT", "--", source, target],
                            capture_output=True, text=True, errors="replace")
    if result.returncode:
        raise OSError(result.stderr.strip() or "Move failed")
    if os.path.lexists(source):
        raise FileExistsError(f"Destination already exists: {target}")


def transfer(source, target, move=False):
    if os.path.lexists(target):
        raise FileExistsError(f"Destination exists: {target}")
    mode = source.lstat().st_mode
    if stat.S_ISDIR(mode) and target.parent.resolve().is_relative_to(source.resolve()):
        raise ValueError("Choose a destination outside the source directory")
    if move:
        relocate(source, target)
        return
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".30na-copy-") as tmp:
        stage = Path(tmp) / "item"
        if stat.S_ISLNK(mode):
            stage.symlink_to(os.readlink(source))
        elif stat.S_ISDIR(mode):
            shutil.copytree(source, stage, symlinks=True)
        elif stat.S_ISREG(mode):
            shutil.copy2(source, stage)
        else:
            raise ValueError("Copy supports files, directories and symbolic links")
        relocate(stage, target)


def remove(path):
    if stat.S_ISDIR(path.lstat().st_mode):
        path.rmdir()
    else:
        path.unlink()
