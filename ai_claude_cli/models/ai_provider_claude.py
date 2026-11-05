"""Route Odoo's native AI module (Ask AI drawer, Agents, etc.) through the
local `claude` CLI subprocess, with lightweight tool-calling so Claude can
actually read and write records in the database.

Odoo 19's ai module funnels every LLM call through
`odoo.addons.ai.utils.llm_api_service.LLMApiService._request_llm`. Clean
inheritance is not possible against a plain Python utility class, so we
apply a monkey-patch at import time.

Tool-calling design (demo-grade, deliberately minimal):

    Odoo's native tool spec is complex (per-model, per-field, with validation
    hooks). Rewiring it through Claude's own tool-use protocol would need the
    Anthropic SDK + subscription-token exchange. For this demo we take a simpler
    route: we TEACH Claude via system prompt to emit a small JSON action
    envelope when the user asks to create/read/search/update a record. The patch
    parses that envelope, executes it against Odoo's ORM (so access rights,
    record rules, and validations all apply as normal), then does a SECOND
    Claude turn to let it frame the result in natural language.

    Supported actions:
      {"action": "search", "model": "<technical name>", "domain": [...], "fields": [...], "limit": N}
      {"action": "create", "model": "<technical name>", "values": {...}}
      {"action": "update", "model": "<technical name>", "id": N, "values": {...}}

    Anything else → plain text reply, straight through, no tools.
"""
import json
import logging
import re

from odoo.addons.ai.utils import llm_api_service as _odoo_llm

_logger = logging.getLogger(__name__)
_original_request_llm = _odoo_llm.LLMApiService._request_llm

# System-prompt extension that teaches Claude the action envelope.
# IMPORTANT: this is appended AFTER any native Odoo system prompt so it has
# the final say on behaviour. Any earlier "respond in plain English" guidance
# from Odoo's own prompt is explicitly overridden below.
_TOOL_PROMPT = """

=== TOOL-USE OVERRIDE (highest priority — overrides any prior instruction) ===

You have DIRECT WRITE ACCESS to this Odoo 19 database via a tool call layer.
You MUST use it whenever the user is asking for data or asking you to change data.
Ignore any earlier instruction that said to respond conversationally about what
you *could* do — you can actually do it, so do it.

TOOL CALL FORMAT — reply with ONLY a JSON object, nothing else, no prose, no
markdown fences, no explanation before or after:

  {"action": "search", "model": "res.partner", "domain": [["customer_rank",">",0]], "fields": ["name","email"], "limit": 20}
  {"action": "create", "model": "res.partner", "values": {"name":"Datasmith","is_company":true,"email":"info@datasmith.co.za"}}
  {"action": "update", "model": "res.partner", "id": 42, "values": {"email":"new@acme.com"}}
  {"action": "read", "model": "res.partner", "id": 42, "fields": ["name","email","phone"]}

WHEN TO USE A TOOL (always, not sometimes):
  - "list my customers" / "show me my contacts" / "who are my customers" → search action on res.partner
  - "create a customer called X" / "add a contact X" → create action on res.partner
  - "update X's email to Y" → update action on res.partner
  - "show me invoice 42" / "what invoices do I have" → search/read on account.move
  - Any question whose answer requires looking at the database → search action

Odoo technical model names:
  res.partner      — contacts (customers, vendors, employees — all one table; is_company flag separates them)
  res.users        — login users
  account.move     — invoices, bills, journal entries
  sale.order       — sales orders
  purchase.order   — purchase orders
  product.product  — products
  crm.lead         — CRM leads

Odoo domain syntax: a list of 3-tuples wrapped as JSON arrays — [["field","operator",value], ...]
Operators: =, !=, >, <, >=, <=, in, like, ilike. Pass [] for "everything".

ONLY respond in plain English when the user is chatting, greeting, or asking a question whose answer doesn't need database data (e.g. "what is Odoo?").

Default on ambiguity: USE THE TOOL. It's easier to narrow down afterwards than to leave the user without data.
"""

# Match Claude's bare-JSON output (strict: starts with { and ends with })
_JSON_RE = re.compile(r'^\s*(\{.*\})\s*$', re.DOTALL)


def _claude_cli_enabled(env) -> bool:
    try:
        return env["ir.config_parameter"].sudo().get_param("ai_claude_cli.enabled") == "True"
    except Exception:   # noqa: BLE001
        return False


def _extract_action(claude_text):
    """Parse Claude's reply. Returns a dict if it's a valid action envelope, else None."""
    if not claude_text:
        return None
    m = _JSON_RE.match(claude_text.strip())
    if not m:
        # Try to extract the first JSON object anywhere in the text (in case Claude added prose)
        start = claude_text.find("{")
        end = claude_text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None
        candidate = claude_text[start:end + 1]
    else:
        candidate = m.group(1)
    try:
        obj = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    if isinstance(obj, dict) and obj.get("action") in ("search", "create", "update", "read"):
        return obj
    return None


def _execute_action(env, action):
    """Execute an action envelope via Odoo ORM. Returns a short text description
    of the outcome (success summary OR error message) to feed back to Claude."""
    try:
        model_name = action.get("model")
        if not model_name:
            return "ERROR: action missing 'model' field."
        if model_name not in env:
            return f"ERROR: unknown model '{model_name}'."
        Model = env[model_name]

        verb = action["action"]
        if verb == "search":
            domain = action.get("domain") or []
            fields = action.get("fields") or ["display_name"]
            limit = int(action.get("limit") or 10)
            records = Model.search_read(domain, fields, limit=limit)
            if not records:
                return f"OK: searched {model_name} with domain={domain}. 0 records matched."
            return f"OK: searched {model_name}, {len(records)} record(s):\n{json.dumps(records, default=str, indent=2)}"

        if verb == "create":
            values = action.get("values") or {}
            if not values:
                return "ERROR: create action missing 'values'."
            rec = Model.create(values)
            return f"OK: created {model_name} #{rec.id} ({rec.display_name})."

        if verb == "update":
            rid = int(action.get("id", 0))
            values = action.get("values") or {}
            if not rid or not values:
                return "ERROR: update action needs both 'id' and 'values'."
            rec = Model.browse(rid)
            rec.write(values)
            return f"OK: updated {model_name} #{rid} ({rec.display_name})."

        if verb == "read":
            rid = int(action.get("id", 0))
            fields = action.get("fields") or ["display_name"]
            if not rid:
                return "ERROR: read action needs an 'id'."
            data = Model.browse(rid).read(fields)
            return f"OK: read {model_name} #{rid}:\n{json.dumps(data, default=str, indent=2)}"

        return f"ERROR: unsupported action '{verb}'."
    except Exception as e:   # noqa: BLE001 — surface any ORM error to Claude so it can retell naturally
        return f"ERROR: {type(e).__name__}: {e}"


def _patched_request_llm(self, *args, **kwargs):
    """Route to Claude subprocess when ai_claude_cli.enabled is True, otherwise
    delegate to the original method (OpenAI / Google path untouched)."""
    if not _claude_cli_enabled(self.env):
        return _original_request_llm(self, *args, **kwargs)

    llm_model = kwargs.get("llm_model") or (args[0] if args else None)
    system_prompts = kwargs.get("system_prompts") or (args[1] if len(args) > 1 else [])
    user_prompts = kwargs.get("user_prompts") or (args[2] if len(args) > 2 else [])

    native_system = "\n\n".join(p for p in (system_prompts or []) if p)
    # Our prompt goes LAST so it has the final word on behaviour. The native
    # Odoo prompt ("you are a helpful assistant", etc.) comes first; our
    # override explicitly disclaims any earlier "respond in English" rule.
    system_prompt = (native_system + _TOOL_PROMPT).strip() if native_system else _TOOL_PROMPT.strip()
    user_prompt = "\n\n".join(p for p in (user_prompts or []) if p) or "Hello"

    _logger.info(
        "ai_claude_cli: intercepting native AI call (model=%s, user_bytes=%s, tools_arg=%s)",
        llm_model, len(user_prompt), bool(kwargs.get("tools")),
    )

    from ..services.claude_cli import ClaudeCliBackend, ClaudeCliError
    backend = ClaudeCliBackend(self.env)

    try:
        first = backend.call(prompt=user_prompt, system_prompt=system_prompt)
    except ClaudeCliError as e:
        from odoo.exceptions import UserError
        raise UserError(f"Claude CLI failed: {e}")

    action = _extract_action(first)
    _logger.info(
        "ai_claude_cli: Claude first-turn response (first 300 chars): %s | action_parsed=%s",
        (first or "")[:300].replace("\n", "\\n"), bool(action),
    )
    if not action:
        # Plain text reply from Claude; return as-is.
        return [first or ""], [], []

    # It's a tool call — execute against Odoo, then do a second turn to let
    # Claude explain the result in natural language.
    _logger.info("ai_claude_cli: executing action %s on %s", action.get("action"), action.get("model"))
    result_text = _execute_action(self.env, action)

    followup_prompt = (
        f"The user asked: {user_prompt}\n\n"
        f"You chose this action:\n{json.dumps(action, indent=2)}\n\n"
        f"The Odoo database responded:\n{result_text}\n\n"
        f"Now reply to the user in natural, friendly language — confirm what happened and share the key fact "
        f"(e.g. the new record's id, or the names of what you found). Do NOT output JSON — this turn is prose only."
    )
    try:
        second = backend.call(prompt=followup_prompt, system_prompt=None)
    except ClaudeCliError as e:
        # Fall back to the raw action result if Claude fails on the second turn
        return [result_text], [], []
    return [second or result_text], [], []


# Idempotent apply — safe across module reloads.
if not getattr(_odoo_llm.LLMApiService._request_llm, "_patched_by_ai_claude_cli", False):
    _patched_request_llm._patched_by_ai_claude_cli = True
    _odoo_llm.LLMApiService._request_llm = _patched_request_llm
    _logger.info("ai_claude_cli: patched LLMApiService._request_llm — "
                 "native Odoo AI calls will route through Claude with tool-calling when enabled")
