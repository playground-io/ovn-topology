"""OVN trace process execution."""
import asyncio

from .config import Config


async def run_ovn_trace(cfg: Config, datapath: str, microflow: str) -> tuple[int, str]:
    """Run a summary trace with user values passed as positional arguments, never shell text."""
    cmd = ["docker", "exec", cfg.container, "ovn-trace"] if cfg.container else ["ovn-trace"]
    if cfg.nb_db:
        cmd.append(f"--db={cfg.nb_db}")
    cmd.extend(["--summary", datapath, microflow])

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError("ovn-trace timed out after 30 seconds")

    output = out.decode(errors="replace")
    stderr = err.decode(errors="replace")
    if stderr:
        output += ("\n" if output and not output.endswith("\n") else "") + stderr
    if proc.returncode is None:
        raise RuntimeError("ovn-trace finished without an exit status")
    return proc.returncode, output
