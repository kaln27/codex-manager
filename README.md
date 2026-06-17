# Codex Manager

Local web UI for managing Codex provider files, sessions, and environment variables.

Frontend assets live in `codex_manager/dist/`:

- `index.html`
- `styles.css`
- `app.js`

## Run

```bash
conda run -n llm python codex_manager/app.py
```

Then open:

```text
http://127.0.0.1:8765
```

If the page is already open from an older version, hard refresh the browser tab.

Optional:

```bash
conda run -n llm python codex_manager/app.py --host 127.0.0.1 --port 8765
```

## Data

- Provider profiles are stored under `codex_manager/provider_profiles/`.
- Switching providers replaces `~/.codex/config.toml` and `~/.codex/auth.json`.
- Provider switching, session provider edits, session deletion, and `.env` saves create backups under `~/.codex/*_backups/`.
- Sessions are loaded from `~/.codex/state_5.sqlite` and their matching jsonl rollout files.
- Env values are saved to `~/.codex/.env`, one `KEY=VALUE` pair per line.
