"""Application configuration and shared runtime state."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Config:
    container: str = "ovn-central-az1"
    nb_db: str = ""          # e.g. "tcp:10.0.0.1:6641" (empty = local default socket)
    sb_db: str = ""          # e.g. "tcp:10.0.0.1:6642"
    interval: float = 3.0
    output: str = ""         # optional path to also write the SVG to
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class State:
    svg: str = ("<svg xmlns='http://www.w3.org/2000/svg' width='400' height='60'>"
                "<text x='10' y='30' fill='#94a3b8'>Waiting for first topology...</text></svg>")
    dot: str = ""
    version: int = 0
    updated: float = 0.0
    error: str | None = None
    stats: dict[str, int] = field(default_factory=dict)
    trace_options: list[dict[str, Any]] = field(default_factory=list)
    trace_version: int = 0
