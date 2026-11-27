# Layer 1 Tunnel Agent

The public agent `-tunnel` follows the discovered `SWITCH`, `NAME`, `run(argv)` contract. The Tunnel Worker is a separate Service Agent child and starts OpenSSH as its own supervised subprocess. It never imports SQLite or opens `hosts.db`: on each start it calls the authenticated Host Agent worker's `exists` operation using the same Service Agent IPC. It shares the Service Agent and Port Agent with the Host Agent.

## CLI contract

```bash
clear
30na -host -add -ip 192.0.2.1
30na -tunnel -help
30na -tunnel -forward -ip 192.0.2.1 -listen 8080 -target 127.0.0.1 -target-port 80
30na -tunnel -reverse -ip 192.0.2.1 -listen 8080 -target 127.0.0.1 -target-port 80
30na -tunnel -list
30na -tunnel -stop -id TUNNEL_ID
```

The `-ip` value must already be registered with the Host Agent; only numeric IPv4/IPv6 addresses are permitted. `-listen` and `-target-port` are integer ports between 1 and 65535. `-target` is a numeric IPv4 or IPv6 address. One of `-forward`, `-reverse`, `-list`, `-stop` is required. `-stop` requires the ID returned by `-forward` or `-reverse`.

Forward uses `ssh -L 127.0.0.1:LISTEN:TARGET:TARGET_PORT`; the listening socket is on the CLI host. Reverse uses `ssh -R 127.0.0.1:LISTEN:TARGET:TARGET_PORT`; the listening socket is on the remote SSH server. Both deliberately bind loopback, not public network interfaces. Dynamic forwarding (`-D`) is unsupported.

OpenSSH is invoked as an argument vector (never via a shell), with `-N -T`, `BatchMode=yes`, `ExitOnForwardFailure=yes`, and `ConnectTimeout=5`. Configure non-interactive SSH credentials (typically keys) before starting a tunnel. The CLI returns a random tunnel ID and an SSH PID. `state=starting` confirms only that the process remained alive during its initial one-second check. It does **not** prove completed authentication, remote routing, or established forwarding; an SSH process that exits later disappears from `-list` upon the next request.

## Lifecycle and safety

Each XDG data directory owns one Service Agent, one Port Agent, and separately keyed Host and Tunnel Workers. All frontend/worker requests are authenticated via the existing challenge/HMAC mechanism. Worker control sockets are allocated by the shared Port Agent. **OpenSSH itself** owns the actual forwarding listener; the Port Agent cannot pass its allocated listener FD to OpenSSH. Therefore tunnel port conflicts are detected from OpenSSH's startup diagnostics, not reassigned by the Port Agent. Port collision and SSH authentication errors after the initial check may surface asynchronously as process exit; no port fallback is attempted.

`-stop -id` stops only the tracked SSH child. When the Tunnel Worker exits normally, its `finally` block terminates and reaps all SSH children, including killing a nonresponsive child. Linux `PR_SET_PDEATHSIG` causes SSH to receive SIGTERM when its parent worker is killed. A crashed Worker is recreated on the next CLI command and has an empty tunnel registry. An unexpected SSH child exit is pruned upon the next Tunnel request. Tunnel IDs are in-memory and cease to exist when the worker stops. Host changes do not automatically terminate already established tunnels. Do not rely on this agent as a high-availability SSH connection manager.

To stop the Tunnel Worker itself without stopping Host Agent:

```bash
clear
python3 -c 'from thirtyna.runtime.service import control; print(control("stop", "tunnel"))'
```

To shut down the entire per-user Service Agent (also stops Host Agent):

```bash
clear
python3 -m thirtyna.runtime.service shutdown
```

## Verification

```bash
clear
python3 -m unittest -v tests.test_tunnel
python3 -m unittest discover -s tests -v
```

The Tunnel integration suite uses a mock SSH command that binds local loopback sockets to simulate `-L` and `-R`, exercises collision, authorization, lifecycle, cleanup, recovery, and agent process relationships. These tests **do not** validate a real SSH server or reverse forwarding over the network. Live remote SSH/port-forwarding acceptance requires a configured test server. Run the full suite against the final commit SHA on a clean Linux checkout.
