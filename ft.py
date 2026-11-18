#!/usr/bin/env python3
"""
FrontierTwin: self-hosted control script (Python 3.8+, standard library only).

Developer: Subramoniam AB (SAB)

  python3 ft.py serve                 Start the dashboard (default http://0.0.0.0:8080)
  python3 ft.py refresh               Rebuild data from models.json + overrides.json
  python3 ft.py refresh --catalog URL Merge a newer catalog (URL or file), then rebuild
  python3 ft.py refresh --discover    Also add new open models from Hugging Face that fit one Spark
  python3 ft.py add FILE.json         Add / replace models (kept across upgrades)
  python3 ft.py check-update          Compare with the release manifest in config.json
  python3 ft.py upgrade --from ZIP|URL  Install a new app release (backs up first, keeps your data)
  python3 ft.py rollback              Restore the most recent backup
  python3 ft.py version

Layout:
  index.html            dashboard (no external dependencies)
  data/models.json      catalog the page polls every 60 s
  data/models.js        same catalog for file:// (double-click) mode
  data/overrides.json   your own additions; never overwritten by upgrades
  config.json           host, port, catalog_url, update_manifest_url
  backups/              zip of the app before each upgrade
"""
import argparse
import contextlib
import datetime as dt
import functools
import http.server
import io
import json
import os
import shutil
import socket
import socketserver
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
MODELS_JSON = os.path.join(DATA_DIR, "models.json")
MODELS_JS = os.path.join(DATA_DIR, "models.js")
OVERRIDES_JSON = os.path.join(DATA_DIR, "overrides.json")
CONFIG_JSON = os.path.join(APP_DIR, "config.json")
BACKUP_DIR = os.path.join(APP_DIR, "backups")
VERSION_FILE = os.path.join(APP_DIR, "VERSION")

# DGX Spark sizing (128 GB unified, ~119 GB usable by the GPU, 273 GB/s)
SPARK_USABLE_GB = 119
SPARK_BW_GBS = 273
KV_RUNTIME_GB = 8
TIGHT_GB = 95
BYTES_4BIT = 0.55            # ~4.4 bits/param incl. scales
BW_EFFICIENCY = 0.6
HF_API = "https://huggingface.co/api/models"
HTTP_TIMEOUT_S = 30
KEEP_PATHS = ("data/overrides.json", "config.json")   # never replaced by an upgrade
CHANGELOG_MAX = 40

DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 8080,
    "catalog_url": "",
    "update_manifest_url": "",
    "discover_limit": 60,
    "discover_max_age_days": 120,
    "allow_web_refresh": True,       # header refresh button may rebuild data
    "web_refresh_discover": False,   # button also queries Hugging Face (slower)
}
REFRESH_LOCK = threading.Lock()
MIN_PORT = 1024                 # below this needs admin/root
MAX_PORT = 65535
PORT_SCAN_SPAN = 50             # how far to look for a free port suggestion
SWITCH_GRACE_S = 4              # old listener stays up while the page redirects
# Windows SO_REUSEADDR lets two servers share a port; only reuse on POSIX
REUSE_ADDR = os.name != "nt"


# ---------- small helpers ----------
def today():
    return dt.date.today().isoformat()


def app_version():
    try:
        with open(VERSION_FILE) as f:
            return f.read().strip()
    except OSError:
        return "0.0.0"


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_atomic(path, text):
    # Write next to the target, then rename: the server never serves a half-written file
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG_JSON, {}) or {})
    return cfg


def fetch_bytes(src):
    if os.path.exists(src):
        with open(src, "rb") as f:
            return f.read()
    req = urllib.request.Request(src, headers={"User-Agent": "FrontierTwin/" + app_version()})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as r:
        return r.read()


def vkey(v):
    return tuple(int(x) if x.isdigit() else 0 for x in str(v).split("."))


# ---------- data ----------
def load_catalog():
    data = load_json(MODELS_JSON)
    if not data or "models" not in data:
        sys.exit("data/models.json is missing or invalid. Restore it from a backup or the release zip.")
    return data


def save_catalog(data):
    data["models"].sort(key=lambda m: (m.get("kind", ""), m.get("family", ""), m.get("id", "")))
    text = json.dumps(data, indent=1, ensure_ascii=False)
    write_atomic(MODELS_JSON, text)
    write_atomic(MODELS_JS, "window.FT_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n")


def log(data, text):
    cl = data.setdefault("meta", {}).setdefault("changelog", [])
    cl.insert(0, {"date": today(), "text": text})
    del cl[CHANGELOG_MAX:]


def merge_models(data, incoming, source, force=False):
    """Insert new models; replace existing ones when the incoming copy is newer (or force)."""
    by_id = {m["id"]: i for i, m in enumerate(data["models"])}
    added, updated = [], []
    for m in incoming:
        if not isinstance(m, dict) or not m.get("id") or not m.get("name"):
            continue
        if m["id"] not in by_id:
            data["models"].append(m)
            added.append(m["name"])
            continue
        cur = data["models"][by_id[m["id"]]]
        if force or str(m.get("updated", "")) >= str(cur.get("updated", "")):
            if m != cur:
                data["models"][by_id[m["id"]]] = m
                updated.append(m["name"])
    if added:
        log(data, f"Added from {source}: " + ", ".join(added[:12]) + (" …" if len(added) > 12 else ""))
    if updated:
        log(data, f"Updated from {source}: " + ", ".join(updated[:12]) + (" …" if len(updated) > 12 else ""))
    return added, updated


def discover_hf(data, cfg):
    """Add recent open text-generation models from Hugging Face that fit one Spark at 4-bit, as 'pending'."""
    url = (f"{HF_API}?pipeline_tag=text-generation&sort=trendingScore&limit={int(cfg['discover_limit'])}"
           "&expand[]=safetensors&expand[]=createdAt&expand[]=downloads")
    try:
        items = json.loads(fetch_bytes(url))
    except Exception as e:   # network blocked, proxy, rate limit
        print(f"  discover: Hugging Face not reachable ({e}); skipped")
        return []
    have = {m.get("deploy", {}).get("hf", "").lower() for m in data["models"]}
    cutoff = (dt.date.today() - dt.timedelta(days=int(cfg["discover_max_age_days"]))).isoformat()
    found = []
    for it in items:
        repo = it.get("id", "")
        params = (it.get("safetensors") or {}).get("total")
        created = (it.get("createdAt") or "")[:10]
        if not repo or not params or repo.lower() in have or created < cutoff:
            continue
        if any(t in repo.lower() for t in ("gguf", "-awq", "-gptq", "lora", "adapter")):
            continue
        p_b = params / 1e9
        mem = round(p_b * BYTES_4BIT + KV_RUNTIME_GB, 1)
        if mem > SPARK_USABLE_GB:
            continue
        # Dense estimate; MoE models are faster than this
        tps = round(BW_EFFICIENCY * SPARK_BW_GBS / max(p_b * BYTES_4BIT, 0.5), 1)
        mid = "hf-" + repo.lower().replace("/", "--").replace(".", "-")
        found.append({
            "id": mid, "kind": "pending", "name": repo.split("/")[-1], "vendor": repo.split("/")[0],
            "family": repo.split("/")[-1].split("-")[0], "version": created,
            "open": True, "paramsTotal": round(p_b, 1), "released": created,
            "spark": {"fit": "tight" if mem > TIGHT_GB else "native", "quant": "4-bit (est.)", "memGB": mem,
                      "tps": {"decode": tps}, "tpsSource": "estimated", "runtime": "vLLM / llama.cpp"},
            "deploy": {"hf": repo, "verified": ["hf"]},
            "bestFor": "Discovered on Hugging Face; awaiting benchmark scores",
            "scores": {}, "sources": ["https://huggingface.co/" + repo], "updated": today(),
        })
    return found


# ---------- commands ----------
def cmd_refresh(args):
    cfg = config()
    data = load_catalog()
    catalog = args.catalog or cfg.get("catalog_url")
    if catalog:
        try:
            remote = json.loads(fetch_bytes(catalog))
            a, u = merge_models(data, remote.get("models", []), "catalog")
            print(f"  catalog: {len(a)} added, {len(u)} updated")
            # Remote changelog entries we don't have yet
            seen = {(c["date"], c["text"]) for c in data["meta"].get("changelog", [])}
            for c in reversed(remote.get("meta", {}).get("changelog", [])):
                if (c.get("date"), c.get("text")) not in seen:
                    data["meta"]["changelog"].insert(0, c)
        except Exception as e:
            print(f"  catalog: could not load {catalog} ({e}); skipped")
    if args.discover:
        a, _ = merge_models(data, discover_hf(data, cfg), "Hugging Face discovery")
        print(f"  discover: {len(a)} new Spark-sized models")
    ov = load_json(OVERRIDES_JSON, {}) or {}
    if ov.get("models"):
        a, u = merge_models(data, ov["models"], "overrides.json", force=True)
        print(f"  overrides: {len(a)} added, {len(u)} replaced")
    data["meta"]["lastRefreshed"] = today()
    save_catalog(data)
    n = {k: sum(1 for m in data["models"] if m.get("kind") == k) for k in ("frontier", "local", "pending")}
    print(f"Refreshed {today()}: {n['frontier']} frontier, {n['local']} local, {n['pending']} pending. Open pages update within 60 s.")


def cmd_add(args):
    new = load_json(args.file)
    if new is None:
        sys.exit(f"Cannot read {args.file} as JSON.")
    items = new.get("models", [new]) if isinstance(new, dict) else new
    ov = load_json(OVERRIDES_JSON, {}) or {}
    ov.setdefault("models", [])
    ids = {m["id"]: i for i, m in enumerate(ov["models"])}
    for m in items:
        if not m.get("id") or not m.get("name") or m.get("kind") not in ("frontier", "local", "pending"):
            sys.exit("Each model needs id, name and kind (frontier | local | pending).")
        m.setdefault("updated", today())
        if m["id"] in ids:
            ov["models"][ids[m["id"]]] = m
        else:
            ov["models"].append(m)
    write_atomic(OVERRIDES_JSON, json.dumps(ov, indent=1, ensure_ascii=False))
    print(f"Saved {len(items)} model(s) to data/overrides.json")
    cmd_refresh(argparse.Namespace(catalog=None, discover=False))


def backup():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"frontiertwin-{app_version()}-{dt.datetime.now():%Y%m%d-%H%M%S}.zip"
    path = os.path.join(BACKUP_DIR, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(APP_DIR):
            dirs[:] = [d for d in dirs if d not in ("backups", "__pycache__")]
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, APP_DIR))
    return path


def install_zip(blob, keep_newer_data=True):
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = z.namelist()
    # Accept a zip with files at the root or inside one top-level folder
    prefix = ""
    if "index.html" not in names:
        tops = {n.split("/")[0] for n in names if "/" in n}
        top = next(iter(tops)) if len(tops) == 1 else None
        if top and f"{top}/index.html" in names:
            prefix = top + "/"
        else:
            sys.exit("This zip is not a FrontierTwin release (no index.html).")
    new_ver = z.read(prefix + "VERSION").decode().strip() if prefix + "VERSION" in names else "?"
    local = load_json(MODELS_JSON, {}) or {}
    for n in names:
        if not n.startswith(prefix) or n.endswith("/"):
            continue
        rel = n[len(prefix):]
        if rel in KEEP_PATHS and os.path.exists(os.path.join(APP_DIR, rel)):
            continue
        if rel in ("data/models.json", "data/models.js") and keep_newer_data:
            incoming = json.loads(z.read(prefix + "data/models.json"))
            if str(local.get("meta", {}).get("lastRefreshed", "")) > str(incoming.get("meta", {}).get("lastRefreshed", "")):
                continue
        dest = os.path.join(APP_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(z.read(n))
    return new_ver


def cmd_upgrade(args):
    cur = app_version()
    blob = fetch_bytes(args.source)
    path = backup()
    print(f"Backed up {cur} to {os.path.relpath(path, APP_DIR)}")
    new = install_zip(blob, keep_newer_data=not args.replace_data)
    # New app code may change the schema: merge the newer catalog and re-apply overrides
    cmd_refresh(argparse.Namespace(catalog=None, discover=False))
    print(f"Upgraded {cur} -> {new}. Restart 'ft.py serve' (or the service/container) to load new server code.")


def cmd_rollback(args):
    if not os.path.isdir(BACKUP_DIR) or not os.listdir(BACKUP_DIR):
        sys.exit("No backups found.")
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip"))
    target = args.backup or files[-1]
    with open(os.path.join(BACKUP_DIR, target), "rb") as f:
        blob = f.read()
    install_zip(blob, keep_newer_data=False)
    print(f"Restored {target}. Restart the server.")


def cmd_check_update(args):
    url = args.manifest or config().get("update_manifest_url")
    if not url:
        sys.exit('Set "update_manifest_url" in config.json (a JSON file: {"version": "1.1.0", "url": "https://.../frontiertwin-1.1.0.zip", "notes": "..."}).')
    man = json.loads(fetch_bytes(url))
    cur = app_version()
    if vkey(man.get("version", "0")) > vkey(cur):
        print(f"Update available: {cur} -> {man['version']}\n  {man.get('notes', '')}\n  Install: python3 ft.py upgrade --from {man['url']}")
    else:
        print(f"Up to date ({cur}).")


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.startswith("/data/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/api/version":
            meta = (load_json(MODELS_JSON, {}) or {}).get("meta", {})
            body = json.dumps({"version": app_version(), "dataAsOf": meta.get("lastRefreshed")}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        route = self.path.split("?")[0]
        if route == "/api/settings":
            self._json(200, {"host": HUB.host, "port": HUB.port, "configPort": int(config()["port"])})
            return
        if route == "/api/port-check":
            port = parse_port(self._query("port"))
            if port is None:
                self._json(400, {"ok": False, "message": f"Enter a number from {MIN_PORT} to {MAX_PORT}."})
                return
            free = port == HUB.port or port_free(HUB.host, port)
            self._json(200, {"ok": True, "port": port, "free": free, "current": port == HUB.port,
                             "suggest": None if free else next_free(HUB.host, port + 1)})
            return
        if self.path.startswith(("/backups", "/config.json", "/ft.py")):
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        route = self.path.split("?")[0]
        if route == "/api/port":
            self._post_port()
            return
        # Manual refresh from the page's header button
        if route != "/api/refresh":
            self.send_error(404)
            return
        cfg = config()
        if not cfg.get("allow_web_refresh", True):
            self._json(403, {"ok": False, "message": "Web refresh is disabled in config.json (allow_web_refresh)."})
            return
        if not REFRESH_LOCK.acquire(blocking=False):
            self._json(409, {"ok": False, "message": "A refresh is already running."})
            return
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_refresh(argparse.Namespace(catalog=None, discover=bool(cfg.get("web_refresh_discover"))))
            lines = [ln.strip() for ln in buf.getvalue().splitlines() if ln.strip()]
            self._json(200, {"ok": True, "message": lines[-1] if lines else "Refreshed.", "log": lines})
        except SystemExit as e:
            self._json(500, {"ok": False, "message": str(e)})
        finally:
            REFRESH_LOCK.release()

    def _query(self, key):
        from urllib.parse import urlparse, parse_qs
        return (parse_qs(urlparse(self.path).query).get(key) or [""])[0]

    def _post_port(self):
        # Settings dialog: start on a new port, save it, retire this listener
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        port = parse_port(body.get("port"))
        if port is None:
            self._json(400, {"ok": False, "message": f"Enter a number from {MIN_PORT} to {MAX_PORT}."})
            return
        if port == HUB.port:
            self._json(200, {"ok": True, "port": port, "message": f"Already running on port {port}."})
            return
        try:
            HUB.switch(port)
        except OSError:
            self._json(409, {"ok": False, "port": port, "suggest": next_free(HUB.host, port + 1),
                             "message": f"Port {port} is in use or blocked. Enter a different port."})
            return
        save_port(port)
        self._json(200, {"ok": True, "port": port,
                         "message": f"Now running on port {port}. Saved to config.json for the next start."})

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *a):
        if os.environ.get("FT_ACCESS_LOG"):
            super().log_message(fmt, *a)


# ---------- ports ----------
def parse_port(v):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    if n < MIN_PORT or n > MAX_PORT:
        return None
    return n


def port_free(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if REUSE_ADDR:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host or "0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def next_free(host, start):
    for p in range(start, min(start + PORT_SCAN_SPAN, MAX_PORT + 1)):
        if port_free(host, p):
            return p
    return None


def save_port(port):
    cfg = load_json(CONFIG_JSON, {}) or {}
    cfg["port"] = port
    write_atomic(CONFIG_JSON, json.dumps(cfg, indent=2))


def ask_port(host, port):
    """Port busy: ask in a terminal; pick the next free one when unattended.

    Returns (port, prompted); only a port the user typed or accepted is saved.
    """
    prompted = False
    while not port_free(host, port):
        suggest = next_free(host, port + 1)
        if not sys.stdin or not sys.stdin.isatty():
            if suggest is None:
                sys.exit(f"Port {port} is in use and no free port found nearby.")
            print(f"Port {port} is in use; using {suggest} instead.")
            return suggest, False
        ans = input(f"Port {port} is in use. Enter another port [{suggest}] (q to quit): ").strip()
        prompted = True
        if ans.lower() == "q":
            sys.exit("Stopped.")
        if not ans and suggest:
            port = suggest
            continue
        p = parse_port(ans)
        if p is None:
            print(f"  Enter a number from {MIN_PORT} to {MAX_PORT}.")
            continue
        port = p
    return port, prompted


class ServerHub:
    """Runs the HTTP listener in a thread so the page can move it to another port."""

    def __init__(self):
        self.host, self.port, self.server = "0.0.0.0", None, None
        self.lock = threading.Lock()

    def _start(self, port):
        handler = functools.partial(Handler, directory=APP_DIR)
        cls = type("FTServer", (socketserver.ThreadingTCPServer,), {"allow_reuse_address": REUSE_ADDR, "daemon_threads": True})
        srv = cls((self.host, port), handler)          # raises OSError if busy
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    def start(self, host, port):
        self.host, self.port = host, port
        self.server = self._start(port)

    def switch(self, port):
        with self.lock:
            new = self._start(port)
            old = self.server
            self.server, self.port = new, port
        shown = "localhost" if self.host in ("0.0.0.0", "") else self.host
        print(f"Moved to http://{shown}:{port} (old port closes in {SWITCH_GRACE_S} s)")

        def retire():
            time.sleep(SWITCH_GRACE_S)
            old.shutdown()
            old.server_close()
        threading.Thread(target=retire, daemon=True).start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()


HUB = ServerHub()


def cmd_serve(args):
    cfg = config()
    host = args.host or cfg["host"]
    port = parse_port(args.port or cfg["port"])
    if port is None:
        sys.exit(f"Port must be a number from {MIN_PORT} to {MAX_PORT}.")
    port, asked = ask_port(host, port)
    if asked and port != parse_port(cfg["port"]):
        save_port(port)
        print(f"Saved port {port} to config.json.")
    try:
        HUB.start(host, port)
    except OSError as e:
        sys.exit(f"Cannot start on port {port}: {e}")
    shown = "localhost" if host in ("0.0.0.0", "") else host
    print(f"FrontierTwin {app_version()} serving at http://{shown}:{port}  (Ctrl+C to stop)")
    print("Change the port any time from the page: Settings (gear icon).")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        HUB.stop()
        print("\nStopped.")


def main():
    p = argparse.ArgumentParser(prog="ft.py", description="FrontierTwin self-hosted control")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the dashboard")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.set_defaults(fn=cmd_serve)
    r = sub.add_parser("refresh", help="rebuild data; optionally merge a catalog or discover new models")
    r.add_argument("--catalog", help="URL or path of a newer models.json")
    r.add_argument("--discover", action="store_true", help="add new Spark-sized open models from Hugging Face")
    r.set_defaults(fn=cmd_refresh)
    a = sub.add_parser("add", help="add/replace models from a JSON file (kept in overrides.json)")
    a.add_argument("file")
    a.set_defaults(fn=cmd_add)
    c = sub.add_parser("check-update", help="check the release manifest")
    c.add_argument("--manifest")
    c.set_defaults(fn=cmd_check_update)
    u = sub.add_parser("upgrade", help="install a new release zip (URL or path)")
    u.add_argument("--from", dest="source", required=True)
    u.add_argument("--replace-data", action="store_true", help="take the release's models.json even if yours is newer")
    u.set_defaults(fn=cmd_upgrade)
    b = sub.add_parser("rollback", help="restore a backup (latest by default)")
    b.add_argument("backup", nargs="?")
    b.set_defaults(fn=cmd_rollback)
    v = sub.add_parser("version")
    v.set_defaults(fn=lambda _: print(app_version()))
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
