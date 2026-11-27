# Xray Configuration Agent

The first suite contains six VLESS/REALITY inbounds on ports 25001–25006: TCP with Vision, TCP without Flow, gRPC and three XHTTP modes. It uses the enabled TCP/REALITY inbound on port 443 as the source of REALITY settings for missing inbounds, with a new UUID per inbound. New inbounds listen on UK loopback for SSH forwarding. Public client links use the Iran entry IPv4.

On the standard 3x-ui server, replace the example entry address with the Iran server's public IPv4. The panel base URL, username, password and optional OTP are prompted interactively.

```bash
clear
30na -xconf -make config -entry 203.0.113.10 -output /root/xconf/profiles.txt
```

The documentation IPv4 above is a placeholder and must be replaced. Make validates prospective inbounds using the installed Xray before making API writes. Existing matching inbounds are reused. Conflicts stop the command. A batch that fails partway can be retried after resolving its error. Use `-get config` to export the existing suite without changing the inbounds. Exported links contain client credentials and are saved with owner-only permissions.

Create the corresponding Forward tunnels on Iran with `30na -tunnel -forward -persistent -ip PUBLIC_IRAN_IP -remote-id UK_ID -local-port PORT -remote-port PORT` for the desired ports. Use `30na -host -list -ids` to identify the UK host. Transfer only the exported profile file over authenticated SSH.

On Iran, run the egress check (replace the documentation IPv4 with the expected UK egress).

```bash
clear
30na -xconf -test -profiles /root/xconf/profiles.txt -expect 203.0.113.20
```

Each profile has an isolated Xray client and SOCKS listener. curl must receive a valid public IP from IPinfo through that listener. A wrong expected IP or any failed profile makes the command exit nonzero. Use the benchmark separately for speed, and repeat the probe at different times to measure intermittent availability.
