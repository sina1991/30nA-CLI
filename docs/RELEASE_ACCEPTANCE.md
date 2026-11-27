# Layer 1 acceptance and evidence

The authoritative state is the repository's current main SHA, merged PRs and actual GitHub Actions logs. This document records the scope, validation policy and historical evidence, not an unconditional claim for future commits.

| Change | Evidence |
|---|---|
| Host / Service / Port Agent | [PR #3](https://github.com/sina1991/30nA-CLI/pull/3), historical Technical report 19/19 |
| Tunnel integration | [PR #4](https://github.com/sina1991/30nA-CLI/pull/4), historical Technical report 27/27 and isolated real SSH |
| Linux CI and agent onboarding | [PR #5](https://github.com/sina1991/30nA-CLI/pull/5), [27/27 CI](https://github.com/sina1991/30nA-CLI/actions/runs/45949327376) |
| Confirmed forwarding and failure reporting | [PR #6](https://github.com/sina1991/30nA-CLI/pull/6), [35/35 CI including real SSH](https://github.com/sina1991/30nA-CLI/actions/runs/45949844879) |
| Opt-in recovery, IPC concurrency, final CI gate | [PR #7](https://github.com/sina1991/30nA-CLI/pull/7), use latest PR checks and main Actions for final result |

## Acceptance gate

- Full Linux suite, including real isolated OpenSSH, with zero failures, errors, skips and expected failures.
- Forward and reverse bidirectional data; wrong key; port collisions preserving foreign listeners; startup timeout; delayed authentication/forwarding failures; worker crash cleanup; shared infrastructure and Host IPC.
- Opt-in restoration after a Tunnel worker crash, Host reauthorization, bounded rate, no implicit recovery after explicit stop, ordinary disconnect or Service shutdown; concurrent CLI starts and replacement Host Worker.
- Exact reviewed PR head and base, tested merge tree, no protection bypass, and clean working tree. Confirm main SHA and main CI after authorized merge.

## Remaining boundaries

Tested platform: Linux Ubuntu 24.04 with Python 3.12 and isolated OpenSSH server on loopback. Other distributions, production endpoints, remote server policy and real network conditions are not certified. Ready confirms forwarding, not application reachability. Reverse listener exposure depends on remote GatewayPorts policy. Recovery is memory-only and opt-in; no recovery after reboot, Service restart or ordinary SSH failure. An abrupt Service Agent kill may leave a private temporary socket directory; it is never reused. User-owned SSH configuration and credentials are not managed by this project. CI runs automatically, but GitHub branch protection is a separate repository setting.

New agents: start with [AGENTS.md](../AGENTS.md). Do not reload complete chat histories. Report only evidence, changes, constraints and the next action.


## Operator smoke test, 2026-11-27

Six VLESS/REALITY profiles traversed public listeners on the Iran controller and separate persistent SSH Forward tunnels to the UK host. The standalone Xray and curl check returned the expected UK egress from IPinfo in all six cases: TCP with Vision, TCP without Flow, gRPC, and XHTTP packet-up, stream-up and stream-one. The operator reported that all profiles also returned an IP on Windows, with intermittent availability. This evidence is a connectivity sample, not an uptime measurement. XHTTP and IPinfo acceptance are not built into the rc.8 Test Agent.
