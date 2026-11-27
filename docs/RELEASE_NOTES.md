# 30nA-CLI v1.0.0-rc.3

Third release candidate for Ubuntu terminal server management. Host addition now installs the application and Ubuntu prerequisites on the target before registration, with a downgrade guard.

- Host enrollment verifies management public-key access before registration and configures ordinary SSH login from the controller.
- Forward and Reverse use registered hosts and operator-selected TCP ports.
- Persistent Forward runs in a dedicated local systemd service.
- Reverse runs in a dedicated remote systemd service with a scoped SSH account on the listener.
- Managed tunnels support start, stop, restart and delete.
- Operator documentation includes installation, authentication, lifecycle and troubleshooting.

Automated Linux regression and OpenSSH integration must pass for the release commit.
The release candidate is intended for the final fresh-VPS chain test. Full two-VPS provisioning, VLESS traffic and reboot acceptance must be recorded before promoting to v1.0.0.

Legacy installations without a revision marker can be upgraded. Their previous launcher is backed up under /var/backups/30na-upgrade.* and existing release files remain available. Known revisions retain the ancestry check.
