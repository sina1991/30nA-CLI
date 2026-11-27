# 30na -tunnel

The Tunnel Agent manages persistent OpenSSH `-L` and `-R` tunnels for Host Agent-registered IP addresses. Forward listens on local loopback; reverse listens on remote loopback. See [Tunnel architecture and lifecycle](../../layer1-tunnel.md).

```bash
clear
30na -tunnel -help
30na -tunnel -forward -ip 192.0.2.1 -listen 8080 -target 127.0.0.1 -target-port 80
30na -tunnel -reverse -ip 192.0.2.1 -listen 8080 -target 127.0.0.1 -target-port 80
30na -tunnel -list
30na -tunnel -stop -id TUNNEL_ID
```

Requires a registered Host and non-interactive OpenSSH authentication. `state=starting` does not certify remote readiness. No dynamic forwarding.
