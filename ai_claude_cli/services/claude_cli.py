"""Subprocess wrapper for the local `claude` CLI.

Security notes (read before touching this file):
  * subprocess.run with shell=False + explicit arg list — no command injection surface.
  * timeout enforced at the subprocess level — a hung CLI can't hang the Odoo worker.
  * env variables sanitised — we pass only what the CLI needs; secrets aren't leaked
    into the child process environment.
  * Prompt size capped — 50KB max per call to prevent runaway subprocess memory.
  * Runs as whatever user Odoo runs as. For the subscription to be found,
    ~/.claude/.credentials.json must exist and be readable by that user.
    One-time setup:  sudo -u odoo claude /login
"""
import json
import logging
import os
import subprocess

_logger = logging.getLogger(__name__)

MAX_PROMPT_BYTES = 50_000
DEFAULT_BINARY = "/usr/local/bin/claude"
DEFAULT_MODEL = "sonnet"
DEFAULT_TIMEOUT = 60


class ClaudeCliError(Exception):
    """Any failure in the subprocess call — missing binary, timeout, non-zero exit, parse fail."""


class ClaudeCliBackend:
    """Thin subprocess wrapper. Not an Odoo model — a plain service class
    instantiated per request so it reads fresh config parameters each time."""

    def __init__(self, env):
        self.env = env
        p = env["ir.config_parameter"].sudo()
        self.binary_path = p.get_param("ai_claude_cli.binary_path") or DEFAULT_BINARY
        self.model = p.get_param("ai_claude_cli.model") or DEFAULT_MODEL
        try:
            self.timeout = int(p.get_param("ai_claude_cli.timeout") or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT

    def call(self, prompt, system_prompt=None, timeout=None, **_kwargs):
        """Run `claude -p` and return the response as a plain string.

        :param prompt: The user prompt.
        :param system_prompt: Optional system prompt (prepended via --append-system-prompt).
        :param timeout: Per-call timeout override; falls back to configured default.
        """
        if not prompt:
            raise ClaudeCliError("Empty prompt.")

        encoded = prompt.encode("utf-8", errors="replace")
        if len(encoded) > MAX_PROMPT_BYTES:
            raise ClaudeCliError(
                f"Prompt too large ({len(encoded)} bytes > {MAX_PROMPT_BYTES} cap)."
            )

        if not os.path.exists(self.binary_path):
            raise ClaudeCliError(
                f"claude binary not found at {self.binary_path}. "
                "Set a correct path in Settings → AI → Path to claude binary, "
                "or install the CLI on the server."
            )

        # Build the command. shell=False, explicit args, no interpolation.
        cmd = [
            self.binary_path,
            "-p", prompt,
            "--model", self.model,
            "--output-format", "json",
            "--max-turns", "1",
        ]
        if system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])

        # Sanitise env. Preserve HOME so ~/.claude/.credentials.json resolves,
        # preserve PATH so any claude subprocess children work, drop everything else.
        env = {
            "HOME": os.environ.get("HOME", "/"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        }

        effective_timeout = timeout if timeout is not None else self.timeout
        _logger.info("claude_cli: calling %s (model=%s, timeout=%ss, prompt_bytes=%s)",
                     self.binary_path, self.model, effective_timeout, len(encoded))

        try:
            result = subprocess.run(  # noqa: S603 — args list, shell=False
                cmd,
                shell=False,
                text=True,
                capture_output=True,
                timeout=effective_timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise ClaudeCliError(f"Claude CLI timed out after {effective_timeout}s.")
        except FileNotFoundError:
            raise ClaudeCliError(f"claude binary not executable at {self.binary_path}.")
        except Exception as e:   # noqa: BLE001 — surface everything upstream
            raise ClaudeCliError(f"Subprocess failed: {e}")

        if result.returncode != 0:
            # Common failures: not authenticated, rate-limited, invalid model.
            stderr = (result.stderr or "").strip()[:500]
            raise ClaudeCliError(
                f"Claude CLI exited {result.returncode}: {stderr or '(no stderr)'}"
            )

        return self._parse_response(result.stdout)

    def _parse_response(self, stdout):
        """Claude CLI with --output-format json returns a JSON envelope. Extract the text."""
        if not stdout or not stdout.strip():
            raise ClaudeCliError("Claude CLI returned empty output.")

        # Try JSON first (our requested format)
        try:
            data = json.loads(stdout)
        except ValueError:
            # Not JSON — some older CLI versions dump plain text when --output-format
            # isn't fully respected. Return as-is.
            return stdout.strip()

        # Shape: {"type":"result","subtype":"success","result":"<text>",...}
        if isinstance(data, dict):
            if "result" in data and isinstance(data["result"], str):
                return data["result"]
            if "content" in data:   # some versions
                content = data["content"]
                if isinstance(content, str):
                    return content
                if isinstance(content, list) and content:
                    first = content[0]
                    if isinstance(first, dict) and "text" in first:
                        return first["text"]

        # Fallback — return the raw JSON as text so the user sees SOMETHING
        return json.dumps(data, indent=2)
