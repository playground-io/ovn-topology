import unittest

from ovn_topology_app.mermaid import build_mermaid
from ovn_topology_app.ovsdb import decode
from ovn_topology_app.topology import build_dot


class TopologyTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "nb:Logical_Switch": [
                {"_uuid": "switch-1", "name": "test-switch", "ports": ["port-1"]},
            ],
            "nb:Logical_Switch_Port": [
                {
                    "_uuid": "port-1",
                    "name": "vm-1",
                    "type": "",
                    "up": True,
                    "enabled": True,
                },
            ],
        }

    def test_decode_ovsdb_values(self):
        self.assertEqual(
            decode(["map", [["key", ["set", ["value"]]]]]),
            {"key": ["value"]},
        )

    def test_build_dot_includes_switch_and_port_stats(self):
        dot, stats = build_dot(self.data)

        self.assertIn("test-switch", dot)
        self.assertIn("vm-1", dot)
        self.assertEqual(stats["switches"], 1)
        self.assertEqual(stats["ports"], 1)
        self.assertEqual(stats["ports_up"], 1)

    def test_build_mermaid_connects_switch_to_port(self):
        diagram = build_mermaid(self.data)

        self.assertIn("flowchart TB", diagram)
        self.assertIn('switch0[["test-switch<br/>1 ports"]]', diagram)
        self.assertIn('port0(["vm-1<br/>VIF - UP"])', diagram)
        self.assertIn("switch0 --> port0", diagram)

    def test_build_dot_displays_router_localnet_and_unattached_ports(self):
        data = {
            "nb:Logical_Switch": [
                {
                    "_uuid": "switch-1",
                    "name": "tenant-switch",
                    "ports": ["vm-port", "router-switch-port", "localnet-port"],
                },
            ],
            "nb:Logical_Switch_Port": [
                {"_uuid": "vm-port", "name": "vm-one", "type": "", "up": True},
                {
                    "_uuid": "router-switch-port",
                    "name": "switch-to-router",
                    "type": "router",
                    "options": {"router-port": "router-to-switch"},
                },
                {
                    "_uuid": "localnet-port",
                    "name": "provider-attachment",
                    "type": "localnet",
                    "options": {"network_name": "physnet-edge-1"},
                    "tag": [42],
                },
                {"_uuid": "orphan-switch-port", "name": "unattached-vm-port", "type": ""},
            ],
            "nb:Logical_Router": [
                {"_uuid": "router-1", "name": "tenant-router", "ports": ["router-port-1"]},
            ],
            "nb:Logical_Router_Port": [
                {
                    "_uuid": "router-port-1",
                    "name": "router-to-switch",
                    "mac": "00:00:00:00:01:01",
                    "networks": ["10.0.1.1/24"],
                    "enabled": True,
                },
                {
                    "_uuid": "orphan-router-port",
                    "name": "unattached-router-port",
                    "mac": "00:00:00:00:ff:01",
                    "networks": ["192.0.2.1/24"],
                },
            ],
        }

        dot, stats = build_dot(data)

        self.assertIn("switch_router_port_router-switch-port", dot)
        self.assertIn("router_port_router-port-1", dot)
        self.assertIn("localnet_port_localnet-port", dot)
        self.assertIn("provider-attachment", dot)
        self.assertIn("physnet-edge-1", dot)
        self.assertIn("provider_net_0", dot)
        self.assertNotIn("provider_physnet-edge-1", dot)
        self.assertIn("unattached-vm-port", dot)
        self.assertIn("unattached-router-port", dot)
        self.assertEqual(stats["logical_switch_ports"], 4)
        self.assertEqual(stats["logical_router_ports"], 2)
        self.assertEqual(stats["unattached_switch_ports"], 1)
        self.assertEqual(stats["unattached_router_ports"], 1)


if __name__ == "__main__":
    unittest.main()
