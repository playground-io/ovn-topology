"""Graphviz DOT generation for OVN topology."""
import html
from typing import Any

from .ovsdb import as_list, as_map, first

# Palette: red/green are reserved for status; each element type has its own hue AND shape.
C_BG = "#0b1220"
C_ROUTER = "#8b5cf6"    # violet  - hexagon
C_SWITCH = "#0ea5e9"    # sky     - 3D box
C_PORT = "#64748b"      # slate   - rounded pill (border colour = status)
C_PROVIDER = "#ec4899"  # pink    - dashed ellipse (cloud)
C_CHASSIS = "#f59e0b"   # amber   - component (host)
C_MUTED = "#94a3b8"
C_OK = "#22c55e"
C_BAD = "#ef4444"
C_OFF = "#a1a1aa"


def esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def q(s: Any) -> str:
    """Quote a DOT identifier / plain string."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def short(u: str | None) -> str:
    return (u or "")[:8]


def trunc(s: str, n: int = 30) -> str:
    return s if len(s) <= n else s[: n // 2 - 1] + ".." + s[-(n // 2 - 1):]


def clip(items: list[str], n: int = 4) -> list[str]:
    return items if len(items) <= n else items[:n] + [f"... +{len(items) - n} more"]


def t(text: Any, size: int | None = None, color: str | None = None, bold: bool = False) -> str:
    """Styled text run for an HTML-like Graphviz label."""
    out = esc(text)
    if bold:
        out = f"<B>{out}</B>"
    attrs = (f' POINT-SIZE="{size}"' if size else "") + (f' COLOR="{color}"' if color else "")
    return f"<FONT{attrs}>{out}</FONT>" if attrs else out


def led(color: str, size: int = 16) -> str:
    """Status light: a coloured circle glyph."""
    return f'<FONT COLOR="{color}" POINT-SIZE="{size}">&#9679;</FONT>'


def label(*lines: str) -> str:
    return "<" + "<BR/>".join(x for x in lines if x) + ">"


def shaped(nid: str, shape: str, lbl: str, *, fill: str, border: str, tooltip: str, cls: str,
           style: str = "filled", penwidth: float = 2.0, margin: str = "0.22,0.14") -> str:
    return (f'{q(nid)} [shape={shape}, style={q(style)}, fillcolor={q(fill)}, color={q(border)}, '
            f'penwidth={penwidth}, margin={q(margin)}, label={lbl}, tooltip={q(tooltip)}, class={q(cls)}];')


def edge_label(lines: list[str]) -> str:
    return "<" + "<BR/>".join(esc(x) for x in lines if x) + ">"


def nat_line(n: dict) -> str:
    kind, ext, log_ip = n.get("type", ""), n.get("external_ip", ""), n.get("logical_ip", "")
    if kind == "snat":
        return f"SNAT {log_ip} -> {ext}"
    if kind == "dnat":
        return f"DNAT {ext} -> {log_ip}"
    return f"DNAT+SNAT {ext} <-> {log_ip}"


def port_status(p: dict) -> str:
    if first(p.get("enabled")) is False:
        return "DISABLED"
    return "UP" if first(p.get("up")) else "DOWN"


STATUS_COLOR = {"UP": C_OK, "DOWN": C_BAD, "DISABLED": C_OFF}


def build_dot(data: dict[str, list[dict]]) -> tuple[str, dict[str, int]]:
    nb = lambda name: data.get(f"nb:{name}", [])  # noqa: E731
    sb = lambda name: data.get(f"sb:{name}", [])  # noqa: E731

    switches = sorted(nb("Logical_Switch"), key=lambda r: r["name"])
    routers = sorted(nb("Logical_Router"), key=lambda r: r["name"])
    lsp = {r["_uuid"]: r for r in nb("Logical_Switch_Port")}
    lrp_by_uuid = {r["_uuid"]: r for r in nb("Logical_Router_Port")}
    lrp_by_name = {r["name"]: r for r in lrp_by_uuid.values()}
    routes = {r["_uuid"]: r for r in nb("Logical_Router_Static_Route")}
    nats = {r["_uuid"]: r for r in nb("NAT")}
    lbs = {r["_uuid"]: r for r in nb("Load_Balancer")}

    lrp_owner: dict[str, str] = {}  # lrp name -> router uuid
    for r in routers:
        for pu in as_list(r.get("ports")):
            if pu in lrp_by_uuid:
                lrp_owner[lrp_by_uuid[pu]["name"]] = r["_uuid"]

    chassis = {c["_uuid"]: c for c in sb("Chassis")}
    encaps = {e["_uuid"]: e for e in sb("Encap")}
    pbind = {r["logical_port"]: r for r in sb("Port_Binding")}

    # Gateway placement: chassisredirect ports (cr-<lrp>) are bound to the active gateway chassis
    lrp_active_gw: dict[str, str] = {}
    for lport, row in pbind.items():
        if lport.startswith("cr-") and first(row.get("chassis")):
            lrp_active_gw[lport[3:]] = first(row["chassis"])
    gw_chassis = set(lrp_active_gw.values())

    dot: list[str] = [
        "digraph ovn_topology {",
        f'  graph [rankdir=TB, bgcolor="{C_BG}", fontname="Helvetica", pad="0.5", nodesep="0.45", '
        'ranksep="1.0", compound=true, splines=true];',
        '  node [fontname="Helvetica", fontsize=11, fontcolor=white];',
        '  edge [fontname="Helvetica", color="#475569", fontcolor="#cbd5e1", penwidth=1.5, fontsize=9, arrowsize=0.8];',
        "",
    ]
    edges: list[str] = []
    clusters: dict[str | None, list[str]] = {None: []}
    chassis_port_count: dict[str, int] = {}
    chassis_node_id = lambda cu: f"chassis_{cu}"  # noqa: E731
    provider_nets: set[str] = set()
    router_links: set[frozenset] = set()
    n_ports = n_up = n_down = 0

    # ---- Chassis details (SB) ----------------------------------------------------
    chassis_info: dict[str, dict] = {}
    for cu, c in chassis.items():
        es = [encaps[u] for u in as_list(c.get("encaps")) if u in encaps]
        oc = as_map(c.get("other_config"))
        chassis_info[cu] = {
            "host": c.get("hostname") or c.get("name") or cu,
            "sysid": c.get("name"),
            "ips": sorted({e["ip"] for e in es if e.get("ip")}),
            "types": sorted({e["type"] for e in es if e.get("type")}),
            "bridges": oc.get("ovn-bridge-mappings"),
            "gw": cu in gw_chassis or "enable-chassis-as-gw" in oc.get("ovn-cms-options", ""),
        }
        clusters[cu] = []

    # ---- Routers: hexagon --------------------------------------------------------
    for r in routers:
        ext = as_map(r.get("external_ids"))
        lrps = [lrp_by_uuid[u] for u in as_list(r.get("ports")) if u in lrp_by_uuid]
        problems = []
        for l in lrps:
            if first(l.get("enabled")) is False:
                problems.append(f"{l['name']} disabled")
            has_gw = bool(as_list(l.get("gateway_chassis"))) or bool(first(l.get("ha_chassis_group")))
            if has_gw and l["name"] not in lrp_active_gw:
                problems.append(f"{l['name']}: no active gateway")
        rt = [f"{x['ip_prefix']} via {x['nexthop']}" + (f" ({x['output_port']})" if first(x.get("output_port")) else "")
              for x in (routes[u] for u in as_list(r.get("static_routes")) if u in routes)]
        nt = [nat_line(x) for x in (nats[u] for u in as_list(r.get("nat")) if u in nats)]
        lb = [f"{x['name']} ({len(as_map(x.get('vips')))} vips)"
              for x in (lbs[u] for u in as_list(r.get("load_balancer")) if u in lbs)]
        alias = ext.get("neutron:router_name")
        lines = [
            t("ROUTER", 8, "#c4b5fd"),
            led(C_BAD if problems else C_OK, 18) + " " + t(r["name"], 15, "#ffffff", True),
            t(alias, 10, C_MUTED) if alias and alias != r["name"] else "",
            t(f"{len(lrps)} ports · {len(rt)} route{'' if len(rt) == 1 else 's'} · {len(nt)} NAT", 10, "#ddd6fe"),
        ]
        lines += [t(x, 9, C_MUTED) for x in clip(rt, 3) + clip(nt, 3) + clip(lb, 2)]
        lines += [t(x, 9, C_BAD) for x in problems]
        if as_list(r.get("policies")):
            lines.append(t(f"{len(as_list(r['policies']))} policies", 9, C_MUTED))
        dot.append("  " + shaped(f"router_{r['_uuid']}", "hexagon", label(*lines), fill="#1e1b4b", border=C_ROUTER,
                                 tooltip=f"{r['name']} | {r['_uuid']}", cls="router", penwidth=2.5,
                                 margin="0.3,0.2"))

    # ---- Switches (3D box) + ports ----------------------------------------------
    for s in switches:
        sid = f"switch_{s['_uuid']}"
        oc, ext = as_map(s.get("other_config")), as_map(s.get("external_ids"))
        ports = sorted((lsp[u] for u in as_list(s.get("ports")) if u in lsp), key=lambda p: p["name"])
        vif = [p for p in ports if (p.get("type") or "") not in ("router", "localnet")]
        up_n = sum(1 for p in vif if port_status(p) == "UP")
        sw_led = C_OFF if not vif else (C_OK if up_n == len(vif) else C_BAD)
        lb = [f"{x['name']} ({len(as_map(x.get('vips')))} vips)"
              for x in (lbs[u] for u in as_list(s.get("load_balancer")) if u in lbs)]
        alias = ext.get("neutron:network_name")
        subnet = oc.get("subnet") or oc.get("ipv6_prefix")
        extra = " · ".join(x for x in (f"{len(as_list(s.get('acls')))} ACLs" if as_list(s.get("acls")) else "",
                                       ", ".join(clip(lb, 2))) if x)
        lines = [
            t("SWITCH", 8, "#7dd3fc"),
            led(sw_led, 18) + " " + t(s["name"], 14, "#ffffff", True),
            t(alias, 10, C_MUTED) if alias and alias != s["name"] else "",
            t(subnet, 11, "#7dd3fc") if subnet else "",
            t(f"{up_n}/{len(vif)} ports up" if vif else "no VM ports", 10, C_OK if sw_led == C_OK else (C_BAD if sw_led == C_BAD else C_OFF)),
            t(extra, 9, C_MUTED) if extra else "",
        ]
        dot.append("  " + shaped(sid, "box3d", label(*lines), fill="#082f49", border=C_SWITCH,
                                 tooltip=f"{s['name']} | {s['_uuid']}", cls="switch", penwidth=2.0,
                                 margin="0.3,0.18"))

        for p in ports:
            ptype = p.get("type") or ""
            opts = as_map(p.get("options"))
            n_ports += 1

            if ptype == "router":
                lrp_name = opts.get("router-port", "")
                lrp = lrp_by_name.get(lrp_name)
                owner = lrp_owner.get(lrp_name)
                if not lrp or not owner:
                    continue
                gw = lrp_name in lrp_active_gw or bool(as_list(lrp.get("gateway_chassis"))) \
                    or bool(first(lrp.get("ha_chassis_group")))
                lines = [f"LRP: {lrp_name}", f"MAC: {lrp.get('mac', 'N/A')}"]
                lines += [f"IP: {n}" for n in as_list(lrp.get("networks"))]
                if gw:
                    lines.append("(gateway port)")
                if first(lrp.get("enabled")) is False:
                    lines.append("DISABLED")
                edges.append(f'  {q("router_" + owner)} -> {q(sid)} [dir=both, color="#a78bfa", '
                             f'fontcolor="#c4b5fd", penwidth=2.2, label={edge_label(lines)}];')
                gcu = lrp_active_gw.get(lrp_name)
                if gcu in chassis:
                    edges.append(f'  {q("router_" + owner)} -> {q(chassis_node_id(gcu))} '
                                 f'[style=dotted, color="{C_CHASSIS}", fontcolor="{C_CHASSIS}", '
                                 f'label={edge_label(["active gw", lrp_name])}, constraint=false];')
                continue

            if ptype == "localnet":
                net = opts.get("network_name", "?")
                pid = f"provider_{net}"
                if net not in provider_nets:
                    provider_nets.add(net)
                    cloud = f'<FONT COLOR="#f9a8d4" POINT-SIZE="18">&#9729;</FONT> {t(net, 13, "#ffffff", True)}'
                    dot.append("  " + shaped(pid, "ellipse", label(t("PROVIDER NETWORK", 8, "#f9a8d4"), cloud),
                                             fill="#2a0f22", border=C_PROVIDER, tooltip=f"physnet {net}",
                                             cls="provider", style="filled,dashed", penwidth=2.0))
                tag = first(p.get("tag"))
                net_lines = ["localnet: " + p["name"]]
                if tag is not None:
                    net_lines.append(f"VLAN {tag}")
                edges.append(f'  {q(sid)} -> {q(pid)} [dir=both, color="{C_PROVIDER}", fontcolor="#f9a8d4", '
                             f'label={edge_label(net_lines)}];')
                continue

            # VIF / localport / virtual / external ... : rounded pill with a status light
            status = port_status(p)
            if status == "UP":
                n_up += 1
            else:
                n_down += 1
            scol = STATUS_COLOR[status]
            addrs = as_list(p.get("addresses"))
            if "dynamic" in addrs:
                addrs = [a for a in addrs if a != "dynamic"] + [first(p.get("dynamic_addresses")) or "dynamic"]
            addrs = [a for a in addrs if a not in ("unknown", "router")]
            sec = as_list(p.get("port_security"))
            parent, tag = first(p.get("parent_name")), first(p.get("tag"))
            tags = [x for x in (ptype, "port-sec" if sec else "", f"parent {parent} vlan {tag}" if parent else "",
                                "dhcp" if first(p.get("dhcpv4_options")) else "", status if status == "DISABLED" else "")
                    if x]
            lines = [led(scol, 15) + " " + t(trunc(p["name"]), 11, "#ffffff", True)]
            lines += [t(a, 9, C_MUTED) for a in clip(addrs, 2)]
            if tags:
                lines.append(t(" · ".join(tags), 8, "#64748b"))
            pid = f"port_{p['_uuid']}"
            cu = first(pbind.get(p["name"], {}).get("chassis"))
            cu = cu if cu in chassis else None
            tip = f"{p['name']} | {status} | {' ; '.join(addrs)} | {p['_uuid']}"
            clusters[cu].append("    " + shaped(pid, "box", label(*lines), fill="#111c2e", border=scol, tooltip=tip,
                                                cls=f"port {status.lower()}", style="rounded,filled", penwidth=2.2,
                                                margin="0.16,0.09"))
            if cu:
                chassis_port_count[cu] = chassis_port_count.get(cu, 0) + 1
            edges.append(f'  {q(sid)} -> {q(pid)} [dir=none, color="#334155", penwidth=1.2];')

    # ---- Router <-> router peering -----------------------------------------------
    for name, lrp in lrp_by_name.items():
        peer = first(lrp.get("peer"))
        if not peer or peer not in lrp_by_name:
            continue
        key = frozenset((name, peer))
        if key in router_links or name not in lrp_owner or peer not in lrp_owner:
            continue
        router_links.add(key)
        lines = [f"{name} <-> {peer}"] + as_list(lrp.get("networks"))
        edges.append(f'  {q("router_" + lrp_owner[name])} -> {q("router_" + lrp_owner[peer])} '
                     f'[dir=both, color="#a78bfa", fontcolor="#c4b5fd", label={edge_label(lines)}];')

    # ---- Chassis clusters: host = "component" shape ------------------------------
    for cu in sorted(chassis, key=lambda k: chassis_info[k]["host"]):
        ci = chassis_info[cu]
        role = t("GATEWAY", 9, C_CHASSIS, True) if ci["gw"] else t("COMPUTE", 9, C_MUTED, True)
        lines = [
            t("CHASSIS", 8, "#fcd34d"),
            t(ci["host"], 13, "#ffffff", True),
            t(ci["sysid"], 9, C_MUTED) if ci["sysid"] and ci["sysid"] != ci["host"] else "",
            t(f"{', '.join(ci['ips']) or 'N/A'} · {', '.join(ci['types']) or 'N/A'}", 10, "#fde68a"),
            t("bridges: " + ci["bridges"], 9, C_MUTED) if ci["bridges"] else "",
            role + t(f"  ·  {chassis_port_count.get(cu, 0)} ports", 9, C_MUTED),
        ]
        dot.append(f"  subgraph {q('cluster_' + cu)} {{")
        dot.append(f'    label={q("Chassis: " + str(ci["host"]))}; style="dashed,rounded"; color="{C_CHASSIS}"; '
                   f'fontcolor="#fde68a"; fontsize=12; bgcolor="#111a2e";')
        dot.append("    " + shaped(chassis_node_id(cu), "component", label(*lines), fill="#2b1d05", border=C_CHASSIS,
                                   tooltip=f"{ci['host']} | {cu}", cls="chassis", penwidth=2.0))
        dot.extend(sorted(clusters[cu]))
        dot.append("  }")

    if clusters[None]:
        dot.append('  subgraph "cluster_unbound" {')
        dot.append(f'    label="Unbound / not scheduled"; style="dashed,rounded"; color="#64748b"; '
                   f'fontcolor="{C_MUTED}"; fontsize=12; bgcolor="{C_BG}";')
        dot.extend(sorted(clusters[None]))
        dot.append("  }")

    dot.extend(sorted(edges))
    dot.append("}")

    stats = {
        "routers": len(routers), "switches": len(switches), "chassis": len(chassis),
        "provider_networks": len(provider_nets), "ports": n_ports,
        "ports_up": n_up, "ports_down": n_down, "unbound_ports": len(clusters[None]),
    }
    return "\n".join(dot), stats
