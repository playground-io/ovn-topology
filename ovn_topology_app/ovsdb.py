"""OVSDB access and trace input discovery."""
import asyncio
import ipaddress
import json
import re
import shlex
from typing import Any

from .config import Config

NB_TABLES = [
    "Logical_Switch", "Logical_Switch_Port", "Logical_Router", "Logical_Router_Port",
    "Logical_Router_Static_Route", "Logical_Router_Policy", "NAT", "Load_Balancer",
]
SB_TABLES = ["Chassis", "Encap", "Port_Binding"]
REQUIRED = {"nb:Logical_Switch", "nb:Logical_Switch_Port", "nb:Logical_Router",
            "nb:Logical_Router_Port", "sb:Chassis", "sb:Port_Binding"}


def decode(v: Any) -> Any:
    """Convert OVSDB JSON atoms (uuid/set/map) into plain Python values."""
    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
        tag, val = v
        if tag in ("uuid", "named-uuid"):
            return val
        if tag == "set":
            return [decode(x) for x in val]
        if tag == "map":
            return {decode(k): decode(x) for k, x in val}
    return v


def as_list(v: Any) -> list:
    """OVSDB sets of size 1 are encoded as the bare value; normalise to list."""
    if v is None or v == "":
        return []
    return v if isinstance(v, list) else [v]


def first(v: Any) -> Any:
    lst = as_list(v)
    return lst[0] if lst else None


def as_map(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def parse_table(text: str) -> list[dict]:
    doc = json.loads(text)
    heads = doc["headings"]
    return [{h: decode(c) for h, c in zip(heads, row)} for row in doc["data"]]


def build_trace_options(data: dict[str, list[dict]]) -> list[dict[str, Any]]:
    """Build trace selectors from datapaths and logical port address data."""
    mac_pattern = re.compile(r"^[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}$")

    def address_values(mac: Any, address_sets: list[Any]) -> tuple[set[str], set[str]]:
        macs: set[str] = set()
        ips: set[str] = set()
        if isinstance(mac, str) and mac_pattern.fullmatch(mac):
            macs.add(mac.lower())
        for address_set in address_sets:
            for address in as_list(address_set):
                if not isinstance(address, str):
                    continue
                for token in address.split():
                    if mac_pattern.fullmatch(token):
                        macs.add(token.lower())
                        continue
                    try:
                        ips.add(str(ipaddress.ip_interface(token).ip))
                    except ValueError:
                        continue
        return macs, ips

    datapaths: list[dict[str, Any]] = []
    switches = {row["_uuid"]: row for row in data.get("nb:Logical_Switch", [])}
    switch_ports = {row["_uuid"]: row for row in data.get("nb:Logical_Switch_Port", [])}
    for switch in sorted(switches.values(), key=lambda row: row.get("name", "")):
        ports = []
        all_macs: set[str] = set()
        all_ips: set[str] = set()
        for port_id in as_list(switch.get("ports")):
            port = switch_ports.get(port_id)
            if not port:
                continue
            macs, ips = address_values(
                "",
                [port.get("addresses"), port.get("dynamic_addresses")],
            )
            all_macs.update(macs)
            all_ips.update(ips)
            ports.append({"name": port["name"]})
        datapaths.append({
            "name": switch["name"],
            "kind": "Logical switch",
            "ports": sorted(ports, key=lambda port: port["name"]),
            "macs": sorted(all_macs),
            "ips": sorted(all_ips),
        })

    router_ports = {row["_uuid"]: row for row in data.get("nb:Logical_Router_Port", [])}
    for router in sorted(data.get("nb:Logical_Router", []), key=lambda row: row.get("name", "")):
        ports = []
        all_macs: set[str] = set()
        all_ips: set[str] = set()
        for port_id in as_list(router.get("ports")):
            port = router_ports.get(port_id)
            if not port:
                continue
            macs, ips = address_values(port.get("mac"), [port.get("networks")])
            all_macs.update(macs)
            all_ips.update(ips)
            ports.append({"name": port["name"]})
        datapaths.append({
            "name": router["name"],
            "kind": "Logical router",
            "ports": sorted(ports, key=lambda port: port["name"]),
            "macs": sorted(all_macs),
            "ips": sorted(all_ips),
        })
    return sorted(datapaths, key=lambda datapath: (datapath["kind"], datapath["name"]))


async def fetch_all(cfg: Config) -> dict[str, list[dict]]:
    """Dump every table we need with ONE docker exec (instead of N+1 calls)."""
    nb_db = f"--db={shlex.quote(cfg.nb_db)} " if cfg.nb_db else ""
    sb_db = f"--db={shlex.quote(cfg.sb_db)} " if cfg.sb_db else ""
    parts = []
    for prefix, tool, dbarg, tables in (
        ("nb", "ovn-nbctl", nb_db, NB_TABLES),
        ("sb", "ovn-sbctl", sb_db, SB_TABLES),
    ):
        for t in tables:
            parts.append(f'echo "@@@{prefix}:{t}"; {tool} {dbarg}--timeout=5 --format=json list {t} 2>/dev/null')
    script = "; ".join(parts)
    cmd = ["docker", "exec", cfg.container, "sh", "-c", script] if cfg.container else ["sh", "-c", script]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("Timed out querying OVN databases")
    if not out.strip():
        raise RuntimeError(f"No output from OVN ({err.decode(errors='replace').strip() or 'is the container running?'})")

    # split sections
    sections: dict[str, str] = {}
    key = None
    for line in out.decode(errors="replace").splitlines():
        if line.startswith("@@@"):
            key = line[3:].strip()
            sections[key] = ""
        elif key:
            sections[key] += line

    data: dict[str, list[dict]] = {}
    for key, text in sections.items():
        if not text.strip():
            if key in REQUIRED:
                raise RuntimeError(f"Could not read required table {key}")
            data[key] = []  # optional table, may not exist in this OVN version
            continue
        data[key] = parse_table(text)
    return data
