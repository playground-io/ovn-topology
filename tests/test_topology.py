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


if __name__ == "__main__":
    unittest.main()
