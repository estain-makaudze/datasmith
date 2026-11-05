# AI: Claude CLI Backend — Odoo 19

Author: **Estain Makaudze** · estainmakaudze@gmail.com

Adds a third provider to **Settings → AI → Providers** (alongside "Use your
own ChatGPT account" and "Use your own Google Gemini account"):

> **Use your own Claude subscription**
>
> Route Odoo AI through the local `claude` CLI — your Claude Code / Claude
> Max subscription — instead of an API key.

Zero new UI. Zero new models. Pure inheritance on Odoo 19's `ai.provider`
dispatcher, plus one `res.config.settings` extension and one subprocess
wrapper. Every Odoo AI feature that was going to hit the OpenAI or Gemini
endpoints (Ask AI drawer, Agents, Pivot/chart suggestions, the full
Enterprise AI surface) now routes through Claude.

## Why this exists

| | API-key providers | Claude CLI backend |
|---|---|---|
| Billing model | Per-token, per-call | Flat monthly subscription |
| Cost for 20 users × 10 calls/day | ~$30–150/month | $0 (already paying for Claude) |
| API key management | Keys in Odoo settings | No keys — uses local `~/.claude/.credentials.json` |
| Data residency | Leaves to provider's cloud | Still leaves to Anthropic, but via the same channel your Claude subscription already uses |
| Setup | Paste key | Install CLI once + login once |

## For the code reviewer — start here

1. **`models/ai_provider_claude.py`** — the inheritance hook on Odoo's `ai.provider`.
   `_get_enabled_providers()` adds `'claude_cli'` to the list when the setting is on;
   `_dispatch()` routes `provider=='claude_cli'` to `_call_claude_cli()`.
2. **`services/claude_cli.py`** — the subprocess wrapper. Security notes at the top:
   `shell=False`, explicit arg list, timeout, prompt size cap, env sanitised.
3. **`views/res_config_settings_views.xml`** — the Settings UI extension. Inherits
   Odoo's `ai.res_config_settings_view_form` and inserts a third `<setting>` block.
4. **`tests/test_claude_cli.py`** — mocks `subprocess.run` so tests pass without the
   CLI installed; covers happy path, missing binary, non-zero exit, timeout, oversized
   prompt, and the non-regression test that `shell=False` is enforced.

## Prerequisites

The `claude` CLI must be installed on the Odoo server and readable by the Odoo
system user (typically `odoo`).

```bash
# One-time setup on the Odoo server, as the Odoo user:
sudo -u odoo claude /login             # browser auth, seeds ~odoo/.claude/.credentials.json
sudo -u odoo claude -p "say OK"        # confirms the subscription works
```

Install path (default): `/usr/local/bin/claude`. If it's elsewhere, set the full
path in Settings → AI → "Path to claude binary".

## Install

```bash
cd /path/to/odoo/addons
ln -s /path/to/zimpreneur-datasmith/ai_claude_cli .
./odoo-bin -d <db> -i ai_claude_cli
```

Requires Odoo 19 **Enterprise** (the `ai` module being extended is Enterprise-only).

## Enabling

1. Settings → AI → Providers
2. Tick **Use your own Claude subscription**
3. Confirm the path to the `claude` binary (default: `/usr/local/bin/claude`)
4. Click **Test Claude connection** — should go green with a response from Claude
5. Save

Every Odoo AI feature now uses Claude.

## Mutual exclusion vs the other providers

When the Claude CLI provider is enabled, it takes priority over OpenAI and Gemini.
The other providers' settings are not altered — turn Claude off and the previous
provider takes over again. This matches Odoo's existing "pick one" pattern on
the Providers screen.

## Security notes

- Subprocess invoked via `subprocess.run(args_list, shell=False, …)` — no command injection surface.
- Explicit timeout (default 60s) — a hung CLI can't hang the Odoo worker.
- Prompt size capped at 50 KB per call — prevents runaway memory on the subprocess.
- Env vars sanitised — only HOME, PATH, LANG passed to the child; secrets in the
  Odoo process environment are NOT inherited.
- The `claude` subprocess runs as the Odoo system user, so `~odoo/.claude/.credentials.json`
  must be chmod 600 and owned by that user. **One privilege boundary, not two.**

## Tests

```bash
./odoo-bin -d <db> -i ai_claude_cli --test-enable --test-tags ai_claude_cli --stop-after-init
```

Covers: JSON response parsing, empty / oversized prompt rejection, missing binary,
non-zero exit, subprocess timeout, plain-text fallback for older CLI versions,
and the non-regression assertion that `shell=False` is always enforced.

## What this module intentionally does NOT do

Deferred to Phase 2:

- Streaming responses (would need Odoo bus / SSE wiring; for now blocks until Claude replies)
- Multi-turn ACP persistent sessions (one subprocess per call; ~2s startup overhead)
- Tool use (agent calling Odoo methods to fetch data)
- Fallback chain (if Claude fails, fall back to OpenAI/Gemini)

Each is a one-conversation extension.

## License

LGPL-3. See `../LICENSE`.
