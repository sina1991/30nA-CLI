# 30nA-CLI — agent entry point

Read this file first. Do not reload old chat transcripts or the entire repository. This repository is the source of truth; never depend on agent-management-system-v2. GitHub Connector is allowed. The owner may delegate architecture, execution, review and merge authority to one agent; otherwise Alpha owns architecture/acceptance, Manager plans, Technical implements/tests. Do not claim another agent ran a command unless there is evidence.

## Start every task
1. Read the real target branch and SHA, and check whether a related PR already exists.
2. Read [development status](docs/DEVELOPMENT_STATUS.md), then only the files relevant to the task. Treat current code and observed GitHub status as authoritative; recorded test results are historical.
3. Work on a feature branch. Preserve public CLI contracts unless explicitly approved. Do not bypass protection or merge without delegated authority.
4. Run relevant tests and the full suite on Linux before publishing where possible. If execution is unavailable, explicitly label the branch unverified and use PR CI; never merge an unverified code change. Check exact final head and CI, then verify the new main SHA after authorized merge.

## Minimal context map
| Task | Read first |
|---|---|
| CLI discovery / extension | thirtyna/core.py, docs/AGENT_DEVELOPMENT_GUIDE.md |
| Host storage / SSH | thirtyna/agents/host.py, thirtyna/runtime/host.py, docs/layer1-host.md |
| IPC / worker lifecycle | thirtyna/runtime/service.py, thirtyna/runtime/ports.py, tests/test_layer1.py |
| Forward / reverse tunnels | thirtyna/agents/tunnel.py, thirtyna/runtime/tunnel.py, docs/layer1-tunnel.md, tests/test_tunnel.py, tests/test_tunnel_real.py |
| Menu / file management | thirtyna/agents/menu.py, thirtyna/menus/, tests/test_menu.py, tests/test_file_manager.py |
| Install / documentation | install.sh, docs/INSTALLATION_GUIDE.md, docs/CLI_USER_GUIDE.md |
| Validation | docs/TESTING_GUIDE.md, .github/workflows/ci.yml |

## Invariants
- Public agents expose SWITCH, NAME, run(argv); discovery belongs to core.
- Host Agent alone accesses its SQLite storage. Tunnel authorization goes through authenticated Host IPC.
- Service Agent supervises separate workers; shared Port Agent allocates worker control sockets. OpenSSH owns forwarding sockets; never kill a foreign listener.
- Forward/reverse listeners request loopback binding. No readiness claim based only on a live PID. No credentials or private keys in source, logs or commits.
- Preserve Linux isolation, XDG paths, error exit codes, noninteractive SSH and cleanup. Do not introduce unrelated dependencies or change unrelated agents.

## Validation
```bash
clear
python3 -m unittest discover -s tests -v
```
Mock SSH and real OpenSSH are distinct evidence. Live tests must use isolated credentials and endpoints. Record exact SHA, environment, executed commands, pass/fail/skip counts and limitations. Readiness, recovery policy and live coverage are tracked in the status document.

## Compact handoff
Report only mission, branch, baseline/head SHA, changed files, observed tests/CI, unresolved limitations, PR URL and next action. Update the relevant docs when changing a contract. Never hard-code a stale branch SHA in agent instructions; query GitHub. Keep this entry point short and link to detailed docs rather than duplicating them.
