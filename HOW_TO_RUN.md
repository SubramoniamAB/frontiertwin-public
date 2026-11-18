# How to Run FrontierTwin

Developer: Subramoniam AB (SAB) · Version 1.1.0

Step-by-step setup, run, refresh and upgrade for DGX Spark (DGX OS), Ubuntu/Linux, macOS and Windows.

## Contents

1. Requirements
2. Install (unpack)
3. Run: quick start per OS
4. `ft.py` command reference
5. Configuration (`config.json`)
6. Access from other machines (network, firewall)
7. Run in the background / at boot
8. Docker
9. Data refresh: manual
10. Data refresh: automatic (scheduled)
11. Add or correct models
12. Upgrade, check for updates, roll back
13. Offline mode (no server)
14. Troubleshooting

---

## 1. Requirements

| Item | Needed | Notes |
|---|---|---|
| Python | 3.8 or newer | Standard library only; no `pip install` |
| Browser | Any current Chrome, Edge, Firefox, Safari | |
| Internet | Only for `--catalog` URLs, `--discover`, and URL upgrades | Dashboard itself runs fully offline |
| Docker | Optional | For the container option |
| Disk | < 1 MB app + backups | |

Check Python:

| OS | Command | Install if missing |
|---|---|---|
| DGX OS / Ubuntu | `python3 --version` | `sudo apt update && sudo apt install -y python3` |
| macOS | `python3 --version` | `brew install python` or python.org installer |
| Windows | `py -3 --version` | `winget install Python.Python.3.12` or python.org (tick "Add python.exe to PATH") |

---

## 2. Install (unpack)

**DGX OS / Ubuntu / Linux**

```bash
# Option A: your home folder
unzip frontiertwin-1.1.0.zip -d ~/
cd ~/frontiertwin

# Option B: system-wide (recommended for a service)
sudo unzip frontiertwin-1.1.0.zip -d /opt/
sudo chown -R $USER:$USER /opt/frontiertwin
cd /opt/frontiertwin

chmod +x start.sh ft.py
```

If `unzip` is missing: `sudo apt install -y unzip`, or `python3 -m zipfile -e frontiertwin-1.1.0.zip ~/`.

**macOS**

```bash
unzip frontiertwin-1.1.0.zip -d ~/
cd ~/frontiertwin
chmod +x start.sh ft.py
xattr -dr com.apple.quarantine .   # only if macOS blocks the scripts
```

**Windows (PowerShell)**

```powershell
Expand-Archive .\frontiertwin-1.1.0.zip -DestinationPath C:\
cd C:\frontiertwin
```

Or right-click the zip → Extract All → `C:\`.

Folder layout after unpacking:

```
frontiertwin/
  index.html            dashboard page
  ft.py                 control script (serve, refresh, add, upgrade ...)
  start.sh / start.bat  launchers
  config.json           host, port, update URLs
  data/models.json      model catalog (page polls this every 60 s)
  data/models.js        same catalog for offline file mode
  data/overrides.json   your own model edits (kept across upgrades)
  Dockerfile, docker-compose.yml, frontiertwin.service
  backups/              created by upgrades
```

---

## 3. Run: quick start per OS

| OS | Start | Stop |
|---|---|---|
| DGX OS / Ubuntu / Linux | `./start.sh` | Ctrl+C |
| macOS | `./start.sh` | Ctrl+C |
| Windows | double-click `start.bat`, or `.\start.bat` in PowerShell | Ctrl+C or close the window |
| Any | `python3 ft.py serve` (Windows: `py -3 ft.py serve`) | Ctrl+C |

Expected output:

```
FrontierTwin 1.1.0 serving at http://localhost:8080  (Ctrl+C to stop)
```

Open **http://localhost:8080**.

Launchers pass options through:

```bash
./start.sh --port 9000                 # Linux/macOS
.\start.bat --port 9000                # Windows
./start.sh --host 127.0.0.1            # only this machine can connect
```

Using the dashboard:

1. Pick a vendor tab, then a frontier model; use the version dropdown (e.g. Opus 5.5 / 5 / 4.8).
2. Pick a priority preset or move the weight sliders.
3. Set constraints: vision, NVIDIA playbook only, tight fits, context, speed, local version/family.
4. Read the twin panel; switch twin versions with the version buttons.
5. Under "Deploy on your DGX Spark", pick a runtime tab and copy the commands. ✓ = covered by an official NVIDIA playbook.
6. Pick a frontier **Effort level** (under the model list) and a **Local reasoning mode** / **Architecture** (Constraints). The twin panel's **Effort mapping** table shows which local mode matches each frontier effort.
7. Click any table row or matrix cell to compare that pair.

The URL keeps the selected model (e.g. `http://localhost:8080/#claude-opus-5`), so links can be bookmarked or shared.

---

### Port already in use

The default port is 8080. If it is taken:

1. **At start-up (terminal):** `start.sh`, `start.bat` or `ft.py serve` stop and ask:
   ```
   Port 8080 is in use. Enter another port [8081] (q to quit):
   ```
   Type a port and press Enter, or press Enter to accept the suggested free port. Invalid or busy ports ask again. The chosen port is saved to `config.json`.
2. **At start-up (service / Docker / no terminal):** the next free port is used automatically and printed in the log (`Port 8080 is in use; using 8081 instead.`). It is not saved.
3. **From the page:** click the **gear icon** (Settings) in the header:
   1. Enter a port (1024–65535).
   2. Click **Check port**: shows "free" or "in use" with a suggested free port (filled in for you).
   3. Click **Apply and move**: the server starts on the new port, saves it to `config.json`, keeps the old port open for 4 seconds, and the page opens the new address.
   4. If the port is taken, the dialog shows the message and a suggestion; enter another port and apply again.
4. **Fixed port:** `./start.sh --port 9000` (Windows `start.bat --port 9000`) or edit `"port"` in `config.json`.

Offline file mode has no server to move; the Settings dialog shows the start command for the port you type.

## 4. `ft.py` command reference

Run from the `frontiertwin` folder. Linux/macOS: `python3 ft.py ...` or `./ft.py ...`. Windows: `py -3 ft.py ...`.

| Command | Options | What it does |
|---|---|---|
| `serve` | `--host HOST` (default from config, `0.0.0.0`) · `--port PORT` (default `8080`) | Starts the web server. If the port is busy, asks for another (terminal) or picks the next free one (no terminal). `/api/version` returns app and data versions. `config.json`, `ft.py`, `backups/` are not served. |
| `refresh` | *(none)* | Re-applies `data/overrides.json`, stamps today's date, rewrites `models.json` + `models.js`. |
| | `--catalog URL_OR_PATH` | Merges a newer catalog file (same format as `data/models.json`). New models are added; existing ones are replaced only if the incoming `updated` date is the same or newer. Changelog entries are merged. Uses `catalog_url` from config if not given. |
| | `--discover` | Queries Hugging Face for trending text-generation models created in the last `discover_max_age_days`, keeps those that fit ~119 GB at 4-bit, adds them as "awaiting scores" with estimated memory and speed. Skips cleanly if Hugging Face is unreachable. |
| `add FILE.json` | | Adds or replaces model(s) in `data/overrides.json`, then refreshes. File can hold one model object, a list, or `{"models": [...]}`. |
| `check-update` | `--manifest URL_OR_PATH` | Compares the installed `VERSION` with a release manifest. Uses `update_manifest_url` from config if not given. |
| `upgrade` | `--from ZIP_PATH_OR_URL` (required) | Backs up the current install to `backups/`, installs the new release, keeps `config.json` and `overrides.json`, keeps your `models.json` if newer, re-applies overrides. |
| | `--replace-data` | Takes the release's `models.json` even if yours is newer. |
| `rollback` | `[BACKUP_FILE]` | Restores the latest backup, or the named file in `backups/`. |
| `version` | | Prints the installed version. |
| `-h` / `--help` | | Help for any command, e.g. `python3 ft.py refresh --help`. |

Environment variable:

| Variable | Effect |
|---|---|
| `FT_ACCESS_LOG=1` | Print one line per HTTP request (off by default). Linux/macOS: `FT_ACCESS_LOG=1 ./start.sh`. Windows PowerShell: `$env:FT_ACCESS_LOG=1; .\start.bat` |

Examples:

```bash
python3 ft.py serve --host 0.0.0.0 --port 8080
python3 ft.py refresh
python3 ft.py refresh --discover
python3 ft.py refresh --catalog https://example.com/frontiertwin/models.json
python3 ft.py refresh --catalog /mnt/share/models.json --discover
python3 ft.py add my-model.json
python3 ft.py check-update --manifest https://example.com/frontiertwin/latest.json
python3 ft.py upgrade --from frontiertwin-1.1.0.zip
python3 ft.py upgrade --from https://example.com/frontiertwin-1.1.0.zip --replace-data
python3 ft.py rollback
python3 ft.py rollback frontiertwin-1.0.0-20261117-055247.zip
```

---

## 5. Configuration (`config.json`)

```json
{
  "host": "0.0.0.0",
  "port": 8080,
  "catalog_url": "",
  "update_manifest_url": "",
  "discover_limit": 60,
  "discover_max_age_days": 120,
  "allow_web_refresh": true,
  "web_refresh_discover": false
}
```

| Key | Meaning |
|---|---|
| `host` | `0.0.0.0` = reachable from the network; `127.0.0.1` = this machine only |
| `port` | Web port |
| `catalog_url` | Default for `refresh --catalog` (URL or file path). Leave empty to disable. |
| `update_manifest_url` | Default for `check-update` |
| `discover_limit` | How many trending Hugging Face models `--discover` inspects |
| `discover_max_age_days` | Ignore models older than this |
| `allow_web_refresh` | `true` = the header refresh button may rebuild data on the server (`POST /api/refresh`); `false` = button only re-reads data |
| `web_refresh_discover` | `true` = the button also runs Hugging Face discovery (slower) |

Command-line options override `config.json`. Restart `serve` after editing it. Upgrades never overwrite it.

---

## 6. Access from other machines

1. Keep `"host": "0.0.0.0"`.
2. Find the server's IP:
   - DGX OS / Ubuntu: `hostname -I`
   - macOS: `ipconfig getifaddr en0`
   - Windows: `ipconfig` (IPv4 Address)
3. Open the port in the firewall:
   - Ubuntu (ufw): `sudo ufw allow 8080/tcp`
   - Windows (admin PowerShell): `New-NetFirewallRule -DisplayName "FrontierTwin" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow`
   - macOS: System Settings → Network → Firewall → allow Python
4. Browse to `http://<server-ip>:8080`.

Through NVIDIA Sync or SSH from a laptop (no firewall change):

```bash
ssh -L 8080:localhost:8080 <user>@<spark-ip>
# then open http://localhost:8080 on the laptop
```

The built-in server has no login. Keep it on a trusted network, or put it behind a reverse proxy (nginx, Caddy) with authentication.

---

## 7. Run in the background / at boot

**DGX OS / Ubuntu: systemd (recommended)**

```bash
cd /opt/frontiertwin
sed -i "s/REPLACE_WITH_YOUR_USER/$USER/" frontiertwin.service
# if installed elsewhere, also edit WorkingDirectory and ExecStart paths
sudo cp frontiertwin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now frontiertwin

systemctl status frontiertwin            # check
journalctl -u frontiertwin -f            # logs
sudo systemctl restart frontiertwin      # after config change or upgrade
sudo systemctl disable --now frontiertwin   # remove from boot
```

**Linux / macOS: quick background run**

```bash
nohup ./start.sh > frontiertwin.log 2>&1 &
pkill -f "ft.py serve"                   # stop
```

**macOS at login (launchd)**: save as `~/Library/LaunchAgents/com.frontiertwin.plist` (edit paths):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.frontiertwin</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>/Users/YOU/frontiertwin/ft.py</string><string>serve</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.frontiertwin.plist
launchctl unload ~/Library/LaunchAgents/com.frontiertwin.plist   # stop
```

**Windows: start at logon (Task Scheduler)**

```powershell
schtasks /create /tn "FrontierTwin" /sc onlogon /rl limited /tr "py -3 C:\frontiertwin\ft.py serve"
schtasks /run /tn "FrontierTwin"          # start now
schtasks /end /tn "FrontierTwin"          # stop
schtasks /delete /tn "FrontierTwin" /f    # remove
```

Hidden window alternative: `pythonw C:\frontiertwin\ft.py serve`.

---

## 8. Docker

Works on arm64 (DGX Spark) and x86_64.

```bash
cd frontiertwin
docker compose up -d --build             # build and start on port 8080
docker compose logs -f                   # logs
docker compose down                      # stop
```

`./data` is mounted into the container, so refreshes run on the host take effect immediately:

```bash
python3 ft.py refresh --discover         # on the host; page updates within 60 s
# or inside the container:
docker exec frontiertwin python3 ft.py refresh --discover
```

Without compose:

```bash
docker build -t frontiertwin .
docker run -d --name frontiertwin -p 8080:8080 -v "$PWD/data:/app/data" --restart unless-stopped frontiertwin
```

Change the host port: edit `"8080:8080"` to `"9000:8080"` in `docker-compose.yml`.

After an app upgrade: `docker compose up -d --build`.

---

## 9. Data refresh: manual

How live updates work:

```
 ft.py refresh  ──writes──>  data/models.json + models.js
                                   │
 open browsers  <──poll every 60 s─┘   (also on tab focus)
```

No page reload or server restart is needed after a data refresh.

**Refresh button (header, circular-arrow icon):**

1. Click it in the page header (next to the help icon).
2. The server runs the same steps as `ft.py refresh` (merges `catalog_url` if set; runs discovery only if `web_refresh_discover` is `true`).
3. The page re-reads the data and shows a message such as "Refreshed 2026-11-18: 25 frontier, 17 local, 7 pending".
4. In offline file mode the button reloads the page.
5. Disable server-side rebuilds with `"allow_web_refresh": false` in `config.json` (the button then only re-reads data).

**Help (? icon or the `?` key):** in-app guide covering sliders, results, the match matrix, deployment, refresh and upgrades.

| Goal | Command |
|---|---|
| Re-apply your overrides | `python3 ft.py refresh` |
| Find new Spark-sized open models | `python3 ft.py refresh --discover` |
| Pull a newer shared catalog | `python3 ft.py refresh --catalog <URL or path>` |
| Everything | `python3 ft.py refresh --catalog <URL> --discover` |

Output example:

```
  catalog: 3 added, 5 updated
  discover: 2 new Spark-sized models
  overrides: 0 added, 1 replaced
Refreshed 2026-11-24: 25 frontier, 18 local, 9 pending. Open pages update within 60 s.
```

Each change is written to the page's "What changed" panel.

Ways to get a newer catalog:

1. Ask Claude in the FrontierTwin project to refresh the data; it produces an updated `models.json`.
2. Host one `models.json` for your team (file share, intranet, GitHub raw URL) and point every install's `catalog_url` at it.
3. Edit models yourself with `ft.py add` (section 11).

Status dot in the header: green = refreshed in the last 10 days; amber = older.

---

## 10. Data refresh: automatic (scheduled)

**DGX OS / Ubuntu / macOS: cron (weekly, Monday 10:17)**

```bash
crontab -e
```

Add:

```
17 10 * * 1 cd /opt/frontiertwin && /usr/bin/python3 ft.py refresh --discover >> refresh.log 2>&1
```

Daily at 06:30 instead: `30 6 * * *`. With a shared catalog: add `--catalog https://...` or set `catalog_url`. Check: `crontab -l`, `tail refresh.log`.

**DGX OS / Ubuntu: systemd timer (alternative to cron)**

`/etc/systemd/system/frontiertwin-refresh.service`:

```ini
[Unit]
Description=FrontierTwin data refresh
[Service]
Type=oneshot
User=REPLACE_WITH_YOUR_USER
WorkingDirectory=/opt/frontiertwin
ExecStart=/usr/bin/python3 /opt/frontiertwin/ft.py refresh --discover
```

`/etc/systemd/system/frontiertwin-refresh.timer`:

```ini
[Unit]
Description=Weekly FrontierTwin refresh
[Timer]
OnCalendar=Mon *-*-* 10:17:00
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now frontiertwin-refresh.timer
systemctl list-timers | grep frontiertwin
sudo systemctl start frontiertwin-refresh.service   # run once now
```

**Windows: Task Scheduler**

```powershell
schtasks /create /tn "FrontierTwin Refresh" /sc weekly /d MON /st 10:17 /tr "py -3 C:\frontiertwin\ft.py refresh --discover"
schtasks /run /tn "FrontierTwin Refresh"          # run now
schtasks /query /tn "FrontierTwin Refresh"        # check
schtasks /delete /tn "FrontierTwin Refresh" /f    # remove
```

Daily: `/sc daily /st 06:30`.

**Docker host**: use cron or a systemd timer on the host with `docker exec frontiertwin python3 ft.py refresh --discover`.

---

## 11. Add or correct models

1. Create a JSON file, e.g. `my-model.json`:

```json
{
  "id": "my-qwen-finetune",
  "kind": "local",
  "name": "My Qwen Finetune",
  "vendor": "Me",
  "family": "Qwen 27B dense",
  "version": "3.8-ft1",
  "paramsTotal": 27, "paramsActive": 27,
  "contextK": 128, "vision": false,
  "scores": { "overall": 55, "coding": 50, "agentic": 60 },
  "spark": { "fit": "native", "quant": "NVFP4", "memGB": 21,
             "tps": { "decode": 36 }, "tpsSource": "measured", "runtime": "vLLM" },
  "deploy": { "hf": "me/my-qwen-finetune", "verified": ["hf"] },
  "playbooks": [{ "name": "vLLM", "url": "https://build.nvidia.com/spark/vllm" }],
  "sources": ["https://example.com/my-eval"]
}
```

2. Run `python3 ft.py add my-model.json`.
3. The page shows it within 60 s.

Field guide:

| Field | Values |
|---|---|
| `kind` | `frontier` (paid target), `local` (ranked; needs scores), `pending` (runs on a Spark, no published capability scores yet; shown in the Pending list, excluded from match %, ranking and matrix until scores are added) |
| `family`, `version` | Same `family` = shown as versions of one model |
| `scores` | 0–100: `overall`, `coding`, `agentic`, `reasoning`, `multimodal`, `knowledge`, `math` (omit unknowns) |
| `spark.fit` | `native` or `tight` (2–3 bit, or > ~95 GB) |
| `spark.tpsSource` | `measured` or `estimated` |
| `deploy` | `hf` (Hugging Face handle), `gguf` (`repo:quant`), `ollama` (tag), `nim` (image), `image` (vLLM image override), `vllmArgs`, `verified` (list of confirmed handles) |
| `playbooks` | NVIDIA playbook name + URL; drives the badge and ✓ tabs |
| `modes` | Local only, optional: measured reasoning modes `{"low": {"factor": 0.85, "tokens": 600}, ...}` (factor vs high, thinking tokens per answer) |
| `efforts` | Frontier only, optional: AA index per effort `{"max": 59.1, "medium": 48.2}` |

To correct an existing model, use its existing `id`; overrides always win. To undo, delete the entry from `data/overrides.json` and restore the original with `python3 ft.py refresh --catalog <original models.json>` or an upgrade.

---

## 12. Upgrade, check for updates, roll back

**Check**

```bash
python3 ft.py check-update                       # uses update_manifest_url
python3 ft.py check-update --manifest https://example.com/frontiertwin/latest.json
```

Manifest format:

```json
{ "version": "1.1.0", "url": "https://example.com/frontiertwin-1.1.0.zip", "notes": "What changed" }
```

**Upgrade**

```bash
python3 ft.py upgrade --from frontiertwin-1.1.0.zip           # local file
python3 ft.py upgrade --from https://example.com/frontiertwin-1.1.0.zip
python3 ft.py upgrade --from frontiertwin-1.1.0.zip --replace-data
```

What happens:

1. Current install zipped to `backups/frontiertwin-<old>-<timestamp>.zip`.
2. New files copied in.
3. Kept: `config.json`, `data/overrides.json`, and `data/models.json` if yours was refreshed more recently (unless `--replace-data`).
4. Overrides re-applied; data files rebuilt.

Then restart the server:

| Setup | Restart |
|---|---|
| Terminal | Ctrl+C, then `./start.sh` / `start.bat` |
| systemd | `sudo systemctl restart frontiertwin` |
| Docker | `docker compose up -d --build` |
| Windows task | `schtasks /end /tn "FrontierTwin"` then `schtasks /run /tn "FrontierTwin"` |

**Roll back**

```bash
python3 ft.py rollback                                        # latest backup
ls backups/                                                   # list backups
python3 ft.py rollback frontiertwin-1.0.0-20261117-055247.zip # specific one
```

Restart the server afterwards. Delete old zips in `backups/` when no longer needed.

---

## 13. Offline mode (no server)

Double-click `index.html` (or open it with File → Open in a browser).

- Works with no Python and no network.
- Reads `data/models.js`.
- Does not auto-refresh: run `ft.py refresh` and reload the page to see changes.
- Header shows "offline file mode".

---

## 14. Troubleshooting

| Symptom | Fix |
|---|---|
| `python3: command not found` / `'py' is not recognized` | Install Python (section 1); on Windows reinstall with "Add to PATH" |
| `Address already in use` / `OSError: [WinError 10048]` | Enter another port at the prompt, use Settings (gear icon) in the page, or `./start.sh --port 9000`; to find the process: Linux `sudo lsof -i :8080`, Windows `netstat -ano \| findstr :8080` |
| `Permission denied: ./start.sh` | `chmod +x start.sh ft.py` |
| Page says "Loading the model catalog" | Open via `http://localhost:8080`, not a different folder; check `data/models.json` exists |
| Other machines can't connect | Host must be `0.0.0.0`; open firewall (section 6) |
| Changes don't appear | Wait 60 s or focus the tab; confirm `ft.py refresh` printed "Refreshed"; in file mode reload the page |
| `discover: Hugging Face not reachable` | Network/proxy blocks huggingface.co; set `HTTPS_PROXY` or run without `--discover` |
| `data/models.json is missing or invalid` | `python3 ft.py rollback`, or copy `data/` from the release zip |
| Upgrade says "not a FrontierTwin release" | Use an official release zip (must contain `index.html` and `VERSION`) |
| macOS blocks scripts | `xattr -dr com.apple.quarantine ~/frontiertwin` |
| Docker on Spark: wrong architecture | Rebuild on the Spark: `docker compose build --no-cache` |
