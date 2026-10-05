# OVN Topology Live Viewer

A FastAPI application that reads OVN Northbound and Southbound databases,
renders the topology with Graphviz or Mermaid, and provides an in-browser
`ovn-trace` builder.

## Project layout

- `ovn_topology.py` is the backwards-compatible command-line launcher.
- `ovn_topology_app/config.py` defines configuration and shared runtime state.
- `ovn_topology_app/ovsdb.py` fetches and parses OVN database data.
- `ovn_topology_app/topology.py` generates the Graphviz topology, including
  individual nodes for Northbound ports, routes, policies, ACLs, NAT, DHCP,
  DNS, load balancers, and related network resources.
- `ovn_topology_app/mermaid.py` generates the Mermaid flowchart.
- `ovn_topology_app/trace.py` runs `ovn-trace`.
- `ovn_topology_app/monitor.py` refreshes state and renders the selected diagram.
- `ovn_topology_app/web.py` defines the FastAPI app and HTTP routes.
- `ovn_topology_app/static/` contains the browser UI, styles, and JavaScript.
- `tests/` contains unit tests for data decoding and topology generation.
- `pyproject.toml` defines the project, dependencies, CLI entry point, and
  packaged static assets.

## Setup

Install the application and its Python dependencies in editable mode:

```powershell
python -m pip install -e .
```

Use Python 3.10 or newer, as required by the project metadata.

The default Graphviz renderer requires Graphviz (including its `dot`
executable) on the host running the viewer. Mermaid diagrams are rendered in
the browser and load Mermaid from a CDN. The default configuration also expects
Docker and the OVN command-line tools inside the configured container.

## Run

```powershell
python ovn_topology.py --container ovn-central-az1 --port 8080
```

Select Mermaid instead of the default Graphviz renderer with `--renderer`:

```powershell
python ovn_topology.py --container ovn-central-az1 --renderer mermaid --port 8080
```

With `--output`, Graphviz mode writes SVG and Mermaid mode writes Mermaid
diagram source.

Alternatively, run the installed command (`ovn-topology`) or use
`python -m ovn_topology_app`.

Then open <http://localhost:8080>. To run OVN commands locally instead of
through Docker, pass `--container ""`. Remote database addresses can be
specified with `--nb-db` and `--sb-db`.

## Test

Run the test suite with Python 3.10 or newer:

```powershell
python -m unittest discover -s tests
```
