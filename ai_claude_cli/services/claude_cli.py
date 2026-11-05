"""Subprocess wrapper that turns the local `claude` CLI into a database-aware
Odoo assistant.

Instead of trying to parse a hand-rolled JSON action envelope from Claude,
we give it the `Bash(psql *)` tool scoped to ONLY psql commands and a system
prompt that tells it how to reach the Odoo database. Claude's agent loop then
runs whatever queries it needs and responds with natural language.

Why scoped `Bash(psql *)`:
    - `--allowed-tools "Bash(psql *)"` lets Claude run psql invocations only.
    - Anything else (rm, curl, other shell commands) is auto-denied.
    - `--permission-prompts none` means no interactive approval flow —
      disallowed tool calls fail silently without hanging the subprocess.

Security:
    - subprocess.run with shell=False + explicit arg list
    - timeout per call
    - prompt size cap
    - env minimal: HOME, PATH, LANG, PGPASSWORD (so psql can auth)
    - the odoo system user's PG password is read from the Odoo config at
      runtime (not hard-coded)
"""
import json
import logging
import os
import subprocess

_logger = logging.getLogger(__name__)

MAX_PROMPT_BYTES = 200_000
DEFAULT_BINARY = "/usr/local/bin/claude"
DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT = 120


DB_SYSTEM_PROMPT = """You are an Odoo 19 database assistant with direct access
to this PostgreSQL database via the `psql` command. The user is chatting with
you inside Odoo; answer questions by querying the database and reply in natural
language.

HOW TO QUERY (use the Bash tool with a psql command):
    psql -h 127.0.0.1 -p 5432 -U odoo -d {db_name} -c "SELECT ... FROM ... LIMIT 10"

The PGPASSWORD env var is already set, so you don't need `-W`.

KEY ODOO TABLES:
    res_partner        — contacts: customers, vendors, individuals
        key columns: id, name, email, phone, is_company, customer_rank, supplier_rank, country_id, create_date
        notes: customer_rank > 0 means they're a customer; is_company=true for businesses
    res_users          — login users (id, login, partner_id)
    account_move       — invoices, bills, journal entries
        key columns: id, name, move_type, state, partner_id, invoice_date, amount_total, currency_id
        move_type: 'out_invoice' = customer invoice, 'in_invoice' = vendor bill
        state: 'draft' | 'posted' | 'cancel'
    sale_order         — sales orders (id, name, partner_id, state, amount_total)
    purchase_order     — purchase orders
    product_product    — product variants (id, default_code, list_price, active)
    product_template   — product templates (name, sale_ok, type)
    crm_lead           — CRM leads
    res_company        — companies

RULES:
    1. Default LIMIT 20 on any SELECT that could return many rows.
    2. Use quoted table/column names only if needed (they're all snake_case).
    3. For "who is my X" type questions, SELECT a short list of relevant columns, not *.
    4. If you need a JSON-aggregated field (name_tsv, etc.), skip it.
    5. Never run DROP, TRUNCATE, or DELETE. For INSERT/UPDATE, confirm the
       intent in your reply so the user sees what you did.
    6. Reply in short, friendly English. If you found records, format a tidy
       list (not raw psql output).

Now answer the user's question."""


class ClaudeCliError(Exception):
    """Any failure in the subprocess call."""


class ClaudeCliBackend:
    def __init__(self, env):
        self.env = env
        p = env["ir.config_parameter"].sudo()
        self.binary_path = p.get_param("ai_claude_cli.binary_path") or DEFAULT_BINARY
        self.model = p.get_param("ai_claude_cli.model") or DEFAULT_MODEL
        try:
            self.timeout = int(p.get_param("ai_claude_cli.timeout") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT
        # Pull the DB name + PG password from the Odoo environment (not the config,
        # so this works regardless of how Odoo was launched)
        self.db_name = env.cr.dbname
        self.pg_user = env.cr._cnx.info.user
        self.pg_password = self._get_pg_password()

    def _get_pg_password(self):
        """Read PG password from Odoo's config object."""
        try:
            from odoo.tools import config as _cfg
            return _cfg.get("db_password") or ""
        except Exception:   # noqa: BLE001
            return ""

    def call(self, prompt, system_prompt=None, timeout=None, **_kwargs):
        """Run `claude -p` with Bash(psql *) tool access + DB-aware system prompt."""
        if not prompt:
            raise ClaudeCliError("Empty prompt.")
        encoded = prompt.encode("utf-8", errors="replace")
        if len(encoded) > MAX_PROMPT_BYTES:
            raise ClaudeCliError(
                f"Prompt too large ({len(encoded)} bytes > {MAX_PROMPT_BYTES} cap)."
            )
        if not os.path.exists(self.binary_path):
            raise ClaudeCliError(
                f"claude binary not found at {self.binary_path}."
            )

        # Compose the system prompt: our DB-aware block + whatever Odoo passed in.
        db_prompt = DB_SYSTEM_PROMPT.format(db_name=self.db_name)
        if system_prompt:
            full_system = db_prompt + "\n\n---\n\n" + system_prompt
        else:
            full_system = db_prompt

        cmd = [
            self.binary_path,
            "-p", prompt,
            "--model", self.model,
            "--output-format", "text",
            "--allowed-tools", "Bash(psql *)",
            "--permission-prompts", "none",
            "--append-system-prompt", full_system,
        ]

        # Sanitised env: HOME (for creds), PATH, LANG, PGPASSWORD for psql auth.
        env = {
            "HOME": os.environ.get("HOME", "/opt/odoo"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "PGPASSWORD": self.pg_password or "",
        }

        effective_timeout = timeout if timeout is not None else self.timeout
        _logger.info("claude_cli: calling %s (model=%s, timeout=%ss, db=%s, prompt_bytes=%s)",
                     self.binary_path, self.model, effective_timeout, self.db_name, len(encoded))

        try:
            result = subprocess.run(   # noqa: S603
                cmd, shell=False, text=True, capture_output=True,
                timeout=effective_timeout, env=env, check=False,
            )
        except subprocess.TimeoutExpired:
            raise ClaudeCliError(f"Claude CLI timed out after {effective_timeout}s.")
        except FileNotFoundError:
            raise ClaudeCliError(f"claude binary not executable at {self.binary_path}.")
        except Exception as e:   # noqa: BLE001
            raise ClaudeCliError(f"Subprocess failed: {e}")

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()[:500]
            raise ClaudeCliError(
                f"Claude CLI exited {result.returncode}: {stderr or '(no stderr)'}"
            )

        return (result.stdout or "").strip()
