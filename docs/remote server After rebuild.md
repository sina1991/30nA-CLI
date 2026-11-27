# Remote server After rebuild

This guide applies when replacing X or UK with a fresh Ubuntu 24.04 VPS. Start from the provider console on the rebuilt host. On UK, restore the VLESS inbound on TCP 443 using its own 3x-ui backup before testing tunnels. On X, 30na supplies the intermediate listeners.

## 1. Prepare and identify the rebuilt server

On its provider console as root:

```bash
clear
apt-get update &&
apt-get install -y openssh-server &&
ssh-keygen -A &&
/usr/sbin/sshd -t &&
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Record the fingerprint. The controller needs working initial root SSH access through the provider's injected key or another existing, authorized SSH login.

## 2. Enroll from Iran and restore the shared key

On Iran, set the rebuilt host name and actual IPv4. Run this block for one server at a time. Remove the old host key only for the verified rebuilt host.

```bash
clear
remote_host=x.30na.top
remote_ip=140.233.177.220
# For UK set remote_host=uk5.30na.top and remote_ip=212.74.39.186.
test -s /root/30na-SSH-Backup.zip &&
ssh-keygen -R "$remote_host"
ssh-keygen -R "$remote_ip"
```

On Iran, in the same shell, continue. Compare the SSH fingerprint with the console output. Supply the ZIP password when prompted.

```bash
clear
: "${remote_host:?Select the rebuilt host first}"
test -s /root/30na-SSH-Backup.zip &&
30na -host -add -domain "$remote_host" &&
30na -host -list -ids
```

Expect `30NA_INSTALL_OK`, `SSH_BACKUP_RESTORED` and `HOST_ID`. This installs 30na remotely and restores the same private/public pair from the encrypted ZIP.

## 3. Restore the X → UK layer

On X, register UK first. If UK was rebuilt and X has its old SSH fingerprint, remove the old entries on X for that verified host before enrolling. Check the current inventory and create only missing entries if X is already in service.

```bash
clear
(
  set -euo pipefail
  30na -host -add -domain uk5.30na.top
  uk_id=$(30na -host -list -ids | awk '$2=="REMOTE" && $3=="uk5.30na.top" {print $1; exit}')
  test -n "$uk_id"
  30na -tunnel -reverse -localhost -remote-id "$uk_id" -local-port 20100 -remote-port 443
  30na -tunnel -forward -persistent -localhost -remote-id "$uk_id" -local-port 20200 -remote-port 443
  30na -tunnel -reverse -localhost -remote-id "$uk_id" -local-port 30300 -remote-port 443
  30na -tunnel -forward -persistent -localhost -remote-id "$uk_id" -local-port 30400 -remote-port 443
  30na -tunnel -list
)
```

## 4. Recover dependent tunnels on the controllers

On Iran and X inspect `30na -tunnel -list`. A rebuild can remove the peer half of a Reverse tunnel, including its dedicated SSH key or systemd service. Recreate affected entries using the [Iran guide](iran%20server%20after%20rebuild.md) and the X commands above. If an old managed tunnel still occupies its listener or blocks recreation, record its configuration and use `30na -tunnel -delete -id TUNNEL_ID` for that affected entry before recreating it. If deletion reports a changed peer identity or cleanup failure, resolve its recorded ownership first.

Prioritize the two direct Iran → UK routes and confirm VLESS traffic on 443 and 6677 before the four chained routes.
