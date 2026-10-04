"""Mermaid flowchart generation for OVN topology."""
import html
from typing import Any

from .ovsdb import as_list, as_map, first


def _label(value: Any) -> str:
    text = html.escape(str(value), quote=True)
    return (text.replace("|", "&#124;")
            .replace("\r\n", "<br/>").replace("\n", "<br/>").replace("\r", "<br/>"))


def build_mermaid(data: dict[str, list[dict]]) -> str:
    nb = lambda name: data.get(f"nb:{name}", [])  # noqa: E731
    sb = lambda name: data.get(f"sb:{name}", [])  # noqa: E731

    switches = sorted(nb("Logical_Switch"), key=lambda row: row.get("name", ""))
    routers = sorted(nb("Logical_Router"), key=lambda row: row.get("name", ""))
    switch_ports = {row.get("_uuid"): row for row in nb("Logical_Switch_Port")}
    router_ports = {row.get("_uuid"): row for row in nb("Logical_Router_Port")}
    router_by_port: dict[str, str] = {}
    switch_ids: dict[str, str] = {}
    lines = [
        "flowchart TB",
        "  classDef router fill:#1e1b4b,stroke:#8b5cf6,color:#fff,stroke-width:2px",
        "  classDef switch fill:#082f49,stroke:#0ea5e9,color:#fff,stroke-width:2px",
        "  classDef port fill:#1e293b,stroke:#64748b,color:#e2e8f0",
        "  classDef provider fill:#500724,stroke:#ec4899,color:#fff,stroke-dasharray:5 5",
        "  classDef chassis fill:#451a03,stroke:#f59e0b,color:#fff",
    ]

    for index, router in enumerate(routers):
        node_id = f"router{index}"
        ports = [router_ports[port_id] for port_id in as_list(router.get("ports"))
                 if port_id in router_ports]
        lines.append(f'  {node_id}{{"{_label(router.get("name", "router"))}<br/>{len(ports)} ports"}}:::router')
        for port in ports:
            router_by_port[port.get("name", "")] = node_id

    for index, switch in enumerate(switches):
        node_id = f"switch{index}"
        switch_ids[switch.get("_uuid", "")] = node_id
        ports = [switch_ports[port_id] for port_id in as_list(switch.get("ports"))
                 if port_id in switch_ports]
        lines.append(f'  {node_id}[["{_label(switch.get("name", "switch"))}<br/>{len(ports)} ports"]]:::switch')

    port_ids: dict[str, str] = {}
    provider_ids: dict[str, str] = {}
    port_index = 0
    provider_index = 0
    for switch in switches:
        switch_id = switch_ids.get(switch.get("_uuid", ""))
        for port_uuid in as_list(switch.get("ports")):
            port = switch_ports.get(port_uuid)
            if not port:
                continue
            node_id = f"port{port_index}"
            port_index += 1
            port_ids[port.get("name", "")] = node_id
            status = "DISABLED" if first(port.get("enabled")) is False else (
                "UP" if first(port.get("up")) else "DOWN"
            )
            port_type = port.get("type") or "VIF"
            lines.append(f'  {node_id}(["{_label(port.get("name", "port"))}<br/>{_label(port_type)} - {status}"]):::port')
            lines.append(f"  {switch_id} --> {node_id}")

            if port_type == "router":
                peer = as_map(port.get("options")).get("router-port", "")
                router_id = router_by_port.get(peer)
                if router_id:
                    lines.append(f"  {node_id} <-->|{_label(peer)}| {router_id}")
            elif port_type == "localnet":
                network = as_map(port.get("options")).get("network_name", "provider network")
                provider_id = provider_ids.get(network)
                if provider_id is None:
                    provider_id = f"provider{provider_index}"
                    provider_index += 1
                    provider_ids[network] = provider_id
                    lines.append(f'  {provider_id}(["{_label(network)}"]):::provider')
                lines.append(f"  {node_id} --- {provider_id}")

    chassis = {row.get("_uuid", ""): row for row in sb("Chassis")}
    chassis_ids: dict[str, str] = {}
    ordered_chassis = sorted(
        chassis.values(),
        key=lambda row: row.get("hostname", row.get("name", "")),
    )
    for index, chassis_row in enumerate(ordered_chassis):
        node_id = f"chassis{index}"
        chassis_ids[chassis_row.get("_uuid", "")] = node_id
        name = chassis_row.get("hostname") or chassis_row.get("name") or "chassis"
        lines.append(f'  {node_id}[("{_label(name)}")]:::chassis')

    for binding in sb("Port_Binding"):
        port_id = port_ids.get(binding.get("logical_port", ""))
        chassis_value = first(binding.get("chassis"))
        if isinstance(chassis_value, dict):
            chassis_value = chassis_value.get("uuid", "")
        chassis_id = chassis_ids.get(str(chassis_value or ""))
        if port_id and chassis_id:
            lines.append(f"  {port_id} -.-> {chassis_id}")

    return "\n".join(lines) + "\n"
