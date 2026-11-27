import unittest
from pathlib import Path
from unittest.mock import patch

from thirtyna.runtime.tunnel import _management_options


class ForwardIdentityTests(unittest.TestCase):
    @patch("thirtyna.ssh_identity.existing_identity")
    @patch("thirtyna.onboarding.verify_identity_config")
    def test_managed_forward_uses_exact_key_and_strict_host(self, verify, existing):
        key = Path("/tmp/fixture/identity")
        existing.return_value = key
        options = _management_options(dict(mode="forward", remote_id=2, host="ssh.example.test"))
        verify.assert_called_once_with("ssh.example.test", key)
        self.assertEqual(options[:2], ["-i", str(key)])
        for option in ("IdentitiesOnly=yes", "IdentityAgent=none", "CertificateFile=none",
                       "PreferredAuthentications=publickey", "StrictHostKeyChecking=yes", "ForwardAgent=no"):
            self.assertIn(option, options)

    @patch("thirtyna.ssh_identity.existing_identity", return_value=None)
    def test_no_management_key_preserves_compatibility(self, existing):
        self.assertEqual(_management_options(dict(mode="forward", remote_id=2, host="ssh.example.test")), [])

    @patch("thirtyna.ssh_identity.existing_identity")
    def test_legacy_and_reverse_do_not_change_identity(self, existing):
        self.assertEqual(_management_options(dict(mode="forward", host="ssh.example.test")), [])
        self.assertEqual(_management_options(dict(mode="reverse", remote_id=2, host="ssh.example.test")), [])
        existing.assert_not_called()

    @patch("thirtyna.ssh_identity.existing_identity", return_value=Path("/tmp/fixture/identity"))
    @patch("thirtyna.onboarding.verify_identity_config", side_effect=RuntimeError("conflicting key"))
    def test_conflicting_config_fails_closed(self, verify, existing):
        with self.assertRaisesRegex(RuntimeError, "conflicting key"):
            _management_options(dict(mode="forward", remote_id=2, host="ssh.example.test"))
