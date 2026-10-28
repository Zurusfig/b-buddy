"""Offline tests for dev.py (the setup helper). No network, no Ollama, no virtual environment is created.

    python -m unittest discover -s tests -v
"""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Harness" / "budget_coach"))

import dev  # noqa: E402


class FakeResponse:
    status = 200

    def __init__(self, payload=None):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *a):
        return json.dumps(self.payload).encode()


class VenvTests(unittest.TestCase):
    def test_finds_windows_and_unix_interpreters(self):
        for rel in ("Scripts/python.exe", "bin/python"):
            with self.subTest(rel):
                tmp = Path(tempfile.mkdtemp())
                (tmp / rel).parent.mkdir(parents=True)
                (tmp / rel).write_text("")
                self.assertEqual(dev.venv_python(tmp), tmp / rel)

    def test_no_venv_means_none_and_current_interpreter(self):
        self.assertIsNone(dev.venv_python(Path(tempfile.mkdtemp())))
        with mock.patch.object(dev, "venv_python", return_value=None):
            self.assertEqual(dev.project_python(), sys.executable)


class EnvFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = self.tmp / ".env"
        self.example = self.tmp / ".env.example"
        self.example.write_text("GATEWAY_KEY=sk-your-key-here\n")

    def test_key_status_variants(self):
        self.assertEqual(dev.key_status(self.env, {}), "missing")
        self.env.write_text("GATEWAY_KEY=sk-your-key-here\n")
        self.assertEqual(dev.key_status(self.env, {}), "placeholder")
        self.env.write_text('GATEWAY_KEY="sk-real"\n')
        self.assertEqual(dev.key_status(self.env, {}), "file")
        self.assertEqual(dev.key_status(self.env, {"GATEWAY_KEY": "x"}), "environment")
        self.env.write_text("GATEWAY_KEY=\n")
        self.assertEqual(dev.key_status(self.env, {}), "missing")

    def test_read_key_strips_quotes_and_never_needs_printing(self):
        self.env.write_text("OTHER=1\nGATEWAY_KEY='abc'\n")
        self.assertEqual(dev.read_key(self.env), "abc")

    def test_ensure_env_creates_once_and_never_overwrites(self):
        self.assertEqual(dev.ensure_env(self.env, self.example), "created")
        self.env.write_text("GATEWAY_KEY=mine\n")
        self.assertEqual(dev.ensure_env(self.env, self.example), "exists")
        self.assertEqual(self.env.read_text(), "GATEWAY_KEY=mine\n")


class OllamaTests(unittest.TestCase):
    def test_models_parsed_from_tags(self):
        opener = mock.Mock(return_value=FakeResponse({"models": [{"name": "qwen3:4b-q4_K_M"}]}))
        self.assertEqual(dev.ollama_models("http://x", opener), ["qwen3:4b-q4_K_M"])

    def test_unreachable_server_is_none(self):
        opener = mock.Mock(side_effect=urllib.error.URLError("refused"))
        self.assertIsNone(dev.ollama_models("http://x", opener))

    def test_find_ollama_prefers_path_then_install_folder(self):
        with mock.patch.object(dev.shutil, "which", return_value="/bin/ollama"):
            self.assertEqual(dev.find_ollama(), "/bin/ollama")
        tmp = Path(tempfile.mkdtemp())
        exe = tmp / "Programs" / "Ollama" / "ollama.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        with mock.patch.object(dev.shutil, "which", return_value=None), \
                mock.patch.dict(dev.os.environ, {"LOCALAPPDATA": str(tmp)}):
            self.assertEqual(dev.find_ollama(), str(exe))


class GatewayTests(unittest.TestCase):
    def test_statuses(self):
        self.assertEqual(dev.gateway_status("k", opener=mock.Mock(return_value=FakeResponse()))[0], "ok")
        err = lambda code: urllib.error.HTTPError("u", code, "m", {}, io.BytesIO(b""))
        self.assertEqual(dev.gateway_status("k", opener=mock.Mock(side_effect=err(401)))[0], "rejected")
        self.assertEqual(dev.gateway_status("k", opener=mock.Mock(side_effect=err(404)))[0], "unknown")
        self.assertEqual(dev.gateway_status("k", opener=mock.Mock(side_effect=OSError("down")))[0], "unreachable")

    def test_key_is_sent_only_in_the_authorization_header(self):
        opener = mock.Mock(return_value=FakeResponse())
        dev.gateway_status("secret", opener=opener)
        req = opener.call_args.args[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer secret")
        self.assertNotIn("secret", req.full_url)

    def test_constants_match_the_agent(self):
        import agent
        import router
        self.assertEqual(dev.GATEWAY_URL, agent.GATEWAY_URL)
        self.assertEqual(dev.SMALL_MODEL, router.CLASSIFIER_MODEL)
        self.assertEqual(dev.PLACEHOLDER_KEY, "sk-your-key-here")
        self.assertIn(dev.PLACEHOLDER_KEY, dev.ENV_EXAMPLE.read_text())


class CommandTests(unittest.TestCase):
    def call(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = dev.main(argv)
        return code, out.getvalue()

    def test_help_and_unknown_command(self):
        code, out = self.call(["help"])
        self.assertEqual(code, 0)
        self.assertIn("python dev.py setup", out)
        code, out = self.call(["nope"])
        self.assertEqual(code, 2)
        self.assertIn("unknown command", out)

    def test_every_documented_command_exists(self):
        for name in ("setup", "check", "test", "pull", "ask", "persona", "eval", "eval-persona",
                     "eval-gateway", "clean"):
            self.assertIn(name, dev.COMMANDS)

    def test_ask_forwards_question_and_flags_to_agent(self):
        with mock.patch.object(dev, "run", return_value=0) as run:
            dev.cmd_ask(["How", "much", "food?", "--compare"])
        cmd = run.call_args.args[0]
        self.assertEqual(cmd[1:], ["agent.py", "How much food?", "--compare"])
        self.assertEqual(run.call_args.kwargs["cwd"], dev.COACH)

    def test_persona_and_eval_commands_run_in_the_coach_folder(self):
        with mock.patch.object(dev, "run", return_value=0) as run:
            dev.cmd_persona(["--user", "3", "q"])
            self.assertEqual(run.call_args.args[0][1:], ["persona_agent.py", "--user", "3", "q"])
            dev.COMMANDS["eval-persona"](["--users", "1"])
            self.assertEqual(run.call_args.args[0][1:], ["eval_persona.py", "--users", "1"])
            self.assertEqual(run.call_args.kwargs["cwd"], dev.COACH)

    def test_pull_without_ollama_explains_what_to_do(self):
        with mock.patch.object(dev, "find_ollama", return_value=None):
            code, out = self.call(["pull"])
        self.assertEqual(code, 1)
        self.assertIn(dev.OLLAMA_DOWNLOAD, out)

    def test_pull_all_pulls_the_three_harness_models(self):
        with mock.patch.object(dev, "find_ollama", return_value="ollama"), \
                mock.patch.object(dev, "ollama_models", return_value=[]), \
                mock.patch.object(dev, "run", return_value=0) as run:
            self.call(["pull", "--all"])
        self.assertEqual([c.args[0][2] for c in run.call_args_list], list(dev.HARNESS_MODELS))

    def test_check_reports_a_missing_package_as_failure(self):
        with mock.patch.object(dev, "deps_ok", return_value=False), \
                mock.patch.object(dev, "find_ollama", return_value=None), \
                mock.patch.object(dev, "ollama_models", return_value=None):
            code, out = self.call(["check"])
        self.assertEqual(code, 1)
        self.assertIn("python dev.py setup", out)

    def test_check_never_prints_the_key(self):
        with mock.patch.object(dev, "deps_ok", return_value=True), \
                mock.patch.object(dev, "find_ollama", return_value=None), \
                mock.patch.object(dev, "ollama_models", return_value=None), \
                mock.patch.object(dev, "read_key", return_value="sk-super-secret"), \
                mock.patch.dict(dev.os.environ, {"GATEWAY_KEY": "sk-super-secret"}), \
                mock.patch.object(dev, "gateway_status", return_value=("ok", "HTTP 200")):
            code, out = self.call(["check", "--gateway"])
        self.assertEqual(code, 0)
        self.assertNotIn("sk-super-secret", out)

    def test_setup_fails_cleanly_on_an_old_python(self):
        with mock.patch.object(dev.sys, "version_info", (3, 8, 0)):
            code, out = self.call(["setup"])
        self.assertEqual(code, 1)
        self.assertIn("Python 3.10+", out)


if __name__ == "__main__":
    unittest.main()
