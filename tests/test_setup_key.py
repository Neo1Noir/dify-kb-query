import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
import warnings
from unittest.mock import MagicMock, patch

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "skills/dify-kb-query/scripts"
sys.path.insert(0, str(SCRIPTS))
import kb_query as kb
import setup_key as setup


class SetupKeyTests(unittest.TestCase):
    def setUp(self):
        self.stored = {}
        self.registry = MagicMock()
        self.registry.REG_SZ = 1
        def read(handle, name):
            if name not in self.stored:
                raise FileNotFoundError()
            return self.stored[name], 1
        self.registry.QueryValueEx.side_effect = read
        self.registry.SetValueEx.side_effect = lambda handle, name, reserved, kind, value: self.stored.update({name: value})
        for ctx in (patch.dict(sys.modules, {"winreg": self.registry}),
                    patch.dict(os.environ, {}, clear=True), patch.object(sys, "platform", "win32")):
            ctx.start()
            self.addCleanup(ctx.stop)

    def cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = setup.main(args)
        return code, out.getvalue() + err.getvalue()

    def test_status_never_discloses_key_or_writes(self):
        self.stored['DIFY_KB_API_KEY'] = 'dataset-secret-for-test'
        code, text = self.cli(['--status'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text), {'configured': True, 'persistent_user_variable': True, 'source': 'windows_user'})
        self.assertNotIn('dataset-secret-for-test', text)
        self.registry.SetValueEx.assert_not_called()

    def test_existing_saved_key_never_reprompts_or_overwrites(self):
        self.stored['DIFY_KB_API_KEY'] = 'dataset-saved-key'
        with patch.object(setup.getpass, 'getpass', side_effect=AssertionError('prompt')):
            self.assertEqual(self.cli([])[0], 0)
        self.registry.SetValueEx.assert_not_called()

    def test_first_setup_survives_loss_of_process_environment(self):
        key = 'dataset-hidden-input-key'
        with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(setup.getpass, 'getpass', return_value=key):
            code, text = self.cli([])
        self.assertEqual(code, 0)
        self.assertNotIn(key, text)
        self.assertEqual(set(self.stored), {'DIFY_KB_API_KEY'})
        os.environ.pop('DIFY_KB_API_KEY')
        self.assertEqual(kb.get_api_key(), key)
        self.registry.CreateKeyEx.assert_called_once_with(self.registry.HKEY_CURRENT_USER, 'Environment', 0, self.registry.KEY_SET_VALUE)

    def test_noninteractive_input_is_refused_before_read_or_write(self):
        with patch.object(sys.stdin, 'isatty', return_value=False), patch.object(setup.getpass, 'getpass') as prompt:
            self.assertEqual(self.cli([])[0], 2)
            prompt.assert_not_called()
        self.registry.SetValueEx.assert_not_called()

    def test_noecho_failure_does_not_fall_back_to_visible_input(self):
        def unavailable(prompt):
            warnings.warn('No echo unavailable', setup.getpass.GetPassWarning)
            raise AssertionError('must not fall back to plaintext input')
        with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(setup.getpass, 'getpass', side_effect=unavailable):
            self.assertEqual(self.cli([])[0], 2)
        self.registry.SetValueEx.assert_not_called()

    def test_explicit_replace_changes_only_named_user_variable(self):
        self.stored['DIFY_KB_API_KEY'] = 'old-key'
        with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(setup.getpass, 'getpass', return_value='new-key'):
            code, text = self.cli(['--replace'])
        self.assertEqual(code, 0)
        self.assertEqual(self.stored, {'DIFY_KB_API_KEY': 'new-key'})
        self.assertNotIn('new-key', text)

    def test_invalid_input_and_cancel_do_not_write(self):
        for value in ('', 'key with spaces', 'key\r\ninjected', '\u975eASCII'):
            with self.subTest(value=value), patch.object(sys.stdin, 'isatty', return_value=True), \
                    patch.object(setup.getpass, 'getpass', return_value=value):
                self.assertEqual(self.cli([])[0], 2)
        with patch.object(sys.stdin, 'isatty', return_value=True), patch.object(setup.getpass, 'getpass', side_effect=KeyboardInterrupt):
            self.assertEqual(self.cli([])[0], 2)
        self.registry.SetValueEx.assert_not_called()

    def test_process_only_key_requires_user_choice_before_persistence(self):
        os.environ['DIFY_KB_API_KEY'] = 'process-only-key'
        with patch.object(sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='n'):
            self.assertEqual(self.cli([])[0], 0)
        self.registry.SetValueEx.assert_not_called()
        with patch.object(sys.stdin, 'isatty', return_value=True), patch('builtins.input', return_value='y'):
            code, text = self.cli([])
        self.assertEqual(code, 0)
        self.assertEqual(self.stored['DIFY_KB_API_KEY'], 'process-only-key')
        self.assertNotIn('process-only-key', text)

    def test_unsupported_platform_does_not_claim_persistence(self):
        with patch.object(sys, 'platform', 'linux'):
            self.assertEqual(self.cli([])[0], 2)
        self.registry.SetValueEx.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
