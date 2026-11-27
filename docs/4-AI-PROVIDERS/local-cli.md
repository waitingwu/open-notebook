# Local AI CLIs (Claude Code and Codex)

Open Notebook can answer through the **Claude Code** or **Codex** command-line tool you already use on the same computer. It runs the CLI as a subprocess, and the CLI uses its own login: your Claude subscription (`claude auth login`) or your ChatGPT sign-in (`codex login`). Open Notebook never reads, stores or forwards those credentials, and it never switches to a paid API when the CLI fails.

These are **language-model** providers. They are tested with source chat and notebook chat; Ask and transformations call models the same way but have not been tested with them yet. Embeddings, speech-to-text and text-to-speech still need a regular provider (for example Ollama for local embeddings).

> Check that your use fits the terms of your Claude or ChatGPT plan. This integration only automates a CLI you run yourself, on your own machine.

## Requirements

- Open Notebook's **API runs natively on the same machine** as the CLIs, not in Docker. A container cannot see the CLIs installed on the host or their login. Follow [Development Setup](../7-DEVELOPMENT/development-setup.md) to run it from source. SurrealDB can run in Docker or natively (`surreal start --user root --pass root rocksdb:./surreal_data/db`).
- macOS or Linux. Windows is untested.
- At least one of:
  - Claude Code 2.x on `PATH`, logged in: `claude auth login`, check with `claude auth status`
  - Codex CLI on `PATH`, logged in: `codex login`, check with `codex login status`

If the API cannot find a CLI that works in your terminal (common when the API is started by a GUI or a service manager), it asks your login shell (`$SHELL -lc 'command -v claude'`). You can also set an absolute path with `OPEN_NOTEBOOK_CLAUDE_PATH` or `OPEN_NOTEBOOK_CODEX_PATH`.

## Set up

1. Open **Manage → AI Runtime & Audit**. The **Local AI CLIs** card shows each CLI's path, version and login state. If one says **Not logged in**, run the command it shows in a terminal and click **Re-check**.
2. Click **Add model**. `default` uses whatever model the CLI is configured to use. For Claude Code you can also enter `sonnet`, `opus`, `haiku` or a full model ID; for Codex, a model name the CLI accepts.
3. Click **Test** next to the model. It sends "Reply with exactly: OK" through the CLI.
4. Use the model:
   - **Manage → Models → Default models**: pick it as the chat model, or
   - in a source or notebook chat, click the model button under the conversation and pick **Claude Code · default** or **Codex · default** for that session.

Answers stream token by token in source chat. Notebook chat shows the whole answer when it is done, as it does for every provider.

## What runs, and how it is locked down

| | Claude Code | Codex |
|---|---|---|
| Command | `claude -p --output-format stream-json --verbose --include-partial-messages` | `codex app-server --listen stdio://` (JSON-RPC) |
| Tools | none (`--tools ""`) | read-only sandbox, approvals declined |
| MCP servers | none (`--strict-mcp-config`) | the CLI's own configuration |
| Your hooks and plugins | not loaded (`--setting-sources project` in an empty temp dir) | n/a |
| Working directory | empty temp dir, deleted afterwards | empty temp dir, deleted afterwards |
| Session history | not saved (`--no-session-persistence`) | ephemeral thread |

The prompt, which includes the source text, goes to the CLI over stdin or a temp file. It never appears in the process arguments, which other local users could see with `ps`. The CLI then sends it to Anthropic or OpenAI, exactly as when you use the CLI yourself.

Set `OPEN_NOTEBOOK_LOCAL_CLI_TIMEOUT` (seconds, default 600) to change how long a run may take.

## Errors

| Message | Cause | Fix |
|---|---|---|
| *… is not logged in. Run `claude auth login` / `codex login` …* | The CLI has no valid login | Run the command, then **Re-check** |
| *… usage limit has been reached* | Your subscription's rate limit | Wait for the reset time shown under **Subscription limits** |
| *… was not found on this machine* | The CLI is not on the API's `PATH` | Install it, or set `OPEN_NOTEBOOK_CLAUDE_PATH` / `OPEN_NOTEBOOK_CODEX_PATH` |
| *Could not read … output (unsupported CLI version?)* | A CLI update changed its output format | Update Open Notebook, or pin the previous CLI version |
| *… did not finish in time* | The run was longer than the timeout | Raise `OPEN_NOTEBOOK_LOCAL_CLI_TIMEOUT` |

Every failure is also recorded in the audit log with its reason.

## Audit log

**Manage → AI Runtime & Audit** records every chat-model call, from any provider:

- **Runs**: provider, model, feature, status and failure reason, duration, time to first token, token usage (input including cache, output, cache read and write, reasoning), CLI version and auth mode, and the lifecycle events of the run.
- **Usage**: tokens per day, by model and by feature for the last 7, 30 or 90 days, and an **API-equivalent cost (estimate)**. A subscription does not bill per token. Claude Code reports its own list-price figure; for other models, enter USD-per-1M-token rates under **Retention & export**. Runs without a rate show "—".
- **Subscription limits**: the latest rate-limit snapshot each CLI reported: Claude's 5-hour and 7-day windows, and Codex's plan, limits and credits.
- **Retention & export**: run events are kept 30 days, runs and usage 365 days by default; clean-up runs daily and on demand. Export to CSV or JSON, or delete everything.

**What is never stored:** prompts, source text, answers and credentials. The log keeps lengths, a SHA-256 of the prompt, and source and notebook IDs. Error text is masked for secret-shaped strings (API keys, tokens, emails) and cut to its last 2 KB. Deleting a notebook removes its run events and detaches its runs, so the token totals remain.

## For developers

- Code: `open_notebook/ai/local_cli/` (detection, runners, protocol parsing, LangChain model) and `open_notebook/audit/` (recorder, service, redaction, pricing); APIs in `api/routers/local_cli.py` and `api/routers/audit.py`; migration 29.
- Parser regression tests replay sanitized real CLI recordings from `tests/fixtures/local_cli/`. When a CLI release changes its output, record a new sample, sanitize it and add a test case (`tests/test_local_cli.py`).
