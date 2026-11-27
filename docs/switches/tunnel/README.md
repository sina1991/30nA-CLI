# 30na -tunnel

Local is always ID 1. Use a stable remote ID or an explicit remote address; the latter is registered via Host Agent.

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

Forward listens on local port and targets remote loopback; Reverse listens on remote port and targets local service. Default local IP is loopback; explicit -ip binds Forward to an assigned interface and can expose it on the network. Reverse listener policy depends on remote sshd. CLI requires noninteractive SSH and verified host identity according to SSH config. Optional -restore is bounded worker-crash restoration, not restart/reboot recovery. Old target syntax is compatibility-only. See [architecture and lifecycle](../../layer1-tunnel.md).
