import unittest

from thirtyna.address import host_address, is_domain
from thirtyna.core import UsageError


class AddressTests(unittest.TestCase):
    def test_canonical_addresses(self):
        for supplied, expected in [
            ("192.0.2.1", "192.0.2.1"),
            ("2001:0DB8::01", "2001:db8::1"),
            ("fe80::1%eth0", "fe80::1%eth0"),
            ("SSH.Example.TEST.", "ssh.example.test"),
            ("xn--bcher-kva.example", "xn--bcher-kva.example"),
        ]:
            with self.subTest(supplied=supplied):
                self.assertEqual(host_address(supplied), expected)
        self.assertTrue(is_domain("ssh.example.test"))
        self.assertFalse(is_domain("2001:db8::1"))

    def test_reject_unsafe_or_ambiguous_addresses(self):
        for value in ("", "bad", "999.999.999.999", "012.0.0.1", "a.123",
                      "-a.example", "a-.example", "a..example", "a.example..",
                      "https://a.example", "root@a.example", "a.example:22",
                      "a.example\n", "a.example ", "a_b.example", "a*.example",
                      "a;id.example", "a%h.example", "bücher.example",
                      "a" * 64 + ".example", ("a" * 63 + ".") * 4 + "test",
                      "fe80::1%bad scope", None, 123):
            with self.subTest(value=value), self.assertRaises(UsageError):
                host_address(value)
