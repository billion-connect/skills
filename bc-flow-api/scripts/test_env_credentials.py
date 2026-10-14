#!/usr/bin/env python3
"""Local .env credentials: isolated files, synthetic secrets, no external API calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

import bootstrap
import flow_api as api


class EnvCredentialsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='flow-env-test-')
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'private' / 'profiles.json'
        self.key = 'synthetic-env-key'
        self.secret = 'synthetic-中文-#=$PATH-"-\\-secret'
        for target in ('system_vault', 'send_once'):
            p = patch.object(api, target)
            setattr(self, target, p.start())
            self.addCleanup(p.stop)
        self.system_vault.side_effect = AssertionError('must not access native vault')
        self.send_once.return_value = (200, b'{"tradeCode":"1000"}')
        p = patch.object(bootstrap, 'ensure_runtime', side_effect=AssertionError('must not bootstrap keyring'))
        self.bootstrap = p.start()
        self.addCleanup(p.stop)

    def cli(self, *args, data=''):
        out, err = io.StringIO(), io.StringIO()
        with patch('sys.stdin', io.StringIO(data)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = api.main(['--config', str(self.config), *args], auto_bootstrap=True)
        return code, out.getvalue(), err.getvalue()

    def configure(self, name='test-env', env='test', key=None, secret=None, *extra):
        return self.cli('configure', '--profile', name, '--environment', env, '--storage', 'env',
                        '--data', '-', *extra, data=json.dumps({'app_key': key or self.key,
                                                             'app_secret': secret or self.secret}))

    def assert_configured(self, *args):
        code, out, err = self.configure(*args)
        self.assertEqual(code, 0, err)
        self.assertNotIn(self.secret, out + err)
        self.assertNotIn(self.key, out + err)
        return json.loads(out)

    def test_provided_keys_configure_without_tty_vault_or_dependency(self):
        result = self.assert_configured()
        self.assertEqual(result['storage'], 'env')
        file = Path(result['credential_file'])
        self.assertEqual(file.suffix, '.env')
        self.assertEqual(api.load_profile(self.config, 'test-env')['app_secret'], self.secret)
        self.assertNotIn(self.secret, self.config.read_text(encoding='utf-8'))
        if os.name != 'nt':
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            self.assertEqual(file.parent.stat().st_mode & 0o777, 0o700)
        self.system_vault.assert_not_called()
        self.bootstrap.assert_not_called()

    def test_env_call_works_on_linux_and_never_writes_configuration(self):
        self.assert_configured()
        with patch.object(api.sys, 'platform', 'linux'), \
                patch.object(api, 'private_write', side_effect=AssertionError('write during call')), \
                patch.object(api, 'private_write_text', side_effect=AssertionError('write during call')):
            code, out, err = self.cli('call', 'F014', '--profile', 'test-env', '--execute')
        self.assertEqual(code, 0, err)
        endpoint, headers, body, _ = self.send_once.call_args.args
        self.assertEqual(endpoint, api.ENDPOINTS['test'])
        self.assertEqual(headers, api.signed_headers(self.key, self.secret, body))
        self.system_vault.assert_not_called()
        self.bootstrap.assert_not_called()

    def test_test_and_production_files_and_signatures_are_separate(self):
        test = self.assert_configured()
        prod = self.assert_configured('prod-env', 'production', 'synthetic-prod-key', 'synthetic-prod-secret')
        self.assertNotEqual(test['credential_file'], prod['credential_file'])
        for name, env, key, secret in [('test-env', 'test', self.key, self.secret),
                                     ('prod-env', 'production', 'synthetic-prod-key', 'synthetic-prod-secret')]:
            code, out, err = self.cli('call', 'F014', '--profile', name, '--environment', env, '--execute')
            self.assertEqual(code, 0, err)
            endpoint, headers, body, _ = self.send_once.call_args.args
            self.assertEqual(endpoint, api.ENDPOINTS[env])
            self.assertEqual(headers, api.signed_headers(key, secret, body))
        code, _, _ = self.cli('call', 'F014', '--profile', 'test-env', '--environment', 'production', '--execute')
        self.assertEqual(code, 2)
        self.assertEqual(self.send_once.call_count, 2)

    def test_default_replacement_preserves_env_and_deletes_old_file(self):
        before = self.assert_configured()
        code, out, err = self.cli('configure', '--profile', 'test-env', '--environment', 'test', '--replace',
                                   '--data', '-', data=json.dumps({'app_key': self.key, 'app_secret': 'rotated-secret'}))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['storage'], 'env')
        self.assertFalse(Path(before['credential_file']).exists())
        self.assertEqual(api.load_profile(self.config, 'test-env')['app_secret'], 'rotated-secret')

    def test_switch_from_locked_system_does_not_access_it(self):
        meta = {'environment': 'test', 'channel_type': 'primary', 'storage': 'system', 'credential_id': 'a'*32}
        api.private_write(self.config, {'profiles': {'test-env': meta}})
        code, out, err = self.configure('test-env', 'test', None, None, '--replace')
        self.assertEqual(code, 0, err)
        self.assertEqual(api.load_profile(self.config, 'test-env')['app_secret'], self.secret)
        self.system_vault.assert_not_called()
        self.bootstrap.assert_not_called()
        self.assertIn('The old system credential remains', err)
        self.assertNotIn(self.secret, err + out)

    def test_env_to_system_switch_removes_old_file_only_after_success(self):
        before = self.assert_configured()
        from test_flow_api import MemoryVault
        vault = MemoryVault()
        with patch.object(api, 'system_vault', return_value=vault), \
                patch.object(bootstrap, 'ensure_runtime', return_value=None):
            code, out, err = self.cli('configure', '--profile', 'test-env', '--environment', 'test', '--replace',
                                      '--storage', 'system', '--data', '-',
                                      data=json.dumps({'app_key': self.key, 'app_secret': self.secret}))
            self.assertEqual(code, 0, err)
            self.assertEqual(api.load_profile(self.config, 'test-env')['app_secret'], self.secret)
        self.assertFalse(Path(before['credential_file']).exists())
        self.assertEqual(json.loads(out)['storage'], 'system')

    def test_metadata_save_failure_preserves_old_and_removes_new_file(self):
        before = self.assert_configured()
        old_config = self.config.read_bytes()
        with patch.object(api, 'private_write', side_effect=OSError('sensitive disk error')):
            code, out, err = self.configure('test-env', 'test', None, 'replacement-secret', '--replace')
        self.assertEqual(code, 2)
        self.assertEqual(self.config.read_bytes(), old_config)
        self.assertEqual(list((self.config.parent / 'credentials').glob('*.env')), [Path(before['credential_file'])])
        self.assertEqual(api.load_profile(self.config, 'test-env')['app_secret'], self.secret)
        self.assertNotIn('replacement-secret', out + err)

    def test_no_cross_environment_rebind(self):
        self.assert_configured()
        before = self.config.read_bytes()
        code, _, _ = self.configure('test-env', 'production', None, None, '--replace')
        self.assertEqual(code, 2)
        self.assertEqual(self.config.read_bytes(), before)

    def test_remove_selected_env_file_without_touching_other_profile(self):
        a = self.assert_configured()
        b = self.assert_configured('prod-env', 'production')
        code, _, err = self.cli('remove-profile', '--profile', 'test-env')
        self.assertEqual(code, 0, err)
        self.assertFalse(Path(a['credential_file']).exists())
        self.assertTrue(Path(b['credential_file']).exists())
        self.assertNotIn('test-env', api.private_read(self.config)['profiles'])

    def test_missing_file_or_invalid_binding_never_uses_vault_or_other_env(self):
        result = self.assert_configured()
        path = Path(result['credential_file'])
        raw = path.read_text(encoding='utf-8')
        for contents in [raw.replace('BC_FLOW_ENVIRONMENT="test"', 'BC_FLOW_ENVIRONMENT="production"'),
                         raw + 'BC_FLOW_APP_SECRET="duplicate"\n', 'bad="' + self.secret]:
            path.write_text(contents, encoding='utf-8')
            code, out, err = self.cli('call', 'F014', '--profile', 'test-env', '--execute')
            self.assertEqual(code, 2)
            self.assertNotIn(self.secret, out + err)
        path.unlink()
        code, _, _ = self.cli('call', 'F014', '--profile', 'test-env', '--execute')
        self.assertEqual(code, 2)
        self.send_once.assert_not_called()
        self.system_vault.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'POSIX permissions')
    def test_world_readable_file_is_rejected_without_disclosing_content(self):
        result = self.assert_configured()
        Path(result['credential_file']).chmod(0o644)
        code, out, err = self.cli('call', 'F014', '--profile', 'test-env', '--execute')
        self.assertEqual(code, 2)
        self.assertNotIn(self.secret, out + err)
        self.send_once.assert_not_called()

    def test_response_and_profiles_never_echo_keys(self):
        self.assert_configured()
        self.send_once.side_effect = lambda endpoint, headers, body, timeout: (200, json.dumps(
            {'tradeCode': '1000', 'echo': [self.secret, self.key, headers['x-sign-value']]}).encode())
        code, out, err = self.cli('call', 'F014', '--profile', 'test-env', '--execute')
        self.assertEqual(code, 0, err)
        self.assertNotIn(self.secret, out + err)
        self.assertNotIn(self.key, out + err)
        code, out, err = self.cli('profiles')
        self.assertEqual(json.loads(out)[0]['storage'], 'env')
        self.assertNotIn(self.secret, out + err)

    def test_setup_env_needs_no_installation(self):
        code, out, err = self.cli('setup', '--storage', 'env')
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)['storage'], 'env')
        self.bootstrap.assert_not_called()

    def test_missing_credentials_prompt_does_not_prescribe_input_method(self):
        code, out, err = self.cli('configure', '--profile', 'test-env', '--environment', 'test', '--storage', 'env')
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)['error'], 'Please provide your API credentials.')

    def test_file_provided_credentials_and_invalid_inline_dont_echo(self):
        file = Path(self.temp.name) / 'provided.json'
        file.write_text(json.dumps({'app_key': self.key, 'app_secret': self.secret}), encoding='utf-8')
        code, out, err = self.cli('configure', '--profile', 'test-env', '--environment', 'test',
                                   '--storage', 'env', '--data', '@' + str(file))
        self.assertEqual(code, 0, err)
        code, out, err = self.cli('configure', '--profile', 'test-env', '--environment', 'test',
                                  '--storage', 'env', '--replace', '--data', file.read_text())
        self.assertEqual(code, 2)
        self.assertNotIn(self.secret, out + err)


class EnvProcessTest(unittest.TestCase):
    def test_full_cli_configure_signed_query_without_site_packages_or_keychain(self):
        seen = []
        class Target(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                expected = api.signed_headers('process-key', 'process-secret', body)
                seen.append(self.headers['x-channel-id'] == expected['x-channel-id'] and
                            self.headers['x-sign-value'] == expected['x-sign-value'])
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"tradeCode":"1000","tradeData":{"saleBalance":"123"}}')
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Target)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with tempfile.TemporaryDirectory(prefix='flow env process ') as folder:
                config = Path(folder) / 'profiles.json'
                proc = subprocess.run([sys.executable, '-B', '-S', str(Path(api.__file__)), '--config', str(config),
                                       'configure', '--profile', 'test-env', '--environment', 'test',
                                       '--storage', 'env', '--data', '-'],
                                      input=b'{"app_key":"process-key","app_secret":"process-secret"}',
                                      capture_output=True, timeout=10)
                self.assertEqual(proc.returncode, 0, proc.stderr.decode('utf-8'))
                self.assertNotIn(b'process-secret', proc.stdout + proc.stderr)
                driver = ("import sys;sys.path.insert(0,sys.argv[1]);import flow_api as a;"
                          "a.ENDPOINTS['test']=sys.argv[2];"
                          "result=a.main(sys.argv[3:],auto_bootstrap=True);"
                          "assert not any(n=='keyring' or n.startswith('keyring.') for n in sys.modules);"
                          "sys.exit(result)")
                proc = subprocess.run([sys.executable, '-B', '-S', '-c', driver, str(Path(api.__file__).parent),
                                       'http://127.0.0.1:' + str(server.server_port), '--config', str(config),
                                       'call', 'F014', '--profile', 'test-env', '--execute'],
                                      capture_output=True, timeout=10,
                                      env=dict(os.environ, no_proxy='127.0.0.1', NO_PROXY='127.0.0.1'))
                self.assertEqual(proc.returncode, 0, proc.stderr.decode('utf-8'))
                self.assertTrue(json.loads(proc.stdout)['success'])
                self.assertEqual(seen, [True])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
