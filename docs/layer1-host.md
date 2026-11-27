# Layer 1 on Linux

The CLI parses Host arguments and calls `control("ensure", "host", bootstrap=True)`.
The first caller locks the private runtime directory, binds a loopback control
socket and passes its descriptor and a lifetime lock to the detached Service
Agent. The Service Agent starts the Port Agent over an inherited private
socketpair. The allocator has no dependency on service discovery.

Register a worker handler in `service.REGISTRY` outside the public switch
package. Its arguments are the resolved data folder, operation and argument.
The supervisor serializes ensure/status/stop. On ensure, the allocator binds
and listens, transfers the bound descriptor with SCM_RIGHTS and closes its
copy. The supervisor passes the descriptor to its direct child and closes
its copy. The last close releases the port, including on worker crash.
THIRTYNA_PREFERRED_PORT selects a candidate at cold start for collision tests;
the default is OS allocation. EADDRINUSE retries with OS allocation.

An ensure reply supplies address, port, worker PID and an instance key.
Each connection challenges the server; each request must answer a fresh
server challenge using HMAC-SHA256. Readiness includes a signed worker reply
and matching child PID. Status omits keys and returns the last successful
operation's caller-reported PID and the worker's own PID. Control credentials
live under the owner-only .runtime directory beside hosts.db. Agents sharing
a Unix account and data directory share its authority. Each resolved data
directory has a separate supervisor and database.

Stop closes the lifetime channel and waits for the direct child. Unexpected
supervisor exit also closes this channel. A dead child is reaped on the next
lifecycle request. No saved PID or port is used to signal processes.
SSH runs in the frontend after the worker authorizes the saved address
(or successfully inserts it for add with SSH), preserving terminal ownership.

## Observe and stop

Run from the checkout with the same XDG_DATA_HOME as the CLI. After installation
use the release directory containing the resolved 30na launcher as the cwd.

```bash
clear
export XDG_DATA_HOME="$(mktemp -d)"
./30na -host -list
python3 -m thirtyna.runtime.service status
python3 -m thirtyna.runtime.service stop
./30na -host -list
python3 -m thirtyna.runtime.service shutdown
```

## Reproduce the acceptance scenarios

```bash
clear
PYTHONPATH=tests python3 -m unittest -v test_layer1.LayerTests.test_a_cold
PYTHONPATH=tests python3 -m unittest -v test_layer1.LayerTests.test_b_process
PYTHONPATH=tests python3 -m unittest -v test_layer1.LayerTests.test_c_parallel
PYTHONPATH=tests python3 -m unittest -v test_layer1.LayerTests.test_d_collision
PYTHONPATH=tests python3 -m unittest -v test_layer1.LayerTests.test_e_recovery
PYTHONPATH=tests python3 -m unittest -v test_layer1.LayerTests.test_f_legacy_isolation_tty test_cli.CLITests
python3 -m unittest discover -s tests -v
```

Each lifecycle scenario runs real CLI processes in temporary data directories.
The tests match the worker's open socket inodes against Linux /proc/net/tcp,
check supervisor child membership, and shut down the test runtime.
