# Iran server after rebuild

Run these steps as root on the rebuilt Ubuntu 24.04 Iran VPS. This procedure assumes the IPv4 address is still 91.216.217.244 and the UK VLESS inbound still listens on TCP 443. Keep the verified encrypted backup on X. Re-create the Iran tunnels from the commands below.

## 1. Install 30na

```bash
clear
apt-get update &&
apt-get install -y curl ca-certificates p7zip-full &&
(
  set -e
  installer=$(mktemp)
  trap 'rm -f -- "$installer"' EXIT
  curl -fsSL https://raw.githubusercontent.com/sina1991/30nA-CLI/main/install.sh -o "$installer"
  bash "$installer" --bootstrap
  /usr/local/bin/30na -help
)
```

## 2. Restore the shared SSH key

Place the original encrypted `30na-SSH-Backup.zip` in `/root` using your trusted management console or existing SSH session. The 7z archive named `30na-i-backup-20261127T145936Z.7z` on X is the separate full backup. Run on Iran and enter the ZIP password when prompted.

```bash
clear
(
  set -e
  umask 077
  test -s /root/30na-SSH-Backup.zip
  launcher=$(readlink -f /usr/local/bin/30na)
  restore_script="$(dirname "$launcher")/thirtyna/backup_peer.py"
  test -f "$restore_script"
  stage=$(mktemp -d /root/.30na-extract.XXXXXXXX)
  trap 'rm -rf -- "$stage"' EXIT
  7z e -r -y "-o$stage" -- /root/30na-SSH-Backup.zip 30na_windows 30na_windows.pub
  python3 "$restore_script" "$stage"
  ssh-keygen -lf /root/.ssh/30na-management/identity.pub
)
```

Expect `SSH_BACKUP_RESTORED` and the fingerprint of `30na-windows-admin`.

## 3. Restore the two production tunnels first

Check that the two local TCP ports are free before creating them. If one is already listening, inspect its owner and the current 30na inventory before taking action.

```bash
clear
ss -H -lntp '( sport = :443 or sport = :6677 )'
30na -tunnel -list
```

```bash
clear
(
  set -euo pipefail
  30na -host -add -domain uk5.30na.top
  uk_id=$(30na -host -list -ids | awk '$2=="REMOTE" && $3=="uk5.30na.top" {print $1; exit}')
  test -n "$uk_id"
  30na -tunnel -forward -persistent -ip 91.216.217.244 -remote-id "$uk_id" -local-port 443 -remote-port 443
  30na -tunnel -reverse -ip 91.216.217.244 -remote-id "$uk_id" -local-port 6677 -remote-port 443
  30na -tunnel -list
)
```

If prompted, verify the SSH host fingerprint before accepting and enter the existing ZIP password for key restoration on UK. Confirm `ready` and `persistent=yes` on both ports, then verify application traffic with the existing VLESS profiles on 443 and 6677.

## 4. Restore the four chains

On X confirm the four loopback tunnels to UK are ready. Use the [remote rebuild guide](remote%20server%20After%20rebuild.md) if any are missing.

```bash
clear
ssh root@x.30na.top '30na -tunnel -list'
```

On Iran, create only the missing entries on these four ports. For a clean rebuild run the full block below.

```bash
clear
(
  set -euo pipefail
  30na -host -add -domain x.30na.top
  x_id=$(30na -host -list -ids | awk '$2=="REMOTE" && $3=="x.30na.top" {print $1; exit}')
  test -n "$x_id"
  30na -tunnel -reverse -ip 91.216.217.244 -remote-id "$x_id" -local-port 20100 -remote-port 20100
  30na -tunnel -reverse -ip 91.216.217.244 -remote-id "$x_id" -local-port 20200 -remote-port 20200
  30na -tunnel -forward -persistent -ip 91.216.217.244 -remote-id "$x_id" -local-port 30300 -remote-port 30300
  30na -tunnel -forward -persistent -ip 91.216.217.244 -remote-id "$x_id" -local-port 30400 -remote-port 30400
  30na -tunnel -list
)
```

An old Reverse unit may remain on its SSH-client server after the listener VPS is rebuilt. Identify it by the saved Tunnel ID and its unit definition before removing it. New tunnel IDs are generated on rebuild.

## Operational evidence

The operator confirmed VLESS traffic after rebuilding Iran on all six entries: 443, 6677, 20100, 20200, 30300 and 30400. The supplied output showed all six listeners ready and persistent on Iran and the four loopback listeners ready on X, using v1.0.0-rc.5 (70cab2910163f9cdc48675afde21e4f3ea4191b3).
