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

Both new modes listen on Local Port and target remote loopback:Remote Port. Forward starts SSH locally; Reverse starts SSH on Remote via a dedicated systemd service and scoped account. Default bind loopback; explicit assigned local IPv4 exposes that interface. Reverse requires root, completed Host onboarding and Local SSH port 22. Legacy target syntax is compatibility-only. [Two-VPS architecture](../../REMOTE_TUNNEL_ARCHITECTURE.md).
