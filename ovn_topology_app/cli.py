"""Command-line entry point."""
import argparse
import logging

import uvicorn

from .config import Config
from .web import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="OVN topology live viewer")
    ap.add_argument("--container", default=Config.container,
                    help="docker container with ovn-nbctl/ovn-sbctl (empty = run locally)")
    ap.add_argument("--nb-db", default="", help="NB DB remote, e.g. tcp:10.0.0.1:6641")
    ap.add_argument("--sb-db", default="", help="SB DB remote, e.g. tcp:10.0.0.1:6642")
    ap.add_argument("--interval", type=float, default=Config.interval, help="poll interval in seconds")
    ap.add_argument("--output", default="", help="also write the latest SVG to this file")
    ap.add_argument("--host", default=Config.host)
    ap.add_argument("--port", type=int, default=Config.port)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = Config(container=args.container, nb_db=args.nb_db, sb_db=args.sb_db, interval=args.interval,
                 output=args.output, host=args.host, port=args.port)
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="warning")
