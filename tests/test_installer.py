"""Installer orchestration with isolated shell mocks; no real apt/systemd changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def shell(self, code, **kwargs):
        return subprocess.run(["bash", "-c", 'source "$1"; shift\n' + code,
                               "bash", str(ROOT / "install.sh")],
                              capture_output=True, text=True, timeout=10, **kwargs)

    def test_shell_syntax(self):
        result = subprocess.run(["bash", "-n", str(ROOT / "install.sh")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_apt_refresh_and_only_missing_packages(self):
        result = self.shell("""
sudo() { "$@"; }
apt-get() { printf 'APT %s\\n' "$*"; }
env() { shift 2; "$@"; }
dpkg-query() {
    [[ ${*: -1} == git ]] && printf 'install ok installed' || return 1
}
apt_prepare git openssh-server
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "APT update",
            "APT install -y --no-install-recommends openssh-server"])

    def test_existing_checkout_wrong_origin_never_pulls(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "checkout"
            (checkout / ".git").mkdir(parents=True)
            result = self.shell("""
git() {
    if [[ $* == *'remote get-url origin' ]]; then
        echo https://example.test/other.git
    else
        echo UNEXPECTED
        return 99
    fi
}
bootstrap_checkout "$CHECKOUT"
""", env=dict(os.environ, CHECKOUT=str(checkout)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("different origin", result.stderr)
            self.assertNotIn("UNEXPECTED", result.stdout)

    def test_bootstrap_clone_from_fixed_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "fresh"
            result = self.shell("""
git() { printf '%s\\n' "$*"; }
bootstrap_checkout "$CHECKOUT"
""", env=dict(os.environ, CHECKOUT=str(checkout)))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(),
                             f"clone --branch main --single-branch https://github.com/sina1991/30nA-CLI.git {checkout}")

    def test_dependency_free_install_never_prepares_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.shell("""
apt_prepare() { fail "unexpected apt"; }
prepare_ssh() { fail "unexpected ssh"; }
prepare_keys() { fail "unexpected key prep"; }
main
""", env=dict(os.environ, INSTALL_DEPS="0", PREFIX=tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((Path(tmp) / "bin/30na").is_symlink())

    def test_active_ssh_socket_preserved(self):
        result = self.shell("""
check_sshd() { echo CHECK; }
systemctl() {
    printf 'SYSTEMCTL %s\\n' "$*"
    case "$*" in
        'is-active --quiet ssh.socket'|'is-enabled --quiet ssh.socket') return 0 ;;
        *) return 1 ;;
    esac
}
prepare_ssh
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CHECK", result.stdout)
        self.assertNotIn("enable --now", result.stdout)
        self.assertNotIn("restart", result.stdout.replace("not restarted", ""))

    def test_inactive_ssh_service_enabled_and_started(self):
        result = self.shell("""
check_sshd() { echo CHECK; }
started=0
systemctl() {
    printf 'SYSTEMCTL %s\\n' "$*"
    case "$*" in
        'is-active --quiet ssh.socket') return 1 ;;
        'is-active --quiet ssh.service') [[ $started == 1 ]] ;;
        'enable --now ssh.service') started=1 ;;
        *) return 1 ;;
    esac
}
prepare_ssh
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEMCTL enable --now ssh.service", result.stdout)

    def test_dirty_checkout_not_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "checkout"
            (checkout / ".git").mkdir(parents=True)
            result = self.shell("""
git() {
    case "$*" in
        *'remote get-url origin') echo https://github.com/sina1991/30nA-CLI.git ;;
        *'branch --show-current') echo main ;;
        *'status --porcelain') echo ' M install.sh' ;;
        *) echo UNEXPECTED; return 99 ;;
    esac
}
bootstrap_checkout "$CHECKOUT"
""", env=dict(os.environ, CHECKOUT=str(checkout)))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("local changes", result.stderr)
            self.assertNotIn("UNEXPECTED", result.stdout)
