# Layer 1 Tunnel Agent

The public agent exposes SWITCH, NAME, run(argv). A separate Service Agent worker owns tunnel processes and authorizes every new start through Host Agent authenticated IPC; it never opens hosts.db. The shared Port Agent allocates worker control sockets only. OpenSSH owns forwarding listeners.

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

Numeric IPv4/IPv6 addresses and ports 1–65535 are required. The SSH host must be registered. Forward requests local loopback and Reverse requests remote loopback. A remote sshd must enforce GatewayPorts=no; its policy can override requested binding. No dynamic forwarding.

## Readiness and failures

Each tunnel starts its own foreground OpenSSH ControlMaster with a short private Unix control socket, no implicit configured forwards, and noninteractive authentication. A separate control client requests exactly one forward with -O forward. The worker marks ready only when this request exits successfully and the master is alive; reverse confirmation comes from the SSH server. This proves forwarding setup, not connectivity to the ultimate target. SSH configuration still supplies credentials, host keys, user and port. Host-key verification remains subject to that configuration.

The CLI returns id, pid and state=starting or state=ready; initial errors may return nonzero. Later errors appear in -list as state=failed reason=authentication_failed, host_key_failed, connection_failed, port_collision, forwarding_rejected, forwarding_command_failed, startup_timeout or ssh_exited. Diagnostics use fixed labels rather than printing raw SSH logs. Port collisions and server policy rejection can be indistinguishable for remote forwarding. Startup has a 12-second deadline and is monitored even without CLI polling. Up to 32 active sessions and 64 failed entries are retained in memory; stop removes either type.

## Lifecycle and recovery policy

The worker terminates only its own SSH children, not foreign listeners. Parent-death signalling handles worker crashes; normal shutdown removes control directories and closes logs. SIGKILL may leave a private temporary control directory (the SSH process is terminated; do not reuse stale sockets). Failed entries and tunnel IDs are in memory and disappear after worker restart. Host removal does not automatically terminate an established tunnel. Automatic restoration is not implemented in this change and is not claimed. A fresh CLI start reauthorizes the host. Do not rely on this for high availability.

```bash
clear
python3 -c 'from thirtyna.runtime.service import control; print(control("stop", "tunnel"))'
python3 -m thirtyna.runtime.service shutdown
```

## Verification

```bash
clear
python3 -m unittest discover -s tests -v
```

Mock tests cover state transitions, delayed failures, timeout, lifecycle, isolation and port collision. CI also enables an isolated loopback sshd fixture with generated keys, strict host key verification, forward/reverse bidirectional data and authentication/collision checks. No production SSH endpoints are contacted. Local real SSH tests require the documented CI prerequisites, a non-root test user with passwordless sudo and /run/sshd; set THIRTYNA_REAL_SSH=1 explicitly. Consult actual CI logs for pass/fail; the existence of a test is not evidence that it passed.
