# Repository Guidelines

## Project Structure & Module Organization
- Root orchestration: `docker-compose.yml`, env in `.env` (copy from `.env.example`).
- Services (Python unless noted):
  - `mumble-bot/` — Mumble AI bot client.
  - `faster-whisper-service/` — Speech-to-text API.
  - `piper-tts-service/` — Text-to-speech API.
  - `web-control-panel/` — Flask-based admin UI.
  - `sip-mumble-bridge/` — SIP ↔ Mumble bridge.
  - `mumble-web/`, `mumble-web-simple/` — Web Mumble clients (Node/webpack).
- Other: `docs/`, `models/`, `init-db.sql`, `mumble-config.ini`.

## Build, Test, and Development Commands
- Bootstrap env: `cp .env.example .env` and edit values.
- Run stack: `docker-compose up -d` (stop with `docker-compose down`).
- Rebuild services: `docker-compose build --no-cache`.
- Tail logs: `docker-compose logs -f <service>` (e.g., `faster-whisper`, `piper-tts`, `web-control-panel`).
- Web clients:
  - `cd mumble-web-simple && npm ci && npm run build` (tests: `npm run test`).
  - `cd mumble-web && npm ci && npm run build`.
- Local service dev (optional): `cd piper-tts-service && python app.py` (Docker is the default path).

## Coding Style & Naming Conventions
- Python: PEP 8, 4 spaces; `snake_case` for modules/functions, `PascalCase` for classes; add type hints and docstrings for public functions.
- JavaScript: 2-space indent; `camelCase` vars/functions; keep assets under `app/` (where applicable).
- Config: never hardcode secrets; read from `.env`. Keep Docker scripts small and self-contained.

## Testing Guidelines
- Current tests are minimal. Prefer:
  - Python: `pytest` with files under `<service>/tests/` named `test_*.py`.
  - Web: `mumble-web-simple` provides `npm run test` and `npm run audit:ci`.
- Aim for >80% coverage on new modules. Include error paths (I/O, network timeouts, audio edge cases).

## Commit & Pull Request Guidelines
- Commits: imperative mood, concise subject (≤72 chars), explain the why in the body.
  - Example: `Fix whisper timeouts on long inputs`.
- PRs: link issues, describe impact and rollout, add screenshots for UI, list repro/test steps, and update docs (README or `docs/`) when behavior changes.

## Security & Configuration Tips
- Do not commit real secrets, tokens, or downloaded models. Use `.env` and the provided download scripts.
- Ollama must be running locally for end-to-end usage; document model assumptions in PRs.
