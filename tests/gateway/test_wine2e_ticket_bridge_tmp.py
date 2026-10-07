"""TEMPORARY (wine2e/106742 only, never merges): the Desktop Python ticket bridge on a live daemon.

apps/desktop/electron/local-gateway-python.test.ts skips on win32, so this drives the SAME
TICKET_SCRIPT (read out of local-gateway-python.ts) the way Electron spawns it: `python -P -c`,
JSON request on stdin, HERMES_HOME forced to the endpoint, against an ordinary gateway.run whose
control channel is the private named pipe on Windows (AF_UNIX elsewhere).
"""
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from websockets.asyncio.client import connect

from tests.gateway.test_unified_gateway_native_live import ROOT, daemon, harness, peer, planned_stop  # noqa: F401

SCRIPT = re.search(r"const TICKET_SCRIPT = `(.*?)`", (ROOT / "apps/desktop/electron/local-gateway-python.ts")
                   .read_text(encoding="utf-8"), re.S).group(1)


def _mint(env, cwd, endpoint, purpose):
    child_env = {**env, "HERMES_HOME": endpoint["profile_id"], "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run([sys.executable, "-P", "-c", SCRIPT], cwd=cwd, env=child_env,
                          input=json.dumps({"endpoint": endpoint, "purpose": purpose}).encode(),
                          capture_output=True, timeout=60)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def test_desktop_python_ticket_bridge_live(harness):  # noqa: F811
    home, env = harness["home"], harness["env"]
    work = harness["work"]
    # A project-local decoy must not shadow hermes_cli (-P keeps cwd off sys.path).
    (work / "hermes_cli").mkdir()
    (work / "hermes_cli" / "__init__.py").write_text("", encoding="utf-8")
    (work / "hermes_cli" / "gateway_client.py").write_text(
        "def _session_ticket(*a, **k):\n    return 'untrusted-project-ticket'\n", encoding="utf-8")
    with daemon(home, env, "bridge.log") as (owner, desc, _):
        served = desc["served_profiles"][0]["profile_id"]
        endpoint = {"profile_id": served, "instance_id": desc["instance_id"], "runtime_protocol": 1,
                    "control_home": None}
        tickets = {}
        for purpose in ("interactive", "native-http"):
            rc, out, err = _mint(env, work, endpoint, purpose)
            assert rc == 0, (purpose, out, err, endpoint, str(Path(served).resolve()))
            tickets[purpose] = json.loads(out)["ticket"]
            assert tickets[purpose] and tickets[purpose] != "untrusted-project-ticket"
        rc, out, err = _mint(env, work, {**endpoint, "instance_id": "someone-else"}, "interactive")
        assert rc != 0 and "ticket" not in out, (out, err)

        async def attach():
            url = desc["api_origin"].replace("http:", "ws:") + "/api/ws"
            async with connect(url, subprotocols=["hermes-gateway-v1", "hermes-gateway-ticket." + tickets["interactive"]],
                               open_timeout=20) as ws:
                assert ws.subprotocol == "hermes-gateway-v1"
        asyncio.run(attach())
        assert planned_stop(home, owner, desc) == 0
    print(json.dumps({"os": sys.platform, "minted": sorted(tickets), "pipe": os.name == "nt"}))
