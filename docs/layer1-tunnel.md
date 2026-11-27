# Layer 1 Tunnel Agent

For boot-persistent Forward and Reverse and lifecycle commands, see the [operator quickstart](TUNNEL_QUICKSTART.md).

The public agent exposes SWITCH, NAME, run(argv). A separate Service Agent worker owns tunnel processes and authorizes every new start through Host Agent authenticated IPC; it never opens hosts.db. The shared Port Agent allocates worker control sockets only. OpenSSH owns forwarding listeners.

## CLI contract

```bash
clear
30na -host -list -ids
30na -tunnel -forward -local-port 8080 -remote-id 3 -remote-port 443
30na -tunnel -reverse -local-port 8080 -remote-id 3 -remote-port 443
30na -tunnel -forward -localhost -id 1 -local-port 8080 -remote-ip 192.0.2.10 -remote-port 443
30na -tunnel -reverse -local-port 8080 -remote-domain ssh.example.test -remote-port 443
30na -tunnel -list
30na -tunnel -stop -id TUNNEL_ID
```

Local is always ID 1. For new numbered endpoint syntax, both modes listen on Local Port and target Remote loopback:Remote Port. Forward retains the worker; Reverse launches its dedicated systemd unit on Remote with a scoped local SSH account and a key generated on Remote. Default bind is loopback; explicit assigned IPv4 exposes the chosen interface. Reverse requires root, enrolled Remote, reachable Local IPv4 and SSH port 22. The legacy -target syntax and already-running worker sessions are unchanged and may use the historical opposite topology. See [two-VPS architecture](REMOTE_TUNNEL_ARCHITECTURE.md).

## Readiness and failures

Each tunnel starts its own foreground OpenSSH ControlMaster with a short private Unix control socket, no implicit configured forwards, and noninteractive authentication. A separate control client requests exactly one forward with -O forward. The worker marks ready only when this request exits successfully and the master is alive; reverse confirmation comes from the SSH server. This proves forwarding setup, not connectivity to the ultimate target. SSH configuration still supplies credentials, host keys, user and port. Host-key verification remains subject to that configuration.

The CLI returns id, pid and state=starting or state=ready; initial errors may return nonzero. Later errors appear in -list as state=failed reason=authentication_failed, host_key_failed, connection_failed, port_collision, forwarding_rejected, forwarding_command_failed, startup_timeout or ssh_exited. Diagnostics use fixed labels rather than printing raw SSH logs. Port collisions and server policy rejection can be indistinguishable for remote forwarding. Startup has a 12-second deadline and is monitored even without CLI polling. Up to 32 active sessions and 64 failed entries are retained in memory; stop removes either type.

## Lifecycle and recovery policy

The worker terminates only its own SSH children, not foreign listeners. Parent-death signalling handles worker crashes; normal shutdown removes control directories and closes logs. The supervisor owns a separate private directory for each Tunnel worker and removes that exact directory on worker exit. A supervisor SIGKILL can leave its private temporary directory, but stale sockets are never reused.

Worker-owned tunnels are not restored by default. Add `-restore` to Forward or legacy Reverse; the new two-VPS Reverse instead persists as a systemd unit:

```bash
clear
30na -tunnel -forward -local-port 8080 -remote-id 3 -remote-port 80 -restore
```

Only confirmed ready opted-in sessions are recorded in a RAM-only memfd journal owned by the Tunnel worker and retained by the running Service Agent. The supervisor checks for worker death and recreates it while there is recovery intent, at most three automatic recreations per 60 seconds. The new worker consumes the old intent before attempting recovery, reauthorizes each host using authenticated Host IPC and reissues forwarding with the same ID and a new SSH PID. The `-list` output includes restore=on; while recovering a queued entry can show pid=0. Interrupted/malformed journal writes are discarded rather than replaying older intent.

An ordinary SSH disconnect is reported as failed; it is not retried indefinitely. Failed recovery is not automatically retried. Removing a Host prevents future restoration but does not terminate an existing connection. Explicit `-stop -id` removes intent before terminating the session; stopping the Tunnel worker or Service Agent discards all recovery intent. Service restart, system reboot and existing TCP streams are not recoverable by this mechanism. No SSH credentials are stored. This is bounded worker-crash recovery, not a high-availability connection manager.

The supervisor supplies the current Host worker reference over its private inherited control channel. Tunnel authenticates directly with Host; it does not invoke the supervisor recursively. This avoids the former lock inversion under concurrent CLI requests. Restart the old Service Agent before switching installed releases; the new Tunnel CLI checks its worker protocol version.

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

Numbered Forward automatically uses the locally imported management key if present, with the same strict host-key and identity configuration checks as onboarding. Legacy commands and installations without a management key retain the original SSH configuration behavior. An old supervisor must be restarted before new managed Forward starts; existing tunnels are not stopped automatically.
