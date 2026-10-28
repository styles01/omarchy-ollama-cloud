#!/usr/bin/env python3
# omarchy:args=[--force] [--meter-url <url>]
"""Print or write the Ollama Cloud usage record as JSON.

The single source of Ollama Cloud usage is the ollama-meter companion
service on the mini (port 8615), whose /api/summary endpoint exposes
session/weekly used percent and reset times. ollama.com itself is never
polled here — the meter is the only poller (ollama.com rate-limits
10 req/min shared across the household).

Meter discovery, in order:
  1. --meter-url / $OLLAMA_METER_URL (explicit wins)
  2. the last URL that produced a good summary (cached in the state dir)
  3. the meter's UDP beacon on port 8616 ("OLLAMA-METER <ip> <port>")
  4. mDNS name ollama-meter.local (:8615)

If the meter cannot be reached, the last good record is kept (a transient
outage must not blank the panel chip); with no prior record the collector
emits an empty record so the panel shows "--" instead of crashing.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AGENT_ID = "ollama"
AGENT_NAME = "Ollama Cloud"
METER_HTTP_PORT = 8615
MDNS_NAME = "ollama-meter.local"
BEACON_PORT = 8616
HTTP_TIMEOUT = 5.0
MDNS_TIMEOUT = 4.0

STATS_KEYS = (
    "todayPrompts",
    "todaySessions",
    "todayTotalTokens",
    "todayTokensByModel",
    "recentDays",
    "totalPrompts",
    "totalSessions",
    "activeDays",
)

TOKEN_KEYS = ("todayTokensByModel", "modelUsage")


def state_dir() -> Path:
  root = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
  return Path(root) / "omarchy" / "agents" / "usage"


def usage_record_path() -> Path:
  return state_dir() / f"{AGENT_ID}.json"


def meter_cache_path() -> Path:
  return state_dir() / "ollama-meter-url"


def empty_result(**overrides) -> dict:
  out: dict = {
    "schemaVersion": 1,
    "id": AGENT_ID,
    "name": AGENT_NAME,
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "ready": False,
    "hasLocalStats": False,
    "hasPromptStats": True,
    # ollama.com numbers are account-global, so synced machines must not sum them.
    "scope": "account",
    "tierLabel": "",
    "usageStatusText": "",
    "authHelpText": "",
    "limits": [],
    "balance": {},
    "modelRequests": {},
  }
  for key in STATS_KEYS:
    out[key] = 0
  for key in TOKEN_KEYS:
    out[key] = {} if "ByModel" in key else []
  out["recentDays"] = []
  out["activeDates"] = []
  out.update(overrides)
  return out


# ---------------------------------------------------------------- meter fetch

def fetch_json(url: str, timeout: float = HTTP_TIMEOUT) -> dict:
  with urllib.request.urlopen(url, timeout=timeout) as resp:
    return json.loads(resp.read().decode("utf-8"))


def summary_from_url(url: str) -> dict:
  """GET {url}/api/summary and return it if the payload is a real meter."""
  base = url.rstrip("/")
  data = fetch_json(f"{base}/api/summary")
  if not isinstance(data, dict) or not isinstance(data.get("cloud"), dict):
    raise TypeError(f"{base}: not an ollama-meter summary (no 'cloud' object)")
  return data["cloud"]


def beacon_discovery() -> str | None:
  """Listen briefly for 'OLLAMA-METER <ip> <port>' on UDP :8616."""
  sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
  if hasattr(socket, "SO_REUSEPORT"):
    try:
      sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except OSError:
      pass
  sock.settimeout(MDNS_TIMEOUT)
  try:
    sock.bind(("", BEACON_PORT))
  except OSError:
    return None
  try:
    parts = sock.recvfrom(256)[0].decode("utf-8", "replace").split()
    if len(parts) >= 3 and parts[0] == "OLLAMA-METER":
      ip, port = parts[1], parts[2]
      if port.isdigit():
        return f"http://{ip}:{port}"
  except OSError:
    pass
  finally:
    sock.close()
  return None


def mdns_discovery() -> str | None:
  try:
    infos = socket.getaddrinfo(MDNS_NAME, METER_HTTP_PORT, type=socket.SOCK_STREAM)
  except OSError:
    return None
  if infos:
    host = infos[0][4][0]
    return f"http://{host}:{METER_HTTP_PORT}"
  return None


def resolve_meter(explicit: str | None) -> tuple[str, dict]:
  """Return (base_url, cloud_summary); persist a good URL for next time."""
  candidates: list[str] = []
  if explicit:
    candidates.append(explicit.rstrip("/"))
  cached = ""
  try:
    cached = meter_cache_path().read_text().strip()
  except OSError:
    pass
  if cached.startswith("http"):
    candidates.append(cached.rstrip("/"))
  for url in beacon_discovery(), mdns_discovery():
    if url:
      candidates.append(url)

  errors = []
  tried = set()
  for url in candidates:
    if url in tried:
      continue
    tried.add(url)
    try:
      cloud = summary_from_url(url)
      try:
        meter_cache_path().write_text(url + "\n")
      except OSError:
        pass
      return url, cloud
    except Exception as exc:
      errors.append(f"{url}: {exc}")
  raise RuntimeError("; ".join(errors) or "no meter candidates available")


# ---------------------------------------------------------------- record build

def local_iso(utc_text: str) -> str:
  """'2026-11-02T00:00:00Z' -> local-time ISO with seconds (panel format)."""
  text = (utc_text or "").strip()
  if not text:
    return ""
  try:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
  except ValueError:
    return ""
  if dt.tzinfo is None:
    dt = dt.replace(tzinfo=timezone.utc)
  return dt.astimezone().isoformat(timespec="seconds")


def build_record(cloud: dict) -> dict:
  tier = str(cloud.get("plan") or "").strip()
  tier = tier[:1].upper() + tier[1:] if tier else ""

  limits = []
  if cloud.get("session_pct") is not None and str(cloud.get("session_reset_at") or "").strip():
    limits.append({
      "label": "Session (5-hour)",
      # Panel expects percent as a 0-1 fraction
      "percent": round(float(cloud["session_pct"]) / 100.0, 4),
      "resetsAt": local_iso(str(cloud.get("session_reset_at") or "")),
      "title": "Session",
    })
  if cloud.get("weekly_pct") is not None and str(cloud.get("weekly_reset_at") or "").strip():
    limits.append({
      "label": "Weekly",
      "percent": round(float(cloud["weekly_pct"]) / 100.0, 4),
      "resetsAt": local_iso(str(cloud.get("weekly_reset_at") or "")),
      "title": "Weekly",
    })

  balance: dict = {"remaining": 0, "funded": 0, "spent": 0, "currency": "USD", "estimated": False}
  if cloud.get("purchased_balance_usd") is not None:
    balance["remaining"] = float(cloud["purchased_balance_usd"])

  model_requests: dict = {}
  top_models = cloud.get("top_models")
  if isinstance(top_models, list):
    for entry in top_models:
      if isinstance(entry, dict):
        model = str(entry.get("model") or "")
        requests = entry.get("requests")
        if model and isinstance(requests, int):
          model_requests[model] = requests

  return empty_result(
    ready=bool(cloud.get("available", True)),
    tierLabel=tier,
    limits=limits,
    balance=balance,
    modelRequests=model_requests,
  )


def collect_record(explicit_url: str | None) -> dict:
  url, cloud = resolve_meter(explicit_url)
  record = build_record(cloud)
  if not record["ready"]:
    raise RuntimeError(f"{url}: meter says cloud usage unavailable")
  if not record["limits"]:
    raise RuntimeError(f"{url}: summary has no usable session/weekly percentages")
  return record


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Print the Ollama Cloud usage record as JSON")
  # --force / --limits-only exist so every collector accepts the same invocation.
  parser.add_argument("--force", action="store_true")
  parser.add_argument("--limits-only", action="store_true")
  parser.add_argument("--write", action="store_true", help="write ~/.local/state/omarchy/agents/usage/ollama.json")
  parser.add_argument("--clear", action="store_true", help="remove ollama.json so the agents panel drops the Ollama Cloud provider")
  parser.add_argument(
    "--meter-url",
    default=os.environ.get("OLLAMA_METER_URL", ""),
    help="Base URL of the ollama-meter (default: auto-discover via cache, UDP beacon on :8616, or ollama-meter.local)",
  )
  args = parser.parse_args(argv)

  if args.clear:
    usage_record_path().unlink(missing_ok=True)
    meter_cache_path().unlink(missing_ok=True)
    return 0

  try:
    record = collect_record(args.meter_url or None)
  except (RuntimeError, OSError, ValueError) as exc:
    print(f"ollama-cloud-usage: {exc}", file=sys.stderr)
    if usage_record_path().exists():
      # Keep the last good record; a transient failure (meter down, network)
      # should not blank the panel chip.
      return 0
    record = empty_result(
      usageStatusText="Ollama Cloud usage unavailable",
      authHelpText="Check that the ollama-meter service on the mini is running, then refresh.",
    )

  if args.write:
    state_dir().mkdir(parents=True, exist_ok=True)
    target = usage_record_path()
    tmp = target.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n")
    os.replace(tmp, target)
    print(f"ollama-cloud-usage: wrote {target}")
  else:
    print(json.dumps(record, separators=(",", ":"), sort_keys=True))
  return 0


if __name__ == "__main__":
  sys.exit(main())