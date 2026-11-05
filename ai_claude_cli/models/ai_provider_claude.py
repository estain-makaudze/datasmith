"""Route Odoo 19's native AI module (Ask AI drawer, Agents, etc.) through the
local `claude` CLI subprocess with scoped psql access.

Odoo 19's ai module funnels every LLM call through
`odoo.addons.ai.utils.llm_api_service.LLMApiService._request_llm`. We monkey-patch
that method so when the admin has ticked "Use your own Claude subscription",
calls go to our subprocess wrapper instead of OpenAI/Google.

Design (post-pivot 2026-11-05):
    Rather than try to parse a hand-rolled JSON action envelope from Claude
    (fighting Odoo's native prompt structure), we hand Claude a `Bash(psql *)`
    tool scoped to only psql commands + a system prompt describing the Odoo
    database schema. Claude's agent loop runs whatever queries it needs and
    responds in natural language.

    The subprocess wrapper (services/claude_cli.py) holds the psql + schema
    knowledge; this file just plumbs Odoo's args/kwargs into it.
"""
import logging

from odoo.addons.ai.utils import llm_api_service as _odoo_llm

_logger = logging.getLogger(__name__)
_original_request_llm = _odoo_llm.LLMApiService._request_llm


def _claude_cli_enabled(env) -> bool:
    try:
        return env["ir.config_parameter"].sudo().get_param("ai_claude_cli.enabled") == "True"
    except Exception:   # noqa: BLE001
        return False


def _flatten_inputs(inp_list):
    """Odoo's Ask AI drawer passes the user conversation in Gemini-style
    inputs: [{'role':'user','parts':[{'text':'...'}]}, ...].
    Flatten to one plain-text string so Claude sees the whole thread."""
    pieces = []
    for item in inp_list or []:
        if isinstance(item, str):
            pieces.append(item)
            continue
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or "user").lower()
        if isinstance(item.get("parts"), list):
            for p in item["parts"]:
                if isinstance(p, dict) and "text" in p:
                    pieces.append(f"[{role}] {p['text']}")
                elif isinstance(p, str):
                    pieces.append(f"[{role}] {p}")
        elif "content" in item:
            c = item["content"]
            if isinstance(c, list):
                for ci in c:
                    txt = ci.get("text") if isinstance(ci, dict) else str(ci)
                    if txt:
                        pieces.append(f"[{role}] {txt}")
            else:
                pieces.append(f"[{role}] {c}")
        elif item.get("text"):
            pieces.append(f"[{role}] {item['text']}")
    return [p for p in pieces if p and p.strip()]


def _patched_request_llm(self, *args, **kwargs):
    if not _claude_cli_enabled(self.env):
        return _original_request_llm(self, *args, **kwargs)

    llm_model = kwargs.get("llm_model") or (args[0] if args else None)
    system_prompts = kwargs.get("system_prompts") or (args[1] if len(args) > 1 else [])
    user_prompts = kwargs.get("user_prompts") or (args[2] if len(args) > 2 else [])
    inputs = kwargs.get("inputs") or []

    flat_inputs = _flatten_inputs(inputs)
    native_system = "\n\n".join(p for p in (system_prompts or []) if p)

    # Build the user prompt from whatever Odoo gave us. Prefer the flattened
    # inputs (contains the real chat history + session context) over the
    # usually-stub user_prompts list.
    if flat_inputs:
        user_prompt = "\n\n".join(flat_inputs)
    elif user_prompts:
        user_prompt = "\n\n".join(user_prompts)
    else:
        user_prompt = "Hello"

    _logger.info(
        "ai_claude_cli: routing to Claude CLI (model=%s, user_prompt_bytes=%s, inputs=%d, has_system=%s)",
        llm_model, len(user_prompt), len(flat_inputs), bool(native_system),
    )

    from ..services.claude_cli import ClaudeCliBackend, ClaudeCliError
    backend = ClaudeCliBackend(self.env)
    try:
        text = backend.call(prompt=user_prompt, system_prompt=native_system or None)
    except ClaudeCliError as e:
        from odoo.exceptions import UserError
        raise UserError(f"Claude CLI failed: {e}")

    # Return shape matches _request_llm_openai: (responses, tool_calls, inputs)
    return [text or ""], [], []


if not getattr(_odoo_llm.LLMApiService._request_llm, "_patched_by_ai_claude_cli", False):
    _patched_request_llm._patched_by_ai_claude_cli = True
    _odoo_llm.LLMApiService._request_llm = _patched_request_llm
    _logger.info("ai_claude_cli: patched LLMApiService._request_llm — "
                 "native Odoo AI now routes to Claude CLI with Bash(psql *) tool access")
