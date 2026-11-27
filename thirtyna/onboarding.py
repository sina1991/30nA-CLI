"""Explicit SSH enrollment: deploy the controller revision, never stop services."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

REVISION = re.compile(r"[0-9a-f]{40}\Z")

# Fixed remote program. Values substituted below are validated hex strings.
REMOTE = r"""
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import tempfile

revision = '__REVISION__'
controller = '__CONTROLLER__'

def command(args, timeout=10, env=None):
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, timeout=timeout, env=env)

def require(args, stage, timeout=10, env=None):
    result = command(args, timeout, env)
    if result.returncode:
        raise RuntimeError(stage + ' failed (exit ' + str(result.returncode) + ')')
    return result.stdout.strip()

def show(title, args):
    print('=== ' + title + ' ===', flush=True)
    try:
        result = command(args)
        if result.returncode:
            print('UNKNOWN (exit ' + str(result.returncode) + ')', flush=True)
        else:
            print(result.stdout[:16000], end='\n', flush=True)
    except (OSError, subprocess.TimeoutExpired):
        print('UNKNOWN', flush=True)

def main():
    machine = Path('/etc/machine-id').read_bytes().strip()
    if not machine:
        raise RuntimeError('Machine identity unavailable')
    if hashlib.sha256(machine).hexdigest() == controller:
        raise RuntimeError('Endpoint is the local machine, reserved ID 1')
    print('AUTHENTICATED SSH HOST', platform.node(), flush=True)
    print('OS', platform.platform(), flush=True)
    print('IP', require(['hostname', '-I'], 'Interface discovery'), flush=True)
    prefix = Path('/usr/local') if os.getuid() == 0 else Path.home() / '.local'
    launcher = prefix / 'bin/30na'
    marker = launcher.resolve().parent / '.revision'
    previous = marker.read_text().strip() if marker.is_file() else 'unknown'
    print('CURRENT_REVISION', previous if len(previous) == 40 and all(c in '0123456789abcdef' for c in previous) else 'unknown', flush=True)
    print('REQUESTED_REVISION', revision, flush=True)
    # Report newer main, but deploy only the exact controller revision.
    url = 'https://github.com/sina1991/30nA-CLI.git'
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL='/dev/null')
    latest = require(['git', 'ls-remote', url, 'refs/heads/main'], 'Main revision lookup', 15, env).split()
    if len(latest) != 2 or latest[1] != 'refs/heads/main':
        raise RuntimeError('Cannot determine main revision')
    print('MAIN_REVISION', latest[0], flush=True)
    if latest[0] != revision:
        print('NOTICE controller revision differs from main; using pinned controller revision', flush=True)
    if previous != revision or not launcher.is_file():
        with tempfile.TemporaryDirectory(prefix='30na-enroll-') as tmp:
            require(['git', 'init', '-q', tmp], 'Git init', env=env)
            require(['git', '-C', tmp, 'fetch', '--depth=1', url, revision], 'Pinned fetch', 35, env)
            require(['git', '-C', tmp, 'checkout', '--detach', 'FETCH_HEAD'], 'Checkout', env=env)
            actual = require(['git', '-C', tmp, 'rev-parse', 'HEAD'], 'Revision verification', env=env)
            if actual != revision:
                raise RuntimeError('Fetched revision mismatch')
            require(['bash', str(Path(tmp) / 'install.sh')], 'Install (dependencies must already exist)',
                    30, dict(env, PREFIX=str(prefix), INSTALL_DEPS='0'))
    marker = launcher.resolve().parent / '.revision'
    if not marker.is_file() or marker.read_text().strip() != revision:
        raise RuntimeError('Installed revision not verified')
    require([str(launcher), '-help'], 'CLI verification')
    print('INSTALLED', str(launcher), revision, flush=True)
    print('NOTICE existing runtime workers and systemd services were not restarted', flush=True)
    if previous != revision:
        print('NOTICE old workers may require a planned restart before new runtime commands', flush=True)
    show('TCP/UDP PORTS AND OWNERS', ['ss', '-H', '-lntup'])
    show('ACTIVE SYSTEMD SERVICES', ['systemctl', '--no-pager', '--no-legend', '--plain', 'list-units', '--type=service', '--state=active'])
    show('30nA WORKERS', [str(launcher), '-service', '-workers'])
    show('SYSTEM DETAILS', [str(launcher), '-sys', '-hostname', '-os', '-kernel', '-uptime', '-cpu', '-ram', '-disk'])
    # Never print complete command lines, key paths or arbitrary SSH options.
    print('=== OBSERVED SSH FORWARDS ===', flush=True)
    import re
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            args = (path / 'cmdline').read_bytes().split(b'\0')
            if not args or Path(os.fsdecode(args[0])).name != 'ssh':
                continue
            for i, arg in enumerate(args):
                for flag, mode in ((b'-L', 'FORWARD'), (b'-R', 'REVERSE')):
                    if not arg.startswith(flag):
                        continue
                    value = arg[2:] if len(arg) > 2 else args[i+1] if i+1 < len(args) else b''
                    # Only ordinary TCP forwarding specs, not arbitrary option strings.
                    if re.fullmatch(rb'[A-Za-z0-9_.:%*\[\]-]{3,255}', value) and value.count(b':') >= 2:
                        print(mode, 'pid=' + path.name, os.fsdecode(value), flush=True)
        except OSError:
            continue
    print('ENROLLMENT_OK', flush=True)

try:
    main()
except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
    print('ENROLLMENT_FAILED', str(exc), flush=True)
    raise SystemExit(1)
"""


def controller_revision():
    root = Path(__file__).resolve().parents[1]
    marker = root / ".revision"
    if marker.is_file():
        value = marker.read_text().strip()
    else:
        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, timeout=5)
        value = result.stdout.strip() if result.returncode == 0 else ""
        if value:
            clean = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                                   capture_output=True, text=True, timeout=5)
            if clean.returncode or clean.stdout.strip():
                raise RuntimeError("Enroll from a clean installed or Git release")
    if not REVISION.fullmatch(value):
        raise RuntimeError("Controller revision unavailable; reinstall from Git")
    return value


def enroll(address, interactive=False):
    """SSH config provides credentials; never install using an unverified host key."""
    if interactive and not sys.stdin.isatty():
        raise RuntimeError("Password authentication requires an interactive terminal")
    revision = controller_revision()
    machine = Path("/etc/machine-id").read_bytes().strip()
    if not machine:
        raise RuntimeError("Local machine identity unavailable")
    script = REMOTE.replace("__REVISION__", revision).replace(
        "__CONTROLLER__", hashlib.sha256(machine).hexdigest())
    authentication = "publickey,password,keyboard-interactive" if interactive else "publickey"
    argv = ["ssh", "-T", "-o", "BatchMode=" + ("no" if interactive else "yes"),
            "-o", "PreferredAuthentications=" + authentication,
            "-o", "StrictHostKeyChecking=" + ("ask" if interactive else "yes"),
            "-o", "ForwardAgent=no", "-o", "NumberOfPasswordPrompts=3",
            "-o", "ConnectTimeout=8", "-o", "ClearAllForwardings=yes",
            "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-o", "PermitLocalCommand=no", "--", address, "python3", "-"]
    try:
        if interactive:
            print("Verify any new host fingerprint against a trusted source before accepting.", file=sys.stderr, flush=True)
        result = subprocess.run(argv, input=script, text=True, stdout=subprocess.PIPE,
                                stderr=None if interactive else subprocess.PIPE,
                                timeout=240 if interactive else 150)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Enrollment timed out; inspect remote installation before retrying") from exc
    # A failed SSH command can return arbitrary remote text. Do not relay stderr.
    output = result.stdout
    if output:
        print(output[:60000], end="" if output.endswith("\n") else "\n", flush=True)
    if result.returncode or not output.splitlines() or output.splitlines()[-1] != "ENROLLMENT_OK":
        raise RuntimeError("Enrollment not confirmed; check SSH access, trusted host key and dependencies")
