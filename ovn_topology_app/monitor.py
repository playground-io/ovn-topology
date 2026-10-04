"""Background refresh, Graphviz rendering, and shared state updates."""
import asyncio
import logging
import time

from .config import Config, State
from .ovsdb import build_trace_options, fetch_all
from .topology import build_dot

log = logging.getLogger("ovn-topology")

async def render_svg(dot: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "dot", "-Tsvg",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError("Graphviz 'dot' binary not found (apt install graphviz)")
    out, err = await asyncio.wait_for(proc.communicate(dot.encode()), timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"Graphviz error: {err.decode(errors='replace')[:500]}")
    return out.decode()


async def monitor(cfg: Config, state: State) -> None:
    last_dot = ""
    while True:
        started = time.monotonic()
        try:
            data = await fetch_all(cfg)
            trace_options = build_trace_options(data)
            if trace_options != state.trace_options:
                state.trace_options = trace_options
                state.trace_version += 1
            dot, stats = build_dot(data)
            state.stats = stats
            if dot != last_dot:
                state.svg = await render_svg(dot)
                state.dot = dot
                state.version += 1
                state.updated = time.time()
                last_dot = dot
                log.info("Topology changed -> v%d %s", state.version, stats)
                if cfg.output:
                    with open(cfg.output, "w", encoding="utf-8") as f:
                        f.write(state.svg)
            state.error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep serving the last good diagram
            if str(exc) != state.error:
                log.error("%s", exc)
            state.error = str(exc)
        await asyncio.sleep(max(0.2, cfg.interval - (time.monotonic() - started)))
