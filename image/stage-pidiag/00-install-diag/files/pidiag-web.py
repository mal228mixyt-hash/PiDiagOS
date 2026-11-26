#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PiDiagOS web panel: the primary interface for operating the board.

Port 80. Displays status, starts diagnostics, serves reports, and provides a link to the display.
Demo mode (--demo) for virtual machines uses a sample report instead of real hardware.
"""

import argparse
import base64
import glob
import hashlib
import hmac
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

RESULTS_DIR = "/boot/firmware/diag_results"
RUNNER = "/usr/local/bin/rpi-diag-runner.py"
AP_CHECK = "/usr/local/bin/pidiag-ap-check.py"
AP_STATE = "/run/pidiag-ap-state.json"
WEB_TITLE = "PiDiagOS"

STATE = {"running": False, "mode": None, "started": 0.0}
STATE_LOCK = threading.Lock()
DEMO = False
DEMO_TEMPLATE = "/opt/pidiag/report_template.html"
WEB_USER_FILE = "/etc/pidiag/web-user"
WEB_PASSWORD_FILE = "/etc/pidiag/web-password"


def _read_first_line(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.readline().strip() or default
    except OSError:
        return default


def _password_hash():
    return _read_first_line(WEB_PASSWORD_FILE)


def web_user():
    return _read_first_line(WEB_USER_FILE, "Admin")


def authorized(handler):
    header = handler.headers.get("Authorization", "")
    stored = _password_hash()
    if not header.startswith("Basic ") or not stored:
        return False
    try:
        raw = base64.b64decode(header[6:]).decode("utf-8")
        user, password = raw.split(":", 1)
        algo, cost, salt_hex, hash_hex = stored.split("$", 3)
        if algo != "scrypt" or not hmac.compare_digest(user, web_user()):
            return False
        digest = hashlib.scrypt(password.encode("utf-8"),
                                salt=bytes.fromhex(salt_hex),
                                n=int(cost), r=8, p=1, dklen=32)
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, OSError, UnicodeError):
        return False


def esc(value):
    return html.escape("—" if value is None else str(value))


def run(cmd, timeout=10):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res.returncode, res.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def host_info():
    rc, ip = run(["hostname", "-I"])
    ip = ip.split()[0] if rc == 0 and ip else ""
    rc, ssid = run(["iwgetid", "-r"])
    if rc != 0 or not ssid:
        rc, ssid = run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
        for line in ssid.splitlines():
            if line.startswith("yes:"):
                ssid = line.split(":", 1)[1]
                break
        else:
            ssid = ""
    return {
        "host": os.uname().nodename,
        "ip": ip,
        "ssid": ssid,
        "demo": DEMO,
    }


def report_files():
    out = []
    for path in glob.glob(os.path.join(RESULTS_DIR, "*.json")):
        try:
            out.append((os.path.getmtime(path), path))
        except OSError:
            pass
    out.sort(reverse=True)
    return out


def latest_report():
    files = report_files()
    if not files:
        return None
    _, path = files[0]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    decoded = data.get("identity", {}).get("decoded", {})
    stress = data.get("stress", {})
    power = data.get("power", {})
    return {
        "name": os.path.basename(path),
        "json": os.path.basename(path),
        "html": os.path.basename(path)[:-5] + ".html",
        "status": data.get("overall_status", "?"),
        "timestamp": data.get("timestamp", ""),
        "board": data.get("identity", {}).get("model_dt") or decoded.get("board_type") or "—",
        "ram": decoded.get("detected_ram_mb"),
        "peak_temp": stress.get("peak_temp_c"),
        "throttled": power.get("throttled_hex"),
        "stress_status": stress.get("status"),
    }


def net_state():
    """Access point state written by pidiag-ap-check.py."""
    try:
        with open(AP_STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def history(limit=10):
    items = []
    for _, path in report_files()[:limit]:
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        items.append({
            "json": name,
            "html": name[:-5] + ".html",
            "status": data.get("overall_status", "?"),
            "timestamp": data.get("timestamp", ""),
        })
    return items


def demo_write_report():
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    os.makedirs(RESULTS_DIR, exist_ok=True)
    if os.path.exists(DEMO_TEMPLATE):
        with open(DEMO_TEMPLATE, encoding="utf-8") as src:
            page = src.read().replace("%TS%", stamp)
    else:
        # Demo mode also works without a template: build the page inline
        page = ("<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
                "<title>PiDiagOS demo</title></head><body>"
                "<h1>PASS — Raspberry Pi 3 Model B Rev 1.2</h1>"
                "<p>Demo report (%s). No hardware checks were performed.</p>"
                "</body></html>" % html.escape(stamp))
    name = "PASS_Pi_3B_demo_%s" % datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(RESULTS_DIR, name + ".html"), "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.join(RESULTS_DIR, name + ".json"), "w", encoding="utf-8") as f:
        json.dump({
            "tool": "PiDiagOS", "timestamp": stamp, "overall_status": "PASS",
            "identity": {"status": "PASS", "model_dt": "Raspberry Pi 3 Model B Rev 1.2",
                         "decoded": {"board_type": "Pi 3B", "detected_ram_mb": 1024}},
            "power": {"status": "PASS", "throttled_hex": "0x0"},
            "stress": {"status": "PASS", "peak_temp_c": 71.6},
            "gpio": {"status": "PASS", "tested_pins_count": 17, "failed_pins": []},
        }, f, ensure_ascii=False, indent=2)


def start_run(full):
    if DEMO:
        with STATE_LOCK:
            if STATE["running"]:
                return False
            STATE.update(running=True, mode="demo", started=time.time())

        def demo_worker():
            time.sleep(4)
            demo_write_report()
            with STATE_LOCK:
                STATE["running"] = False
        threading.Thread(target=demo_worker, daemon=True).start()
        return True

    with STATE_LOCK:
        if STATE["running"]:
            return False
        STATE.update(running=True, mode="full" if full else "quick", started=time.time())

    def worker():
        cmd = [sys.executable, RUNNER]
        cmd += ["--stress-seconds", "60"] if full else ["--skip-stress"]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=900)
        finally:
            with STATE_LOCK:
                STATE["running"] = False
    threading.Thread(target=worker, daemon=True).start()
    return True


PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --text:#12161c; --muted:#5b6572;
         --pass:#188038; --fail:#c5221f; --accent:#1a73e8; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
        font:16px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }}
.wrap {{ max-width:900px; margin:0 auto; padding:20px 16px 48px; }}
header {{ display:flex; align-items:center; gap:12px; margin-bottom:18px; flex-wrap:wrap; }}
h1 {{ font-size:24px; margin:0; }}
.badge {{ display:inline-block; padding:4px 12px; border-radius:999px; color:#fff;
          font-weight:700; font-size:14px; }}
.pass {{ background:var(--pass); }} .fail {{ background:var(--fail); }}
.unknown {{ background:#7a8794; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
         padding:18px 20px; margin-bottom:16px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; }}
.metric {{ background:#fbfcfd; border:1px solid var(--line); border-radius:10px; padding:10px 12px; }}
.metric .k {{ color:var(--muted); font-size:13px; }}
.metric .v {{ font-size:18px; font-weight:600; }}
button, a.btn {{ display:inline-block; border:0; border-radius:10px; padding:14px 18px;
                 font-size:16px; font-weight:600; cursor:pointer; text-decoration:none;
                 color:#fff; background:var(--accent); }}
a.btn.green {{ background:var(--pass); }}
a.btn.grey {{ background:#5f6b7a; }}
a.btn.ghost {{ background:#eef1f5; color:#1a2632; }}
button:disabled, a.btn.disabled {{ opacity:.5; pointer-events:none; }}
.row {{ display:flex; gap:10px; flex-wrap:wrap; }}
table {{ width:100%; border-collapse:collapse; font-size:15px; }}
th, td {{ text-align:left; padding:8px 6px; border-bottom:1px solid var(--line); }}
th {{ color:var(--muted); font-weight:600; }}
iframe {{ width:100%; height:520px; border:1px solid var(--line); border-radius:10px; background:#fff; }}
.note {{ color:var(--muted); font-size:14px; }}
.progress {{ display:flex; align-items:center; gap:10px; color:var(--muted); }}
.spinner {{ width:18px; height:18px; border:3px solid #d4d9e0; border-top-color:var(--accent);
            border-radius:50%; animation:spin 1s linear infinite; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
</style></head><body><div class="wrap">
<header>
  <h1>{title}</h1>
  {badge}
</header>

<div class="card" id="status">
  <div class="row">
    <a class="btn" href="/api/run?mode=quick" onclick="return runTest(this)">Quick Check</a>
    <a class="btn green" href="/api/run?mode=full" onclick="return runTest(this)">Full Test (60s stress test)</a>
    <a class="btn grey" href="/report/">Open Report</a>
  </div>
  <div id="runline" style="margin-top:14px; display:{run_display}">
    <div class="progress"><span class="spinner"></span><span id="runtext">Running diagnostics…</span></div>
  </div>
  <div class="note" style="margin-top:12px">
    Quick Check — power, revision, RAM, GPIO, and peripherals (a few seconds).
    Full Test also loads all CPU cores for 60 seconds and checks for throttling.
  </div>
</div>

<div class="card">
  <div class="grid">
    <div class="metric"><div class="k">Board</div><div class="v">{board}</div></div>
    <div class="metric"><div class="k">RAM</div><div class="v">{ram} MB</div></div>
    <div class="metric"><div class="k">Peak temperature</div><div class="v">{temp} °C</div></div>
    <div class="metric"><div class="k">get_throttled</div><div class="v">{throttled}</div></div>
  </div>
  <div class="note" style="margin-top:12px">
    Wi-Fi: <b>{ssid}</b> · IP: <b>{ip}</b> · host: {host} · latest report: {last_time}
  </div>
</div>

<div class="card">
  <h3 style="margin-top:0">Network</h3>
  <div class="grid">
    <div class="metric"><div class="k">Access point</div><div class="v">{ap_ssid}</div></div>
    <div class="metric"><div class="k">State</div><div class="v">{ap_state}</div></div>
    <div class="metric"><div class="k">Board IP</div><div class="v">{ap_ip}</div></div>
    <div class="metric"><div class="k">Connected devices</div><div class="v">{ap_clients}</div></div>
  </div>
  {clients_table}
  <div class="row" style="margin-top:14px">
    <a class="btn ghost" href="/api/netcheck" onclick="return netCheck(this)">Check Wi-Fi</a>
  </div>
  <div class="note" style="margin-top:10px">
    The check runs at startup and once per minute. If the access point is down,
    the system will try to bring it back up.
  </div>
</div>

<div class="card">
  <h3 style="margin-top:0">Latest Report</h3>
  {report_block}
</div>

<div class="card">
  <h3 style="margin-top:0">Check History</h3>
  {history_block}
</div>

<div class="card">
  <h3 style="margin-top:0">SSH Access</h3>
  <p class="note">User <b>{login}</b>; password set when the image was built.
  Connect with: <code>ssh {login}@{ip}</code></p>
</div>
</div>
<script>
function runTest(link) {{
  link.classList.add('disabled');
  document.getElementById('runline').style.display = 'block';
  fetch(link.href).then(() => setTimeout(check, 1000));
  return false;
}}
function netCheck(link) {{
  link.classList.add('disabled');
  fetch(link.href).then(() => setTimeout(() => location.reload(), 14000));
  return false;
}}
let wasRunning = {run_js};
function check() {{
  fetch('/api/status').then(r => r.json()).then(s => {{
    const line = document.getElementById('runline');
    line.style.display = s.running ? 'block' : 'none';
    if (s.running) {{ wasRunning = true; setTimeout(check, 1500); }}
    else if (wasRunning) location.reload();
  }});
}}
if (wasRunning) setTimeout(check, 1000);
</script>
</body></html>
"""


def render_index():
    info = host_info()
    last = latest_report()
    with STATE_LOCK:
        running = STATE["running"]
        mode = STATE["mode"]

    badge = '<span class="badge unknown">No reports yet</span>'
    if last:
        cls = "pass" if last["status"] == "PASS" else ("fail" if last["status"] == "FAIL" else "unknown")
        badge = '<span class="badge %s">%s</span>' % (cls, esc(last["status"]))

    if last:
        html_name = "/report/" + last["html"]
        block = ('<div class="row" style="margin-bottom:12px">'
                 '<a class="btn ghost" href="%s" target="_blank">Open in new tab</a>'
                 '<a class="btn ghost" href="/report/%s" download>Download JSON</a>'
                 '</div><iframe src="%s" title="Report"></iframe>'
                 % (html_name, esc(last["json"]), html_name))
        last_time = esc(last["timestamp"])
    else:
        block = '<p class="note">No reports yet. Run a check to get started.</p>'
        last_time = "—"

    items = history()
    if items:
        rows = "".join(
            '<tr><td><span class="badge %s">%s</span></td><td>%s</td>'
            '<td><a href="/report/%s" target="_blank">Open</a> · '
            '<a href="/report/%s" download>JSON</a></td></tr>'
            % ("pass" if i["status"] == "PASS" else "fail", esc(i["status"]),
               esc(i["timestamp"]), esc(i["html"]), esc(i["json"]))
            for i in items)
        history_block = ("<table><tr><th>Result</th><th>Date</th><th>Files</th></tr>"
                         + rows + "</table>")
    else:
        history_block = '<p class="note">No history yet.</p>'

    net = net_state()
    clients = net.get("clients") or []
    if clients:
        rows = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (esc(c.get("ip")), esc(c.get("mac")), esc(c.get("name") or "—"))
            for c in clients)
        clients_table = "<table><tr><th>IP</th><th>MAC</th><th>Name</th></tr>%s</table>" % rows
    else:
        clients_table = '<p class="note">No devices connected.</p>'

    if DEMO:
        ap_state = "Demo (Wi-Fi unavailable)"
    elif not net:
        ap_state = "No data"
    elif net.get("ok"):
        ap_state = "Online"
    else:
        ap_state = net.get("note") or "Offline"

    return PAGE.format(
        title=WEB_TITLE,
        badge=badge,
        login=esc(web_user()),
        board=esc(last["board"] if last else "—"),
        ram=esc(last["ram"] if last and last["ram"] is not None else "—"),
        temp=esc(last["peak_temp"] if last and last["peak_temp"] is not None else "—"),
        throttled=esc(last["throttled"] if last else "—"),
        ssid=esc(info["ssid"] or ("demo" if info["demo"] else "—")),
        ip=esc(info["ip"] or "—"),
        host=esc(info["host"]),
        last_time=last_time,
        run_display="block" if running else "none",
        run_js="true" if running else "false",
        ap_ssid=esc(net.get("ssid") or "—"),
        ap_state=esc(ap_state),
        ap_ip=esc(net.get("ip") or "—"),
        ap_clients=len(clients),
        clients_table=clients_table,
        report_block=block,
        history_block=history_block,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "PiDiagOS"

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not authorized(self):
            return self._send(401, "Authentication required", extra={"WWW-Authenticate": 'Basic realm="PiDiagOS"'})
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            return self._send(200, render_index())

        if path == "/api/status":
            with STATE_LOCK:
                running = STATE["running"]
                mode = STATE["mode"]
                started = STATE["started"]
            last = latest_report()
            return self._send(200, json.dumps({
                "running": running,
                "mode": mode,
                "elapsed": round(time.time() - started) if running else 0,
                "report": last,
            }), "application/json")

        if path == "/api/run":
            mode = (query.get("mode") or ["quick"])[0]
            ok = start_run(mode == "full")
            if not ok:
                return self._send(409, "A check is already running")
            return self._send(303, "", extra={"Location": "/"})

        if path == "/api/net":
            return self._send(200, json.dumps(net_state(), ensure_ascii=False),
                              "application/json")

        if path == "/api/netcheck":
            run([AP_CHECK], timeout=180)
            return self._send(303, "", extra={"Location": "/"})

        if path == "/report" or path == "/report/":
            index = os.path.join(RESULTS_DIR, "index.html")
            if os.path.exists(index):
                return self._serve_file(index)
            last = latest_report()
            if last:
                return self._serve_file(os.path.join(RESULTS_DIR, last["html"]))
            return self._send(404, "No reports yet")

        if path.startswith("/report/"):
            name = os.path.basename(path)
            if not re.fullmatch(r"[A-Za-z0-9_.-]+\.(html|json)", name):
                return self._send(403, "Forbidden")
            target = os.path.join(RESULTS_DIR, name)
            if os.path.exists(target):
                return self._serve_file(target)
            return self._send(404, "Report not found")

        return self._send(404, "Not found")

    def _serve_file(self, path):
        ctype = "application/json" if path.endswith(".json") else "text/html; charset=utf-8"
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self._send(404, "File not found")
        return self._send(200, body, ctype)

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] %s\n" % (fmt % args))


def main():
    global DEMO, RESULTS_DIR
    parser = argparse.ArgumentParser(description="PiDiagOS web panel")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--results", default=RESULTS_DIR, help="reports directory")
    parser.add_argument("--demo", action="store_true", help="demo mode without hardware")
    args = parser.parse_args()
    DEMO = args.demo
    RESULTS_DIR = args.results

    if DEMO:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        if not report_files():
            demo_write_report()

    print("[web] PiDiagOS panel on :%d (demo=%s)" % (args.port, DEMO), flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
