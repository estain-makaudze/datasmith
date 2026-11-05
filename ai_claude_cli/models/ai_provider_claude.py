"""Phase-2: route Odoo's native AI module (Ask AI drawer, Agents, etc.)
through the local `claude` CLI subprocess.

Odoo 19's ai module does not expose a `provider` ORM model — every LLM call
funnels through a utility class `odoo.addons.ai.utils.llm_api_service.LLMApiService`
whose `_request_llm` method dispatches by provider name ('openai' / 'google').

Clean inheritance is not possible against a plain Python utility class, so the
only option is a monkey-patch applied at module load time. We wrap `_request_llm`
to check the `ai_claude_cli.enabled` config parameter; when it is True, the
call is routed to our subprocess wrapper regardless of the provider Odoo thinks
it should use.

Return contract mirrors Odoo's `_request_llm_openai`:
    (responses: list[str], tool_calls: list, inputs: list)
"""
import logging

from odoo.addons.ai.utils import llm_api_service as _odoo_llm

_logger = logging.getLogger(__name__)

# Keep a reference to the original method so we can call it when the Claude
# routing is OFF (users may toggle the setting without restarting).
_original_request_llm = _odoo_llm.LLMApiService._request_llm


def _claude_cli_enabled(env) -> bool:
    try:
        return env["ir.config_parameter"].sudo().get_param("ai_claude_cli.enabled") == "True"
    except Exception:   # noqa: BLE001 — never fail the native path over our check
        return False


def _patched_request_llm(self, *args, **kwargs):
    """Intercept: if the admin ticked 'Use your own Claude subscription',
    route this call through our subprocess wrapper instead of OpenAI/Google."""
    if not _claude_cli_enabled(self.env):
        return _original_request_llm(self, *args, **kwargs)

    # Pull what we need from args/kwargs. Signature of the underlying
    # _request_llm_openai is: (llm_model, system_prompts, user_prompts, tools=None, ...)
    llm_model = kwargs.get("llm_model") or (args[0] if args else None)
    system_prompts = kwargs.get("system_prompts") or (args[1] if len(args) > 1 else [])
    user_prompts = kwargs.get("user_prompts") or (args[2] if len(args) > 2 else [])

    # Flatten to one prompt string for the CLI
    system_prompt = "\n\n".join(p for p in (system_prompts or []) if p) or None
    user_prompt = "\n\n".join(p for p in (user_prompts or []) if p) or ""

    _logger.info(
        "ai_claude_cli: intercepting native AI call (model=%s, system_len=%s, user_len=%s)",
        llm_model, len(system_prompt or ""), len(user_prompt),
    )

    from ..services.claude_cli import ClaudeCliBackend, ClaudeCliError
    backend = ClaudeCliBackend(self.env)
    try:
        text = backend.call(prompt=user_prompt or "Hello", system_prompt=system_prompt)
    except ClaudeCliError as e:
        from odoo.exceptions import UserError
        raise UserError(f"Claude CLI failed: {e}")

    # Return shape matches _request_llm_openai: (responses, tool_calls, inputs)
    return [text or ""], [], []


# Apply the patch once, at module load time.
if not getattr(_odoo_llm.LLMApiService._request_llm, "_patched_by_ai_claude_cli", False):
    _patched_request_llm._patched_by_ai_claude_cli = True
    _odoo_llm.LLMApiService._request_llm = _patched_request_llm
    _logger.info("ai_claude_cli: patched LLMApiService._request_llm — "
                 "native Odoo AI calls will route through Claude when enabled")
