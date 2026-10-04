"""FastAPI application and HTTP routes."""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import Config, State
from .monitor import monitor
from .trace import run_ovn_trace

log = logging.getLogger("ovn-topology")
STATIC_DIR = Path(__file__).with_name("static")
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def create_app(cfg: Config) -> FastAPI:
    state = State()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(monitor(cfg, state))
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(lifespan=lifespan, title="OVN Topology")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/diagram.svg")
    def diagram(request: Request) -> Response:
        etag = f'"v{state.version}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304)
        return Response(state.svg, media_type="image/svg+xml", headers={"ETag": etag, "Cache-Control": "no-cache"})

    @app.get("/diagram.dot", response_class=PlainTextResponse)
    def diagram_dot() -> str:
        return state.dot

    @app.get("/status")
    def status() -> JSONResponse:
        return JSONResponse({"version": state.version, "updated": state.updated,
                             "error": state.error, "stats": state.stats,
                             "trace_version": state.trace_version})

    @app.get("/trace-options")
    def trace_options() -> JSONResponse:
        return JSONResponse({"datapaths": state.trace_options, "version": state.trace_version})

    @app.post("/ovn-trace")
    async def ovn_trace(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "Request body must be valid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"error": "Request body must be a JSON object"}, status_code=400)

        datapath = payload.get("datapath")
        microflow = payload.get("microflow")
        if not isinstance(datapath, str) or not datapath.strip():
            return JSONResponse({"error": "A datapath is required"}, status_code=400)
        if not isinstance(microflow, str) or not microflow.strip():
            return JSONResponse({"error": "A microflow is required"}, status_code=400)
        datapath, microflow = datapath.strip(), microflow.strip()
        if len(datapath) > 256 or len(microflow) > 4096:
            return JSONResponse({"error": "Datapath or microflow exceeds the allowed length"}, status_code=400)
        if "\x00" in datapath or "\x00" in microflow:
            return JSONResponse({"error": "Datapath and microflow cannot contain NUL characters"}, status_code=400)

        try:
            returncode, output = await run_ovn_trace(cfg, datapath, microflow)
        except TimeoutError as exc:
            return JSONResponse({"error": str(exc)}, status_code=504)
        except OSError as exc:
            log.error("Could not start ovn-trace: %s", exc)
            return JSONResponse({"error": f"Could not start ovn-trace: {exc}"}, status_code=502)
        except RuntimeError as exc:
            log.error("%s", exc)
            return JSONResponse({"error": str(exc)}, status_code=502)
        result = {"returncode": returncode, "output": output}
        if returncode:
            return JSONResponse({"error": f"ovn-trace exited with status {returncode}", **result},
                                status_code=422)
        return JSONResponse(result)

    # kept for backward compatibility with the previous version
    @app.get("/version")
    def version() -> dict:
        return {"version": state.version}

    return app
