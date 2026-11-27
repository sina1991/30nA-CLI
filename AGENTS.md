# 30nA-CLI — agent entry point

Read this file first. Do not reload old chat transcripts or the entire repository. This repository is the source of truth; never depend on agent-management-system-v2. GitHub Connector is allowed. The owner may delegate architecture, execution, review and merge authority to one agent; otherwise Alpha owns architecture/acceptance, Manager plans, Technical implements/tests. Do not claim another agent ran a command unless there is evidence.

## Start every task
1. Read the real target branch and SHA, and check whether a related PR already exists.
2. Read [development status](docs/DEVELOPMENT_STATUS.md), then only the files relevant to the task. Treat current code and observed GitHub status as authoritative; recorded test results are historical.
3. Work on a feature branch. Preserve public CLI contracts unless explicitly approved. Do not bypass protection or merge without delegated authority.
4. Run relevant tests and the full suite on Linux before publishing where possible. If execution is unavailable, explicitly label the branch unverified and use PR CI; never merge an unverified code change. Check exact final head/base and successful no-skip CI; verify the merged tree and main CI after authorized merge.

## Minimal context map
| Task | Read first |
|---|---|
| CLI discovery / extension | thirtyna/core.py, docs/AGENT_DEVELOPMENT_GUIDE.md |
| Host storage / SSH | thirtyna/agents/host.py, thirtyna/runtime/host.py, docs/layer1-host.md |
| IPC / worker lifecycle | thirtyna/runtime/service.py, thirtyna/runtime/ports.py, tests/test_layer1.py |
| Forward / reverse tunnels | thirtyna/agents/tunnel.py, thirtyna/runtime/tunnel.py, docs/layer1-tunnel.md, tests/test_tunnel.py, tests/test_tunnel_real.py |
| Menu / file management | thirtyna/agents/menu.py, thirtyna/menus/, tests/test_menu.py, tests/test_file_manager.py |
| Install / documentation | install.sh, docs/INSTALLATION_GUIDE.md, docs/CLI_USER_GUIDE.md |
| Validation | docs/TESTING_GUIDE.md, tests/run_ci.py, .github/workflows/ci.yml, docs/RELEASE_ACCEPTANCE.md |

## Invariants
- Public agents expose SWITCH, NAME, run(argv); discovery belongs to core.
- Host Agent alone accesses its SQLite storage. Shared endpoint validation is in thirtyna/address.py; DNS registration never implicitly authorizes resolved IPs. Tunnel authorization goes through authenticated Host IPC. Local ID 1 is reserved; remote IDs persist and never recycle. Read `thirtyna/endpoints.py` for endpoint mapping.
- Service Agent supervises separate workers; shared Port Agent allocates worker control sockets. OpenSSH owns forwarding sockets; runtime allocator and Tunnel never kill a foreign listener. Explicit public Port Agent emergency release follows its separate owner-verification policy.
- Default forward/reverse listeners request loopback binding. New numbered endpoint contract permits explicit assigned local IP binding for Forward and two-VPS Reverse; warn about exposure. No readiness claim based only on a live PID. No credentials or private keys in source, logs or commits.
- Preserve Linux isolation, XDG paths, error exit codes, noninteractive SSH and cleanup. Recovery is opt-in, RAM-only, bounded and reauthorizes Host. Explicit stop discards intent. Never infer readiness from process liveness or bypass Host IPC. Do not introduce unrelated dependencies or change unrelated agents.

## Validation
```bash
clear
python3 -m unittest discover -s tests -v
```
Mock SSH and real OpenSSH are distinct evidence. Live tests must use isolated credentials and endpoints. Record exact SHA, environment, executed commands, pass/fail/skip counts and limitations. Readiness, recovery policy and live coverage are tracked in the status document.

## Compact handoff
Report only mission, branch, baseline/head SHA, changed files, observed tests/CI, unresolved limitations, PR URL and next action. Update the relevant docs when changing a contract. Never hard-code a stale branch SHA in agent instructions; query GitHub. Keep this entry point short and link to detailed docs rather than duplicating them.

For TUI control-center changes, read `docs/TUI_GUIDE.md`, `thirtyna/menus/dashboard.py`, `tests/test_dashboard.py`. Delegate to the same release CLI without a shell; keep observed counts separate from command exit status. Preserve direct file manager and legacy numbered/Tk modes.

For systemd operations use `thirtyna/agents/systemctl.py`, `docs/SYSTEMD_SERVICE_GUIDE.md`, `tests/test_systemctl.py`. This public agent is distinct from the internal supervisor. Never escalate automatically or mutate real services in tests. Dashboard regions live in `thirtyna/menus/panels.py`.

Local IP discovery: `thirtyna/agents/sysinfo.py` (`-sys -ip`) uses local interface information, not Host registration or external DNS. Target pickers must not require saved hosts to show local addresses.

Public Port Inspection Agent: `thirtyna/agents/port.py`, `tests/test_port.py`, `docs/PORT_AGENT_GUIDE.md`. Distinct from runtime allocator; read-only by default. Explicit -force is the only public emergency release exception; verify exact owner, protect SSH/runtime/ancestors, never indiscriminately kill listeners. Owner/unit unknown when unavailable.

Host onboarding: `thirtyna/onboarding.py`, `docs/HOST_ONBOARDING.md`, `tests/test_onboarding.py`. Verify host identity and key-only access before saving the host. Native interactive SSH prompts only; never store passwords. Explicit Host addition deploys main with Ubuntu dependencies over root SSH and rejects downgrade or divergent installed revisions. Tunnel reauthentication does not deploy the application. All public Host additions require verified key-only access. Test fixtures may seed isolated inventories directly.

Management identity: `thirtyna/ssh_identity.py` validates and copies the operator's own local `30na_windows` pair into a private directory. Never include key contents in Git, output or IPC. Explicit interactive enrollment permits ssh-copy-id of the public key only after verified remote identity; verify key-only access before installation/registration. Existing authorized keys are preserved.

External SSH tunnel discovery: `thirtyna/remote_probe.py`, `thirtyna/tunnel_inventory.py`. Read-only; discovered units remain external. Never claim end-to-end readiness from a unit configuration. See `docs/REMOTE_TUNNEL_ARCHITECTURE.md` for the corrected two-VPS topology and remaining provisioning gates.

Two-VPS reverse engine: `thirtyna/two_vps.py`, `thirtyna/reverse_peer.py`, `tests/test_two_vps.py`. New reverse starts SSH on Remote, listens on Local, uses per-tunnel private key on Remote and scoped local account. Persist intent before mutation; stop only owned resources. Legacy worker and external services remain unchanged.

Installer bootstrap (`install.sh --bootstrap`) uses clean official main checkout only, installs missing Ubuntu prerequisites, preserves existing active SSH/socket activation, validates local root key pair if present. `INSTALL_DEPS=0` must not run apt, systemctl or modify keys.
