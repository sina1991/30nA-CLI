# VLESS Test Agent

The first Test Agent release measures the VLESS profiles stored on the current controller. Xray-core and curl must be installed. The existing private Xray binary at ~/vless-bench/bin/xray and profile file ~/vless-bench/profiles.txt are the defaults.

Supported profiles use VLESS over TCP/RAW with REALITY, TLS or no transport security. Unsupported profiles receive CONFIG_ERROR.

## Run all or selected profiles

```bash
clear
30na -test
```

```bash
clear
30na -test -vless -all
```

Profile IDs follow the VLESS links in file order, starting at 1.

```bash
clear
30na -test -vless -ids 1,3,7 -count 5
```

## Measurement options

```bash
clear
30na -test -vless -all -count 3 -bytes 10000000 -timeout 60 -connect-timeout 10 -interval 1
```

| Option | Meaning |
| --- | --- |
| -profiles FILE | Input file containing VLESS links |
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
