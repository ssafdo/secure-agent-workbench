from __future__ import annotations

import unittest

from scripts.run_container_niceeval import parse_wsl_gateway


class WslGatewayParsingTests(unittest.TestCase):
    def test_extracts_gateway_from_default_route(self) -> None:
        route = "default via 172.23.240.1 dev eth0 proto kernel\n"

        self.assertEqual(parse_wsl_gateway(route), "172.23.240.1")

    def test_rejects_route_without_gateway(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "did not report"):
            parse_wsl_gateway("default dev eth0 scope link\n")

    def test_rejects_invalid_ipv4_gateway(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            parse_wsl_gateway("default via 999.23.240.1 dev eth0\n")


if __name__ == "__main__":
    unittest.main()
