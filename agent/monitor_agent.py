#!/usr/bin/env python3
"""
Letsma Endpoint Monitoring Agent
================================
A lightweight, dependency-minimal agent that runs on managed Windows, macOS,
or Linux devices and reports health metrics back to the Letsma MSP Platform.

Requirements:
    pip install psutil requests

First-time setup (registers the device once, saves its endpoint_id locally):
    python monitor_agent.py --register --customer-id <CUSTOMER_ID> --server https://msp.letsma.co.uk

Recurring heartbeat (schedule this to run every 5 minutes):
    python monitor_agent.py --heartbeat --server https://msp.letsma.co.uk

Deployment:
  - Windows: create a Scheduled Task that runs this script every 5 minutes
    (Task Scheduler > Create Task > Trigger: Repeat every 5 minutes indefinitely).
  - Linux/macOS: add a systemd timer or cron entry, e.g.:
        */5 * * * * /usr/bin/python3 /opt/letsma-agent/monitor_agent.py --heartbeat --server https://msp.letsma.co.uk
"""
import argparse
import json
import os
import platform
import socket
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    print("This agent requires psutil. Install it with: pip install psutil", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("This agent requires requests. Install it with: pip install requests", file=sys.stderr)
    sys.exit(1)

STATE_FILE = Path(__file__).parent / "agent_state.json"
AGENT_VERSION = "1.0.0"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def check_disk_health() -> bool:
    """Best-effort disk health check. On Windows, uses WMIC/PowerShell SMART status;
    elsewhere assumes healthy unless disk usage indicates near-full (handled separately)."""
    try:
        if platform.system() == "Windows":
            import subprocess
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-PhysicalDisk | Select-Object -ExpandProperty HealthStatus) -join ','"],
                capture_output=True, text=True, timeout=10,
            )
            statuses = result.stdout.strip()
            return "Healthy" in statuses or statuses == ""
    except Exception:
        pass
    return True


def check_av_enabled() -> bool | None:
    """Best-effort AV status check (Windows Defender). Returns None if undetermined."""
    try:
        if platform.system() == "Windows":
            import subprocess
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-MpComputerStatus).RealTimeProtectionEnabled"],
                capture_output=True, text=True, timeout=10,
            )
            out = result.stdout.strip().lower()
            if out in ("true", "false"):
                return out == "true"
    except Exception:
        pass
    return None


def check_pending_reboot() -> bool:
    try:
        if platform.system() == "Windows":
            import winreg
            try:
                winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
                )
                return True
            except FileNotFoundError:
                return False
    except Exception:
        pass
    return False


def register(server: str, customer_id: str, api_key: str):
    hostname = socket.gethostname()
    payload = {
        "customer_id": customer_id,
        "hostname": hostname,
        "os_name": platform.system(),
        "os_version": platform.version(),
        "agent_version": AGENT_VERSION,
        "ip_address": get_local_ip(),
    }
    resp = requests.post(
        f"{server}/api/endpoints/register",
        json=payload,
        headers={"X-Agent-Key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    save_state({"endpoint_id": data["id"], "customer_id": customer_id, "server": server})
    print(f"Registered successfully. endpoint_id={data['id']}")


def heartbeat(server: str, api_key: str):
    state = load_state()
    if "endpoint_id" not in state:
        print("Not registered yet. Run with --register first.", file=sys.stderr)
        sys.exit(1)

    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent if platform.system() != "Windows" else psutil.disk_usage("C:\\").percent
    uptime = int(time.time() - psutil.boot_time())

    payload = {
        "endpoint_id": state["endpoint_id"],
        "cpu_percent": cpu,
        "memory_percent": mem,
        "disk_percent": disk,
        "uptime_seconds": uptime,
        "disk_health_ok": check_disk_health(),
        "av_enabled": check_av_enabled(),
        "pending_reboot": check_pending_reboot(),
        "ip_address": get_local_ip(),
    }

    resp = requests.post(
        f"{server or state.get('server')}/api/endpoints/heartbeat",
        json=payload,
        headers={"X-Agent-Key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()
    if result.get("alerts"):
        print("ALERTS:", "; ".join(result["alerts"]))
    else:
        print("Heartbeat OK.")


def main():
    parser = argparse.ArgumentParser(description="Letsma Endpoint Monitoring Agent")
    parser.add_argument("--register", action="store_true", help="Register this device with the platform")
    parser.add_argument("--heartbeat", action="store_true", help="Send a health heartbeat")
    parser.add_argument("--server", default=os.getenv("LETSMA_SERVER", ""), help="Base URL of the Letsma MSP platform")
    parser.add_argument("--customer-id", default="", help="Customer ID to register this device under")
    parser.add_argument("--api-key", default=os.getenv("LETSMA_AGENT_API_KEY", "letsma-agent-shared-key"))
    args = parser.parse_args()

    if not args.server:
        print("Provide --server or set LETSMA_SERVER environment variable.", file=sys.stderr)
        sys.exit(1)

    if args.register:
        if not args.customer_id:
            print("--customer-id is required for registration.", file=sys.stderr)
            sys.exit(1)
        register(args.server, args.customer_id, args.api_key)
    elif args.heartbeat:
        heartbeat(args.server, args.api_key)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
