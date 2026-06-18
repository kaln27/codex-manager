# Codex Manager

Local tools for managing Codex provider files, sessions, and environment variables.

This repository contains two interfaces:

- Web UI: provider profile switching, session management, and `.env` editing.
- TUI: terminal session manager for changing or deleting selected Codex sessions.

Frontend assets live in `codex_manager/dist/`:

- `index.html`
- `styles.css`
- `app.js`

## Run Web UI

By default, the Web UI has no password. Set one before exposing it beyond your own machine.

Use an environment variable:

```bash
CODEX_MANAGER_PASSWORD='your-password' conda run -n llm python codex_manager/app.py
```

Or create a local password file:

```bash
printf '%s\n' 'your-password' > codex_manager/.manager_password
conda run -n llm python codex_manager/app.py
```

`codex_manager/.manager_password` is ignored by git.

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

## Run TUI

The TUI opens directly in the terminal and does not require arguments:

```bash
conda run -n llm python codex_manager/codex_session_manager.py
```

It supports selecting Codex sessions, inspecting session detail, changing the model provider, and deleting selected sessions. The official OpenAI provider name is `openai`.

## Data

- Provider profiles are stored under `codex_manager/provider_profiles/`.
- Switching providers replaces `~/.codex/config.toml` and `~/.codex/auth.json`.
- Provider switching does not automatically create file backups. The Web UI can save the current provider as a named profile before switching.
- Session provider edits, session deletion, and `.env` saves create backups under `~/.codex/*_backups/`.
- Sessions are loaded from `~/.codex/state_5.sqlite` and their matching jsonl rollout files.
- Env values are saved to `~/.codex/.env`, one `KEY=VALUE` pair per line.
