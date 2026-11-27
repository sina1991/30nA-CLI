# 30nA-CLI v1.0.0-rc.1

First release candidate for Ubuntu terminal server management.

- Host enrollment verifies management public-key access before registration and configures ordinary SSH login from the controller.
- Forward and Reverse use registered hosts and operator-selected TCP ports.
- Persistent Forward runs in a dedicated local systemd service.
- Reverse runs in a dedicated remote systemd service with a scoped SSH account on the listener.
- Managed tunnels support start, stop, restart and delete.
- Operator documentation includes installation, authentication, lifecycle and troubleshooting.

Automated Linux regression and OpenSSH integration must pass for the release commit.
The release candidate is intended for the final fresh-VPS chain test. Full two-VPS provisioning, VLESS traffic and reboot acceptance must be recorded before promoting to v1.0.0.
