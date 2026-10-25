"""Run a Python script inside a running 3D Slicer through its Web Server "exec" endpoint.

Usage (from the repository root)::

    python scripts/testing_data/run_in_slicer.py generate_test_data.py --revision rev001
    python scripts/testing_data/run_in_slicer.py check_test_data_in_slicer.py --manifest .testing_data/manifest_rev001.json

Slicer must be running with the Web Server module's "Slicer API exec" endpoint enabled, for example::

    Slicer.exe --python-code "from WebServer import WebServerLogic; wsLogic = WebServerLogic(port=2016, enableExec=True); wsLogic.start()"

If no server is found and ``--slicer`` (or the ``SLICER_EXECUTABLE`` environment variable) is given, Slicer is
started automatically with that command line. Everything after the script name is passed to the script as
``sys.argv`` inside Slicer. The script's ``__execResult`` (if any) is printed as JSON; stdout of the script appears
in the Slicer Python console / log, so scripts should collect what they want to report into ``__execResult``.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

DEFAULT_PORT = 2016


def server_url(port):
    return f"http://127.0.0.1:{port}"


def is_server_running(port, timeout_sec=3):
    try:
        response = requests.get(f"{server_url(port)}/slicer/system/version", timeout=timeout_sec)
        return "applicationName" in response.json()
    except Exception:
        return False


def start_slicer(slicer_executable, port, timeout_sec=120):
    env = dict(os.environ)
    env["DASHBOARD_TEST_FROM_CTEST"] = "1"  # suppress memory-leak popup on exit
    python_code = (
        "from WebServer import WebServerLogic; "
        f"wsLogic = WebServerLogic(port={port}, enableExec=True); wsLogic.start()"
    )
    process = subprocess.Popen([slicer_executable, "--python-code", python_code], env=env)
    start = time.time()
    while not is_server_running(port):
        if time.time() - start > timeout_sec:
            raise TimeoutError(f"Slicer did not start a web server on port {port} within {timeout_sec} s")
        time.sleep(1.0)
    return process


def exec_in_slicer(code, port, timeout_sec=3600):
    response = requests.post(f"{server_url(port)}/slicer/exec", data=code.encode("utf-8"), timeout=timeout_sec)
    if not response.ok:
        raise RuntimeError(f"Slicer exec failed ({response.status_code}): {response.text[:2000]}")
    try:
        return response.json()
    except ValueError:
        return response.text


def run_script(script_path, script_args, port):
    script_path = Path(script_path).resolve()
    # Run the file in a fresh namespace inside Slicer, with sys.argv set as if it was executed as a program.
    # __execResult is picked up by the exec handler and returned as JSON.
    bootstrap = f"""
import sys, runpy, json, traceback
_argv_backup = sys.argv
sys.argv = {json.dumps([str(script_path)] + list(script_args))}
try:
    _ns = runpy.run_path({json.dumps(str(script_path))}, run_name="__main__")
    __execResult = _ns.get("__execResult", {{"status": "ok"}})
except SystemExit as e:
    __execResult = {{"status": "exit", "code": e.code}}
except Exception:
    __execResult = {{"status": "error", "traceback": traceback.format_exc()}}
finally:
    sys.argv = _argv_backup
"""
    return exec_in_slicer(bootstrap, port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("script", help="Python script to run inside Slicer (path relative to this directory or absolute)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Slicer web server port (default 2016)")
    parser.add_argument("--slicer", default=os.environ.get("SLICER_EXECUTABLE"),
                        help="Slicer executable to start if no server is running (default: SLICER_EXECUTABLE env var)")
    parser.add_argument("script_args", nargs=argparse.REMAINDER, help="arguments passed to the script")
    args = parser.parse_args(argv)

    script_path = Path(args.script)
    if not script_path.is_absolute() and not script_path.exists():
        script_path = Path(__file__).parent / script_path
    if not script_path.exists():
        parser.error(f"script not found: {script_path}")

    if not is_server_running(args.port):
        if not args.slicer:
            parser.error(f"No Slicer web server on port {args.port}. Start Slicer with the exec endpoint enabled "
                         "or pass --slicer / set SLICER_EXECUTABLE.")
        print(f"Starting {args.slicer} ...", file=sys.stderr)
        start_slicer(args.slicer, args.port)

    result = run_script(script_path, args.script_args, args.port)
    print(json.dumps(result, indent=2, default=str))
    if isinstance(result, dict) and result.get("status") in ("error", "exit") and result.get("code", 1) not in (0, None):
        return 1
    if isinstance(result, dict) and result.get("status") == "error":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
