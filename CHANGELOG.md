# Changelog

## 1.0.5 (2026-11-18)
- README rewritten with dashboard screenshot (docs/screenshot.png), features, config and port tables
- Fix: a free --port given on the command line was saved to config.json; only a port chosen at the busy-port prompt is saved now

## 1.0.4 (2026-11-18)
- Settings (gear icon): check a port and move the running server to it; saved to config.json
- Busy port at start-up: terminal prompt with suggested free port; unattended runs pick the next free port
- Windows: no SO_REUSEADDR, so a busy port is detected instead of shared
- API: GET /api/settings, GET /api/port-check?port=N, POST /api/port

## 1.0.3 (2026-11-18)
- Clear explanation of "pending" models on the page, in Help and in the docs

## 1.0.2 (2026-11-18)
- Header refresh button (server rebuild via POST /api/refresh; config: allow_web_refresh, web_refresh_discover)
- In-app Help: getting started, sliders, results, match matrix, deploy, refresh, install/upgrade, about
- Match matrix: explanation, color legend, best cell per row, Best twin column, sticky row labels
- "How matching works" as a full-width panel of six method cards

## 1.0.1 (2026-11-18)
- Redesigned header: logo, full-width description, short status, KPI strip
- "What matters to you": live share % per capability and plain-language explanation
- Developer credit with photo in the footer; author headers in code

## 1.0.0 (2026-11-17)
- Frontier → DGX Spark twin matching with weights, constraints and verdicts
- Version selector per model family (frontier and local)
- NVIDIA DGX Spark playbook badges, filter and copy-ready deploy commands
- Match matrix, awaiting-scores list, changelog
- ft.py: serve, refresh (catalog merge, Hugging Face discovery), add, check-update, upgrade, rollback
- Docker, docker-compose, systemd, Windows/macOS/Linux launchers
- HOW_TO_RUN.md: full install, run, refresh and upgrade guide

Developer: Subramoniam AB (SAB)
