import unittest

from ovn_topology_app.mermaid import build_mermaid
from ovn_topology_app.config import State
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

    def test_new_runtime_state_gets_unique_instance_id(self):
        self.assertNotEqual(State().instance_id, State().instance_id)

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

    def test_build_dot_renders_attached_northbound_resources(self):
        data = {
            "nb:Logical_Switch": [
                {
                    "_uuid": "switch-1",
                    "name": "tenant-switch",
                    "ports": ["switch-port"],
                    "acls": ["acl-1"],
                    "dns_records": ["dns-1"],
                    "qos_rules": ["qos-1"],
                    "load_balancer": ["lb-1"],
                    "load_balancer_group": ["lb-group-1"],
                },
            ],
            "nb:Logical_Switch_Port": [
                {
                    "_uuid": "switch-port",
                    "name": "tenant-vm",
                    "type": "",
                    "enabled": True,
                    "up": True,
                    "dhcpv4_options": ["dhcp-1"],
                },
            ],
            "nb:Logical_Router": [
                {
                    "_uuid": "router-1",
                    "name": "tenant-router",
                    "ports": ["router-port"],
                    "static_routes": ["route-1"],
                    "policies": ["policy-1"],
                    "nat": ["nat-1"],
                },
            ],
            "nb:Logical_Router_Port": [
                {
                    "_uuid": "router-port",
                    "name": "router-to-switch",
                    "mac": "00:00:00:00:01:01",
                    "networks": ["10.0.1.1/24"],
                },
            ],
            "nb:Logical_Router_Static_Route": [
                {"_uuid": "route-1", "ip_prefix": "0.0.0.0/0", "nexthop": "192.0.2.1"},
            ],
            "nb:Logical_Router_Policy": [
                {
                    "_uuid": "policy-1",
                    "priority": 100,
                    "match": "ip4.src == 10.0.1.10",
                    "action": "reroute",
                    "nexthops": ["10.0.1.100"],
                },
            ],
            "nb:NAT": [
                {
                    "_uuid": "nat-1",
                    "type": "snat",
                    "external_ip": "192.0.2.10",
                    "logical_ip": "10.0.1.0/24",
                },
            ],
            "nb:Load_Balancer": [
                {
                    "_uuid": "lb-1",
                    "name": "web-lb",
                    "protocol": ["tcp"],
                    "vips": {"192.0.2.20:80": "10.0.1.10:80,10.0.1.11:80"},
                },
            ],
            "nb:Load_Balancer_Group": [
                {"_uuid": "lb-group-1", "name": "web-group", "load_balancers": ["lb-1"]},
            ],
            "nb:ACL": [
                {
                    "_uuid": "acl-1",
                    "name": "allow-web",
                    "direction": "to-lport",
                    "priority": 2000,
                    "action": "allow-related",
                    "match": "tcp.dst == 80",
                    "meter": "web-meter",
                },
            ],
            "nb:DHCP_Options": [
                {
                    "_uuid": "dhcp-1",
                    "cidr": "10.0.1.0/24",
                    "options": {"router": "10.0.1.1", "server_id": "10.0.1.2"},
                },
            ],
            "nb:DNS": [
                {"_uuid": "dns-1", "records": {"web.example.test": "10.0.1.10"}},
            ],
            "nb:Address_Set": [
                {"_uuid": "address-set-1", "name": "web-clients", "addresses": ["10.0.1.20"]},
            ],
            "nb:Port_Group": [
                {"_uuid": "port-group-1", "name": "web-ports", "ports": ["switch-port"], "acls": ["acl-1"]},
            ],
            "nb:Meter": [
                {"_uuid": "meter-1", "name": "web-meter", "bands": ["band-1"]},
            ],
            "nb:QoS": [
                {
                    "_uuid": "qos-1",
                    "direction": "from-lport",
                    "priority": 100,
                    "match": "tcp.dst == 80",
                    "action": {"bandwidth": 1000},
                },
            ],
        }

        dot, _ = build_dot(data)

        for node_id in (
            "resource_acl_acl-1",
            "resource_dhcp_dhcp-1",
            "resource_dns_dns-1",
            "resource_qos_qos-1",
            "resource_route_route-1",
            "resource_policy_policy-1",
            "resource_nat_nat-1",
            "resource_load balancer_lb-1",
            "resource_load balancer group_lb-group-1",
            "resource_port group_port-group-1",
            "resource_address set_address-set-1",
            "resource_meter_meter-1",
        ):
            self.assertIn(f'"{node_id}" [', dot)
        self.assertIn("allow-web", dot)
        self.assertIn("10.0.1.1", dot)
        self.assertIn("192.0.2.10", dot)
        self.assertIn("web.example.test", dot)
        self.assertIn("web-meter", dot)


if __name__ == "__main__":
    unittest.main()
