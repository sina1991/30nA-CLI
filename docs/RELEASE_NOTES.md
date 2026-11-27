# 30nA-CLI v1.0.0-rc.8

This release candidate organizes the installation, rebuild, host, tunnel and profile testing guides. Runtime commands and supported platforms are unchanged from rc.7.

- Ubuntu bootstrap follows official main. To install this exact release, check out the tag and run the bundled installer.
- Host enrollment verifies SSH access. Use the numbered inventory when selecting a destination for a managed tunnel.
- The profile benchmark supports VLESS, VMess, Trojan and Shadowsocks with compatible RAW/TCP, WebSocket and gRPC settings. Reports and rolling classifications are stored locally.
- An operator-run check returned the expected UK egress IP for six VLESS/REALITY variants, including three XHTTP modes. The check used a separate script and is not a benchmark feature in this release. The operator reported intermittent connectivity on Windows. See [acceptance evidence](RELEASE_ACCEPTANCE.md).

Start with the [documentation index](../README.md).
