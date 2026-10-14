#!/usr/bin/env python3
"""Offline bootstrap tests; synthetic interpreters, no pip download or real credentials."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import bootstrap as boot
import flow_api as api


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='flow-bootstrap-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'space and 中文' / 'venv'
        self.enter(patch.object(boot, 'runtime_dir', return_value=self.folder))
        self.enter(patch.object(boot.sys, 'platform', 'darwin'))
        self.enter(patch.dict(os.environ, {boot.SWITCHED: ''}))
        self.ready = self.enter(patch.object(boot, 'dependency_ready', return_value=False))
        self.run = self.enter(patch.object(boot, 'quiet_run', return_value=True))
        self.enter(contextlib.redirect_stderr(io.StringIO()))

    def enter(self, cm):
        result = cm.__enter__()
        self.addCleanup(cm.__exit__, None, None, None)
        return result

    def existing(self):
        self.folder.mkdir(parents=True)
        (self.folder / 'pyvenv.cfg').write_text('home = synthetic\n', encoding='utf-8')

    def test_current_dependency_avoids_all_setup(self):
        self.ready.return_value = True
        self.assertIsNone(boot.prepare_runtime())
        self.run.assert_not_called()
        self.assertFalse(self.folder.parent.exists())

    def test_reuses_existing_without_writes_or_pip(self):
        self.existing()
        with patch.object(boot.os, 'open', side_effect=PermissionError('write denied')) as opened, \
                patch.object(Path, 'mkdir', side_effect=PermissionError('write denied')) as mkdir:
            self.assertEqual(boot.prepare_runtime(), self.folder / 'bin/python')
        opened.assert_not_called()
        mkdir.assert_not_called()
        self.assertEqual(self.run.call_count, 2)
        self.assertFalse(any('install' in call.args[0] for call in self.run.call_args_list))

    def test_creates_then_installs_then_verifies(self):
        self.run.side_effect = [True, True, False, True, True, True]
        self.assertEqual(boot.prepare_runtime(), self.folder / 'bin/python')
        commands = [c.args[0] for c in self.run.call_args_list]
        self.assertIn('venv', commands[0])
        install = next(c for c in commands if 'install' in c)
        self.assertEqual(install[0], str(self.folder / 'bin/python'))
        self.assertIn(str(boot.ROOT / 'requirements.txt'), install)
        self.assertEqual(commands[-1][-2], '-c')

    def test_existing_without_dependency_is_repaired_without_recreation(self):
        self.existing()
        self.run.side_effect = [True, False, True, True, True]
        self.assertEqual(boot.prepare_runtime(), self.folder / 'bin/python')
        commands = [c.args[0] for c in self.run.call_args_list]
        self.assertFalse(any('venv' in c for c in commands))
        self.assertEqual(sum('install' in c for c in commands), 1)

    def test_missing_pip_uses_ensurepip_only_in_private_venv(self):
        self.existing()
        self.run.side_effect = [True, False, False, True, True, True]
        boot.prepare_runtime()
        commands = [c.args[0] for c in self.run.call_args_list]
        ensure = next(c for c in commands if 'ensurepip' in c)
        self.assertEqual(ensure[0], str(self.folder / 'bin/python'))

    def test_install_failure_stops_without_child_or_raw_output(self):
        self.existing()
        self.run.side_effect = [True, False, True, False]
        with patch.object(boot.subprocess, 'run') as child, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(boot.ensure_runtime(api.__file__, ['setup']), 2)
        child.assert_not_called()
        self.assertIn('No API was called', err.getvalue())
        self.assertFalse(json.loads(err.getvalue().splitlines()[-1])['executed'])

    def test_failed_verification_does_not_execute_business(self):
        self.existing()
        self.run.side_effect = [True, False, True, True, False]
        with patch.object(boot.subprocess, 'run') as child:
            self.assertEqual(boot.ensure_runtime(api.__file__, ['setup']), 2)
        child.assert_not_called()

    def test_broken_or_foreign_environment_is_preserved(self):
        self.folder.mkdir(parents=True)
        sentinel = self.folder / 'keep.txt'
        sentinel.write_text('keep', encoding='utf-8')
        with self.assertRaises(boot.BootstrapError):
            boot.prepare_runtime()
        self.run.assert_not_called()
        self.assertEqual(sentinel.read_text(), 'keep')
        (self.folder / 'pyvenv.cfg').write_text('home = missing', encoding='utf-8')
        self.run.return_value = False
        with self.assertRaises(boot.BootstrapError):
            boot.prepare_runtime()
        self.assertEqual(self.run.call_count, 1)
        self.assertTrue(sentinel.exists())

    def test_switch_guard_prevents_install_loop(self):
        with patch.dict(os.environ, {boot.SWITCHED: '1'}):
            with self.assertRaises(boot.BootstrapError):
                boot.prepare_runtime()
        self.run.assert_not_called()

    def test_switch_once_preserves_argv_cwd_stdin_and_failure_exit(self):
        args = ['--config', 'relative config.json', 'call', 'F040', '--data', '-', '--execute', '--allow-write']
        with patch.object(boot, 'prepare_runtime', return_value=self.folder / 'bin/python'), \
                patch.object(boot.subprocess, 'run', return_value=subprocess.CompletedProcess([], 4)) as child:
            self.assertEqual(boot.ensure_runtime(api.__file__, args), 4)
        child.assert_called_once()
        self.assertEqual(child.call_args.args[0][2:], args)
        self.assertEqual(set(child.call_args.kwargs), {'env'})
        self.assertEqual(child.call_args.kwargs['env'][boot.SWITCHED], '1')

    def test_linux_credentials_stop_without_install(self):
        with patch.object(boot.sys, 'platform', 'linux'):
            with self.assertRaises(boot.BootstrapError):
                boot.prepare_runtime()
        self.run.assert_not_called()

    def test_windows_uses_scripts_interpreter(self):
        with patch.object(boot.sys, 'platform', 'win32'):
            self.assertEqual(boot.runtime_python(self.folder), self.folder / 'Scripts/python.exe')

    def test_cli_preview_and_help_never_prepare(self):
        with patch.object(boot, 'ensure_runtime') as ensure, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(api.main(['call', 'F002'], auto_bootstrap=True), 0)
            self.assertEqual(api.main(['list'], auto_bootstrap=True), 0)
        ensure.assert_not_called()

    def test_setup_or_write_handoff_precedes_vault_network_and_stdin(self):
        class Unreadable:
            def read(self, *args):
                raise AssertionError('consumed stdin before bootstrap')
        with patch.object(boot, 'ensure_runtime', return_value=4) as ensure, \
                patch.object(api, 'system_vault') as vault, patch.object(api, 'send_once') as send, \
                patch('sys.stdin', Unreadable()), contextlib.redirect_stdout(io.StringIO()):
            argv = ['call', 'F040', '--data', '-', '--execute', '--allow-write']
            self.assertEqual(api.main(argv, auto_bootstrap=True), 4)
            self.assertEqual(ensure.call_args.args[1], argv)
            self.assertEqual(api.main(['setup'], auto_bootstrap=True), 4)
        vault.assert_not_called()
        send.assert_not_called()


@unittest.skipUnless(os.name == 'posix', 'POSIX launcher tests')
class LaunchProcessTest(unittest.TestCase):
    def test_launcher_preserves_bom_chinese_pipe_and_spaces(self):
        proc = subprocess.run(['sh', str(boot.ROOT / 'scripts/flow-api'), 'call', 'F002', '--data', '-'],
                              input='\ufeff{"comment":"中文 空格"}'.encode(), capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        self.assertEqual(json.loads(proc.stdout)['request']['tradeData']['comment'], '中文 空格')

    def test_missing_python_has_actionable_error_no_request(self):
        # Test a copied shell entrypoint with a PATH containing only dirname.
        with tempfile.TemporaryDirectory() as folder:
            launch = Path(folder) / 'flow-api'
            script = (boot.ROOT / 'scripts/flow-api').read_text()
            # Exclude the user's real fallback interpreter without changing HOME.
            script = script.replace('"$HOME/.config/bc-flow-api/venv/bin/python"', '"/nonexistent-flow-test-python"')
            launch.write_text(script)
            os.symlink('/usr/bin/dirname', Path(folder) / 'dirname')
            proc = subprocess.run(['/bin/sh', str(launch), 'setup'], capture_output=True,
                                  env=dict(os.environ, PATH=folder), timeout=10)
        self.assertEqual(proc.returncode, 2)
        self.assertIn(b'https://www.python.org/downloads/', proc.stderr)
        self.assertEqual(proc.stdout, b'')

    def test_real_child_handoff_preserves_pipe_and_never_retries_failure(self):
        with tempfile.TemporaryDirectory(prefix='flow handoff ') as folder:
            root = Path(folder)
            child = root / 'child.py'
            marker = root / 'calls.txt'
            child.write_text("import json,sys;from pathlib import Path;"
                             "p=Path(sys.argv[1]);p.open('a').write('once\\n');"
                             "print(json.dumps({'args':sys.argv[2:],'data':sys.stdin.buffer.read().decode('utf-8')}));"
                             "sys.exit(4)", encoding='utf-8')
            driver = ("import sys;sys.path.insert(0,sys.argv[1]);import bootstrap as b;"
                      "b.prepare_runtime=lambda:sys.executable;"
                      "sys.exit(b.ensure_runtime(sys.argv[2],sys.argv[3:]))")
            proc = subprocess.run([sys.executable, '-B', '-c', driver, str(boot.ROOT / 'scripts'),
                                   str(child), str(marker), '中文 参数', '--data', '-'],
                                  input='{"comment":"中文"}'.encode('utf-8'), capture_output=True, timeout=15)
            self.assertEqual(proc.returncode, 4, proc.stderr.decode('utf-8'))
            data = json.loads(proc.stdout)
            self.assertEqual(data['args'], ['中文 参数', '--data', '-'])
            self.assertEqual(json.loads(data['data'])['comment'], '中文')
            self.assertEqual(marker.read_text(), 'once\n')

    def test_quiet_setup_never_consumes_request_or_exposes_pip_errors(self):
        secret = 'synthetic-proxy-password'
        code = 'import sys; print("' + secret + '",file=sys.stderr); sys.exit(1)'
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertFalse(boot.quiet_run([sys.executable, '-c', code]))
        self.assertNotIn(secret, out.getvalue() + err.getvalue())



if __name__ == '__main__':
    unittest.main(verbosity=2)
