"""Unit tests for the subprocess wrapper. Mocks subprocess.run so tests don't
need the `claude` binary installed on the test machine."""
import json
from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase, tagged

from ..services.claude_cli import ClaudeCliBackend, ClaudeCliError


@tagged("post_install", "-at_install", "ai_claude_cli")
class TestClaudeCli(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ICP = cls.env["ir.config_parameter"].sudo()
        cls.ICP.set_param("ai_claude_cli.enabled", "True")
        cls.ICP.set_param("ai_claude_cli.binary_path", "/usr/local/bin/claude")
        cls.ICP.set_param("ai_claude_cli.model", "sonnet")
        cls.ICP.set_param("ai_claude_cli.timeout", "60")

    def _mock_run(self, stdout, returncode=0, stderr=""):
        m = MagicMock()
        m.stdout = stdout
        m.stderr = stderr
        m.returncode = returncode
        return m

    def test_parses_json_result_field(self):
        """Happy path: claude returns {'type':'result','result':'<text>'}, we return the text."""
        payload = {"type": "result", "subtype": "success", "result": "Hello world!"}
        with patch("os.path.exists", return_value=True), \
             patch("subprocess.run", return_value=self._mock_run(json.dumps(payload))):
            backend = ClaudeCliBackend(self.env)
            out = backend.call(prompt="hi")
        self.assertEqual(out, "Hello world!")

    def test_rejects_empty_prompt(self):
        backend = ClaudeCliBackend(self.env)
        with self.assertRaises(ClaudeCliError):
            backend.call(prompt="")

    def test_rejects_oversized_prompt(self):
        backend = ClaudeCliBackend(self.env)
        with self.assertRaises(ClaudeCliError) as cm:
            backend.call(prompt="x" * 60_000)
        self.assertIn("too large", str(cm.exception))

    def test_binary_missing_raises(self):
        self.ICP.set_param("ai_claude_cli.binary_path", "/nonexistent/claude")
        backend = ClaudeCliBackend(self.env)
        with patch("os.path.exists", return_value=False):
            with self.assertRaises(ClaudeCliError) as cm:
                backend.call(prompt="hi")
        self.assertIn("not found", str(cm.exception))

    def test_nonzero_exit_raises(self):
        with patch("os.path.exists", return_value=True), \
             patch("subprocess.run", return_value=self._mock_run("", returncode=1, stderr="boom")):
            backend = ClaudeCliBackend(self.env)
            with self.assertRaises(ClaudeCliError) as cm:
                backend.call(prompt="hi")
        self.assertIn("exited 1", str(cm.exception))
        self.assertIn("boom", str(cm.exception))

    def test_timeout_raises(self):
        import subprocess
        with patch("os.path.exists", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5)):
            backend = ClaudeCliBackend(self.env)
            with self.assertRaises(ClaudeCliError) as cm:
                backend.call(prompt="hi", timeout=5)
        self.assertIn("timed out", str(cm.exception))

    def test_plain_text_fallback(self):
        """Older CLI versions may ignore --output-format json and return plain text."""
        with patch("os.path.exists", return_value=True), \
             patch("subprocess.run", return_value=self._mock_run("Just text, not JSON\n")):
            backend = ClaudeCliBackend(self.env)
            out = backend.call(prompt="hi")
        self.assertEqual(out, "Just text, not JSON")

    def test_subprocess_called_with_shell_false(self):
        """Non-regression — make sure we never flip shell=True by accident."""
        payload = {"result": "ok"}
        with patch("os.path.exists", return_value=True), \
             patch("subprocess.run", return_value=self._mock_run(json.dumps(payload))) as m:
            backend = ClaudeCliBackend(self.env)
            backend.call(prompt="hi")
        kwargs = m.call_args.kwargs
        self.assertFalse(kwargs.get("shell", False), "shell=True would be a command-injection risk")
        self.assertTrue(isinstance(m.call_args.args[0], list), "command must be an args list, not a string")
