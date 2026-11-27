# Proxy Profile Test Agent

The Test Agent measures VLESS, VMess, Trojan and Shadowsocks profiles stored on the current controller. Xray-core and curl must be installed. The existing private Xray binary at ~/vless-bench/bin/xray and profile file ~/vless-bench/profiles.txt are the defaults.

Supported share links are vless://, legacy base64-JSON vmess://, trojan:// and SIP002/legacy ss://. TCP/RAW, WebSocket and gRPC transports are supported with compatible TLS settings. VLESS also supports REALITY over TCP/RAW or gRPC. Shadowsocks plugins, TCP HTTP-header obfuscation and native UDP protocols are reported as unsupported. Each endpoint must have a matching inbound configured by the operator. Native UDP paths require a separate transport design from the existing SSH TCP tunnels.

## Run all or selected profiles

```bash
clear
30na -test
```

```bash
clear
30na -test -all
```

Profile IDs follow all share links in file order, starting at 1.

```bash
clear
30na -test -vless -ids 1,3,7 -count 5
```

## Measurement options

```bash
clear
30na -test -all -count 3 -bytes 10000000 -timeout 60 -connect-timeout 10 -interval 1
```

| Option | Meaning |
| --- | --- |
| -profiles FILE | Input file containing supported share links |
| -ids 1,3,7 | Selected profile numbers |
| -all | All profiles, also the default |
| -count N | Attempts per profile, 1 through 100 |
| -bytes N | Download bytes per attempt, default 10 MB |
| -timeout SECONDS | Total timeout for each download |
| -connect-timeout SECONDS | Connection timeout for curl |
| -interval SECONDS | Delay between attempts |
| -xray PATH | Xray-core executable |
| -routes FILE | JSON map of endpoint to route label |
| -output DIRECTORY | Parent directory for generated reports |
| -help | Full CLI help |

Each profile starts an isolated Xray client on a dynamically selected loopback SOCKS port. Ownership of its listener is verified before curl uses it. The client process is terminated after its profile finishes, including interruption and errors. Temporary configuration files containing credentials are deleted on exit.

Every successful attempt must download the requested byte count. TTFB includes the complete proxied request setup. Rates are measured in Mbps. The benchmark uses the Cloudflare download endpoint.

## Route labels

The profile fragment is used as its default label. A routes.json file beside profiles.txt is loaded automatically. Route labels describe the operator's known topology and are not discovered from VLESS itself.

For the tested Iran/X/UK topology, create this file on the controller:

```bash
clear
cat > /root/vless-bench/routes.json <<'JSON'
{
  "i.30na.top:443": "i --Forward--> uk5:443",
  "i.30na.top:6677": "i --Reverse--> uk5:443",
  "i.30na.top:20100": "i --Reverse--> x --Reverse--> uk5:443",
  "i.30na.top:20200": "i --Reverse--> x --Forward--> uk5:443",
  "i.30na.top:30300": "i --Forward--> x --Reverse--> uk5:443",
  "i.30na.top:30400": "i --Forward--> x --Forward--> uk5:443"
}
JSON
```

## Reports

An execution-specific directory under ~/vless-bench/reports contains summary.csv, summary.json, details.csv, details.json and report.md. Each profile has a private diagnostic log. Completed profiles are saved immediately. Summary reports include profile ID, source line, endpoint, route, success count, median download rate and median TTFB.

Ranking orders profiles by successful attempt count, then median download speed. TCP/RAW measurements use independent sequential downloads. They reflect the current controller's route to the test endpoint.

Keep profile files and diagnostic logs private. Share summary.csv or report.md for comparison. Exit status is 0 when every selected profile passes every attempt, 1 when a profile fails, 2 for invalid options and 130 for interruption.


## Compare protocols

Put each complete share link on its own line in the existing profiles file. Profile IDs follow file order across all protocols. Filtering preserves these original IDs.

```bash
clear
30na -test -all -count 5
```

```bash
clear
30na -test -protocol trojan -count 5
```

```bash
clear
30na -test -protocol vmess -ids 2,4 -bytes 25000000
```

The -vless flag remains a VLESS-only selector. -protocol accepts all, vless, vmess, trojan and ss. Reports include protocol, a credential-free parse-failure reason, successful-run percentage, minimum/maximum download speed, median download speed and median TTFB. Test the same inbound through each intended route to compare paths, and use matching separate inbounds to compare protocols.


## Persistent catalog and three lists

History is stored on the controller at ~/.local/state/30na/tests/history.sqlite, respecting XDG_STATE_HOME. The database contains credential-free observations and a SHA-256 identity derived from each canonical client configuration. Changing a profile name preserves identity. Changing its authentication or transport configuration starts a separate history. The input share links stay in the operator's private profiles file.

Each completed profile is saved transactionally. A run/profile pair has one observation, making repeated recording idempotent. The database retains previous observations. All three lists are exported atomically in catalog.json beside the database and a snapshot is saved with every completed report.

```bash
clear
30na -test -lists
```

```bash
clear
30na -test -all -count 3
```

```bash
clear
30na -test -list 1
```

```bash
clear
30na -test -list 3 -count 5
```

The three lists are:

1. Recommended profiles with sufficient history, at least 95% successful attempts, failure rate at or below the fleet's weighted failure rate, and median speed at or above the fleet median.
2. Reserve/evaluating profiles. New profiles remain here until three separate test batches have been recorded. Profiles with no observations in the selected window are marked STALE.
3. Unreliable profiles with sufficient history and success below 70%, or failure more than 15 percentage points above the fleet's weighted failure rate. Invalid/unsupported configurations are explicitly marked here without entering the fleet comparison.

The default classification window is 24 hours. Each entry also exposes 1h, 24h and 7d aggregates. Rates use successful attempts divided by requested attempts. Download medians use individual successful samples. Speed cohorts are separated by requested download size, so use the same -bytes setting when comparing profiles or viewing their lists.

```bash
clear
30na -test -lists -window 168 -min-runs 3 -bytes 10000000
```

To change the success/failure thresholds, provide a JSON policy:

```json
{
  "good_success": 0.95,
  "bad_success": 0.70,
  "failure_margin": 0.15
}
```

```bash
clear
30na -test -all -policy /root/vless-bench/policy.json
```

-list filters the current input file by its stored classification. Lists are recomputed after tests and whenever -lists is called. The source of each measurement is the current controller. Traffic routing and server inbound creation are operator actions.

Include the history database in rebuild backups using SQLite's backup API when tests may be writing concurrently.

A validated -policy file is saved as policy.json beside the history database and automatically reused by subsequent invocations. Window and minimum-run flags remain explicit invocation settings.
