#!/usr/bin/env python3
"""Offline contract tests. Synthetic credentials only, transport mocked except loopback-only diagnostic fixtures."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import types
import socket
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cli_support

import flow_api as api


NATIVE_VAULT = api.system_vault


class MemoryVault:
    def __init__(self):
        self.data = {}
    def set_password(self, service, user, password):
        self.data[(service, user)] = password
    def get_password(self, service, user):
        return self.data.get((service, user))
    def delete_password(self, service, user):
        del self.data[(service, user)]


class FlowApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'private' / 'profiles.json'
        self.secret = 'offline-test-secret'
        self.vault = MemoryVault()
        vault_patch = patch.object(api, 'system_vault', return_value=self.vault)
        self.vault_factory = vault_patch.start()
        self.addCleanup(vault_patch.stop)
        api.private_write(self.config, {'profiles': {
            'test-a': {'environment': 'test', 'channel_type': 'primary',
                       'app_key': 'offline-test-key', 'app_secret': self.secret},
            'prod-a': {'environment': 'production', 'channel_type': 'primary',
                       'app_key': 'offline-prod-key', 'app_secret': 'offline-prod-secret'},
            'dist-a': {'environment': 'test', 'channel_type': 'distribution',
                       'app_key': 'offline-dist-key', 'app_secret': 'offline-dist-secret'},
        }})
        self.cli('migrate-credentials')
        self.vault_factory.reset_mock()
        self.network = patch.object(api, 'send_once')
        self.send = self.network.start()
        self.addCleanup(self.network.stop)
        self.send.return_value = (200, b'{"tradeCode":"1000","tradeData":{"saleBalance":"0"}}')

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = api.main(['--config', str(self.config), *args])
        return status, out.getvalue(), err.getvalue()

    def test_all_documented_examples_preview_without_credentials_or_network(self):
        for code, entry in api.load_catalog().items():
            with self.subTest(code=code):
                status, out, err = self.cli('call', code, '--data', json.dumps(entry['example_trade_data']))
                self.assertEqual(status, 0, err)
                self.assertFalse(json.loads(out)['executed'])
        self.send.assert_not_called()

    def test_all_documented_operations_dispatch_with_correct_trade_data_shape(self):
        for code, entry in api.load_catalog().items():
            with self.subTest(code=code):
                status, out, err = self.cli('call', code, '--profile', 'test-a', '--data',
                                          json.dumps(entry['example_trade_data']), '--execute', '--allow-write')
                self.assertEqual(status, 0, err)
                body = json.loads(self.send.call_args.args[2])
                self.assertEqual(body['tradeType'], code)
                self.assertEqual(body['tradeData'], entry['example_trade_data'])
        self.assertEqual(self.send.call_count, 33)

    def test_signature_known_fixture(self):
        # Independently fixed RFC1321 MD5 vector: secret='a', body=b'bc'.
        headers = api.signed_headers('fixture-key', 'a', b'bc')
        self.assertEqual(headers['x-sign-value'], '900150983cd24fb0d6963f7d28e17f72')
        self.assertEqual(headers['x-sign-method'], 'md5')

    def test_utf8_body_and_headers_are_sent_unchanged(self):
        captured = {}
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"tradeCode":"1000"}'
        class Opener:
            def open(self, request, timeout):
                captured['request'], captured['timeout'] = request, timeout
                return Response()
        body = api.body_bytes('F014', {'comment': '中文 Ω'}, '2026-10-08 09:01:02')
        headers = api.signed_headers('fixture-key', 'fixture-secret', body)
        self.network.stop()
        with patch.object(api.urllib.request, 'build_opener', return_value=Opener()):
            api.send_once(api.ENDPOINTS['test'], headers, body, 60)
        req = captured['request']
        self.assertEqual(req.data, body)
        self.assertIn('中文'.encode(), req.data)
        self.assertEqual(req.get_header('X-sign-value'), headers['x-sign-value'])
        self.assertEqual(json.loads(body)['tradeTime'], '2026-10-08 09:01:02')
        self.assertEqual(req.get_method(), 'POST')

    def test_undocumented_or_callback_codes_never_send(self):
        for code in ('N009', 'F085', 'F021', 'F999', '../F014'):
            status, _, _ = self.cli('call', code, '--profile', 'test-a', '--execute', '--allow-write')
            self.assertEqual(status, 2)
        self.send.assert_not_called()

    def test_all_write_operations_need_execution_flag(self):
        for code, entry in api.load_catalog().items():
            if entry['mode'] != 'write': continue
            status, _, _ = self.cli('call', code, '--profile', 'test-a', '--execute',
                                    '--data', json.dumps(entry['example_trade_data']))
            self.assertEqual(status, 2)
        self.send.assert_not_called()

    def test_missing_profile_does_not_select_environment(self):
        status, _, _ = self.cli('call', 'F014', '--execute')
        self.assertEqual(status, 2)
        self.send.assert_not_called()

    def test_environment_and_channel_credentials_stay_paired(self):
        self.cli('call', 'F014', '--profile', 'prod-a', '--execute')
        endpoint, headers, _, _ = self.send.call_args.args
        self.assertEqual(endpoint, api.ENDPOINTS['production'])
        self.assertEqual(headers['x-channel-id'], 'offline-prod-key')

    def test_distribution_hidden_interface_is_not_executed(self):
        status, _, _ = self.cli('call', 'F060', '--profile', 'dist-a', '--execute')
        self.assertEqual(status, 2)
        self.send.assert_not_called()

    def test_array_and_conditional_contracts(self):
        invalid = [('F015', {}), ('F046', {'iccid': '123'}), ('F010', {'iccid': '123'}),
                   ('F010', {'iccid': ['123'] * 101}), ('F013', {'iccid': []}),
                   ('F014', {'tradeType': 'F014', 'tradeData': {}})]
        for code, data in invalid:
            status, _, _ = self.cli('call', code, '--data', json.dumps(data))
            self.assertEqual(status, 2)
        self.send.assert_not_called()

    def test_days_can_replace_copies(self):
        for code, field in [('F040', 'planSkuCopies'), ('F007', 'copies')]:
            data = api.operation(code)['example_trade_data']
            data['subOrderList'][0].pop(field)
            data['subOrderList'][0]['days'] = '5'
            api.validate_data(code, data)

    def test_esim_multiple_suborder_objects_rejected(self):
        data = api.operation('F040')['example_trade_data']
        data['subOrderList'] *= 2
        with self.assertRaises(api.ClientError): api.validate_data('F040', data)

    def test_card_only_order_uses_quote_copies_without_adding_a_plan(self):
        data = api.operation('F006')['example_trade_data']
        sub = data['subOrderList'][0]
        sub.pop('planSkuId', None)
        sub.pop('days', None)
        sub['planSkuCopies'] = '1'
        status, _, err = self.cli('call', 'F006', '--profile', 'test-a', '--execute',
                                  '--allow-write', '--data', json.dumps(data))
        self.assertEqual(status, 0, err)
        sent = json.loads(self.send.call_args.args[2])['tradeData']['subOrderList'][0]
        self.assertNotIn('planSkuId', sent)
        self.assertNotIn('days', sent)

    def test_card_quote_zero_days_and_out_of_range_copies_never_send(self):
        for field in ('days', 'planSkuCopies'):
            for bad in ('0', '-1', '731', '1.5', True):
                data = api.operation('F006')['example_trade_data']
                data['subOrderList'][0][field] = bad
                status, _, _ = self.cli('call', 'F006', '--profile', 'test-a', '--execute',
                                        '--allow-write', '--data', json.dumps(data))
                self.assertEqual(status, 2)
        self.send.assert_not_called()

    def test_template_cannot_be_accidentally_executed(self):
        template = api.sanitized_template(api.operation('F040')['example_trade_data'])
        status, _, _ = self.cli('call', 'F040', '--profile', 'test-a', '--execute', '--allow-write',
                                '--data', json.dumps(template))
        self.assertEqual(status, 2)
        self.send.assert_not_called()

    def test_http_200_business_failure_is_not_success(self):
        self.send.return_value = (200, b'{"tradeCode":"9999","tradeMsg":"No permission"}')
        status, out, _ = self.cli('call', 'F014', '--profile', 'test-a', '--execute')
        self.assertEqual(status, 3)
        self.assertFalse(json.loads(out)['success'])
        self.assertEqual(json.loads(out)['response']['tradeMsg'], 'No permission')

    def test_vendor_0000_is_not_flow_success(self):
        self.send.return_value = (200, b'{"tradeCode":"0000"}')
        status, _, _ = self.cli('call', 'F014', '--profile', 'test-a', '--execute')
        self.assertEqual(status, 3)

    def test_write_timeout_returns_unknown_and_never_retries(self):
        self.send.side_effect = TimeoutError()
        data = api.operation('F040')['example_trade_data']
        status, out, _ = self.cli('call', 'F040', '--profile', 'test-a', '--execute', '--allow-write',
                                '--data', json.dumps(data))
        self.assertEqual(status, 4)
        self.assertEqual(json.loads(out)['outcome'], 'unknown')
        self.send.assert_called_once()

    def test_invalid_json_response_is_failure(self):
        self.send.return_value = (200, b'<html>gateway error</html>')
        status, out, _ = self.cli('call', 'F014', '--profile', 'test-a', '--execute')
        self.assertEqual(status, 4)
        self.assertFalse(json.loads(out)['success'])

    def test_redirect_handler_does_not_forward_credentials(self):
        self.assertIsNone(api.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid'))

    def test_private_storage_and_profile_output(self):
        if os.name != 'nt':
            self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.config.parent.stat().st_mode & 0o777, 0o700)
        status, out, _ = self.cli('profiles')
        self.assertEqual(status, 0)
        self.assertNotIn(self.secret, out)
        self.assertNotIn('offline-test-key', out)
        self.assertEqual(api.load_profile(self.config, 'test-a')['app_secret'], self.secret)

    @unittest.skipIf(os.name == 'nt', 'Windows metadata uses ACLs, not POSIX mode bits')
    def test_permissive_credentials_file_is_rejected(self):
        os.chmod(self.config, 0o644)
        status, _, _ = self.cli('call', 'F014', '--profile', 'test-a', '--execute')
        self.assertEqual(status, 2)
        self.send.assert_not_called()

    def test_non_ascii_app_key_fails_locally_not_as_response_error(self):
        meta = api.profile_metadata(self.config, 'test-a')
        key = (api.vault_service('test-a', meta), 'credentials')
        data = json.loads(self.vault.data[key])
        data['app_key'] = '测试渠道'
        self.vault.data[key] = json.dumps(data)
        status, out, err = self.cli('call', 'F014', '--profile', 'test-a', '--execute')
        self.assertEqual(status, 2)
        self.assertIn('ASCII', err)
        self.assertNotIn('测试渠道', err)
        self.send.assert_not_called()

    def test_success_output_does_not_contain_secret_or_signature(self):
        self.send.return_value = (200, json.dumps({'tradeCode':'1000', 'tradeMsg':self.secret}).encode())
        _, out, _ = self.cli('call', 'F014', '--profile', 'test-a', '--execute')
        self.assertNotIn(self.secret, out)
        self.assertNotIn(self.send.call_args.args[1]['x-sign-value'], out)

    def test_output_cannot_overwrite_credentials_even_before_send(self):
        before = self.config.read_bytes()
        status, _, _ = self.cli('call', 'F014', '--profile', 'test-a', '--execute', '--output', str(self.config))
        self.assertEqual(status, 2)
        self.assertEqual(before, self.config.read_bytes())
        self.send.assert_not_called()

    def test_result_file_is_private(self):
        path = Path(self.temp.name) / 'response.json'
        status, out, _ = self.cli('call', 'F014', '--profile', 'test-a', '--execute', '--output', str(path))
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(path.read_text())['success'])
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('saleBalance', out)

    def test_nonfinite_request_and_timeout_rejected(self):
        for args in [('--data', '{"value":NaN}'), ('--timeout', 'nan'), ('--timeout', '9999')]:
            status, _, _ = self.cli('call', 'F014', '--profile', 'test-a', '--execute', *args)
            self.assertEqual(status, 2)
        self.send.assert_not_called()

    def configure(self, name='test-a', environment='test', key='new-key', secret='new-secret', replace=True):
        with patch.object(api.sys.stdin, 'isatty', return_value=True), patch.object(api.getpass, 'getpass', side_effect=[key, secret]):
            return self.cli('configure', '--profile', name, '--environment', environment,
                            *(['--replace'] if replace else []))

    def test_two_environments_use_distinct_keys_and_signatures(self):
        for name, env, key, secret in [('test-a','test','offline-test-key',self.secret),
                                      ('prod-a','production','offline-prod-key','offline-prod-secret')]:
            status, _, err = self.cli('call','F014','--profile',name,'--environment',env,'--execute')
            self.assertEqual(status,0,err)
            endpoint, headers, body, _ = self.send.call_args.args
            self.assertEqual(endpoint,api.ENDPOINTS[env])
            self.assertEqual(headers,api.signed_headers(key,secret,body))

    def test_environment_assertion_cannot_redirect_credentials(self):
        status, _, _ = self.cli('call','F014','--profile','test-a','--environment','production','--execute')
        self.assertEqual(status,2)
        self.vault_factory.assert_not_called()
        self.send.assert_not_called()

    def test_preview_and_listing_never_unlock_vault(self):
        self.vault_factory.side_effect = api.ClientError('locked')
        for args in [('profiles',),('call','F014','--profile','test-a'),('list',),('template','F040')]:
            status, _, err = self.cli(*args)
            self.assertEqual(status,0,err)
        self.vault_factory.assert_not_called()

    def test_configuration_metadata_has_no_keys(self):
        raw = self.config.read_text()
        self.assertNotIn('app_key',raw)
        self.assertNotIn('app_secret',raw)
        self.assertNotIn(self.secret,raw)
        self.assertEqual(len(self.vault.data),3)

    def test_replace_rotates_only_selected_environment(self):
        prod = api.load_profile(self.config,'prod-a')
        status, _, err = self.configure()
        self.assertEqual(status,0,err)
        self.assertEqual(api.load_profile(self.config,'test-a')['app_secret'],'new-secret')
        self.assertEqual(api.load_profile(self.config,'prod-a'),prod)
        self.assertEqual(len(self.vault.data),3)

    def test_replace_cannot_rebind_environment(self):
        before = self.config.read_bytes()
        status, _, _ = self.configure(environment='production')
        self.assertEqual(status,2)
        self.assertEqual(self.config.read_bytes(),before)
        self.vault_factory.assert_not_called()

    def test_locked_vault_error_is_redacted_and_never_sends(self):
        with patch.object(self.vault,'get_password',side_effect=RuntimeError(self.secret)):
            status,out,err=self.cli('call','F014','--profile','test-a','--execute')
        self.assertEqual(status,2)
        self.assertNotIn(self.secret,out+err)
        self.send.assert_not_called()

    def test_missing_production_key_does_not_fallback_to_test(self):
        meta=api.profile_metadata(self.config,'prod-a')
        self.vault.data.pop((api.vault_service('prod-a',meta),'credentials'))
        status,_,_=self.cli('call','F014','--profile','prod-a','--execute')
        self.assertEqual(status,2)
        self.send.assert_not_called()

    def test_tampered_environment_binding_fails_closed(self):
        data=api.private_read(self.config)
        value=data['profiles']['test-a']
        old_service=api.vault_service('test-a',value)
        value['environment']='production'
        # Simulate a reference substitution as well: sealed payload still binds original environment.
        self.vault.data[(api.vault_service('test-a',value),'credentials')]=self.vault.data[(old_service,'credentials')]
        api.private_write(self.config,data)
        status,_,_=self.cli('call','F014','--profile','test-a','--execute')
        self.assertEqual(status,2)
        self.send.assert_not_called()

    def test_legacy_credentials_never_used_for_api(self):
        data=api.private_read(self.config)
        data['profiles']['test-a']={'environment':'test','channel_type':'primary','app_key':'legacy-key','app_secret':'legacy-secret'}
        api.private_write(self.config,data)
        status,_,err=self.cli('call','F014','--profile','test-a','--execute')
        self.assertEqual(status,2)
        self.assertIn('migrate-credentials',err)
        self.send.assert_not_called()

    def test_migration_failure_preserves_all_plaintext_and_cleans_staged(self):
        data={'profiles':{name:{'environment':env,'channel_type':'primary','app_key':name+'-key','app_secret':name+'-secret'}
                          for name,env in [('a','test'),('b','production')]}}
        api.private_write(self.config,data)
        before=self.config.read_bytes();vault_before=dict(self.vault.data)
        original=self.vault.set_password
        def fail_second(service,user,password):
            if '/production/' in service:raise RuntimeError('do not echo secret')
            original(service,user,password)
        with patch.object(self.vault,'set_password',side_effect=fail_second):
            status,_,_=self.cli('migrate-credentials')
        self.assertEqual(status,2)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(self.vault.data,vault_before)
        status,_,err=self.cli('migrate-credentials')
        self.assertEqual(status,0,err)
        for name in ('a','b'):
            self.assertEqual(api.load_profile(self.config,name)['app_secret'],name+'-secret')
        self.assertNotIn('app_secret',self.config.read_text())

    def test_failed_metadata_save_keeps_old_working_credential(self):
        before=self.config.read_bytes();vault_before=dict(self.vault.data)
        with patch.object(api,'private_write',side_effect=OSError('disk full')):
            status,_,_=self.configure()
        self.assertEqual(status,2)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(self.vault.data,vault_before)

    def test_readback_mismatch_does_not_commit(self):
        before=self.config.read_bytes()
        with patch.object(self.vault,'get_password',return_value=None):
            status,_,_=self.configure()
        self.assertEqual(status,2)
        self.assertEqual(self.config.read_bytes(),before)

    def test_remove_profile_preserves_other_environment(self):
        prod=api.load_profile(self.config,'prod-a')
        status,_,err=self.cli('remove-profile','--profile','test-a')
        self.assertEqual(status,0,err)
        self.assertEqual(len(self.vault.data),2)
        self.assertNotIn('test-a',api.private_read(self.config)['profiles'])
        self.assertEqual(api.load_profile(self.config,'prod-a'),prod)

    def test_config_lock_prevents_concurrent_changes(self):
        with api.config_lock(self.config):
            status,_,_=self.configure()
        self.assertEqual(status,2)
        self.assertFalse(self.config.with_name('profiles.json.lock').exists())

    def test_windows_metadata_write_avoids_posix_chmod(self):
        with patch.object(api.os,'name','nt'), patch.object(api.os,'fchmod',create=True,side_effect=AssertionError('POSIX-only')):
            # Path class selection uses os.name; supply existing Path and mock constructor.
            with patch.object(api,'Path',side_effect=lambda x:x):
                api.private_write(self.config,{'profiles':{}})
                self.assertEqual(api.private_read(self.config),{'profiles':{}})

    def test_native_backend_selection_ignores_generic_keyring_config(self):
        # The patched factory has no bearing on this captured native implementation.
        for platform,module,cls in [('darwin','keyring.backends.macOS','Keyring'),('win32','keyring.backends.Windows','WinVaultKeyring')]:
            backend=types.SimpleNamespace(priority=5)
            from unittest.mock import Mock
            factory=Mock(return_value=backend)
            mod=types.ModuleType(module);setattr(mod,cls,factory)
            with patch.dict('sys.modules',{module:mod}),patch.object(api.sys,'platform',platform):
                selected=NATIVE_VAULT()
            self.assertIs(selected,backend)
            if platform=='win32':self.assertEqual(selected.persist,'local machine')
        with patch.object(api.sys,'platform','linux'):
            with self.assertRaises(api.ClientError):NATIVE_VAULT()

    def test_echoed_key_and_signature_are_redacted(self):
        def response(endpoint,headers,body,timeout):
            return 200,json.dumps({'tradeCode':'1000','echo':headers}).encode()
        self.send.side_effect=response
        status,out,err=self.cli('call','F014','--profile','test-a','--execute')
        self.assertEqual(status,0,err)
        self.assertNotIn('offline-test-key',out)
        self.assertNotIn(self.send.call_args.args[1]['x-sign-value'],out)


    def goods_response(self, rows, code='1000'):
        self.send.return_value = (200, json.dumps({'tradeCode': code, 'tradeData': rows}).encode())

    def test_bom_file_and_stdin_preserve_chinese_request(self):
        value = {'language': '1', 'comment': '中文输入'}
        path = Path(self.temp.name) / '请求.json'
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8-sig')
        for source in ('@' + str(path), '-'):
            with self.subTest(source=source), patch('sys.stdin', io.StringIO('\ufeff' + json.dumps(value))):
                status, out, err = self.cli('call', 'F002', '--data', source)
                self.assertEqual(status, 0, err)
                self.assertEqual(json.loads(out)['request']['tradeData'], value)
        self.send.assert_not_called()

    def test_compound_filter_before_limit_and_full_output_retained(self):
        rows = [{'skuId': str(i), 'type': '3106' if i % 2 else '212',
                 'name': '商品' + str(i), 'country': [{'mcc': 'JP', 'name': '日本',
                                                    'apnPassword': 'not-in-summary'}]}
                for i in range(1330)]
        self.goods_response(rows)
        path = Path(self.temp.name) / 'goods.json'
        status, out, err = self.cli('call', 'F002', '--profile', 'test-a', '--execute',
                                   '--country-code', 'jp', '--product-type', '3106',
                                   '--summary', '--limit', '3', '--output', str(path))
        self.assertEqual(status, 0, err)
        shown = json.loads(out)
        self.assertEqual(shown['local_view']['total_count'], 1330)
        self.assertEqual(shown['local_view']['matched_count'], 665)
        self.assertEqual([r['skuId'] for r in shown['response']['tradeData']], ['1', '3', '5'])
        self.assertTrue(shown['local_view']['truncated'])
        self.assertNotIn('not-in-summary', out)
        saved = json.loads(path.read_text())
        self.assertEqual(saved['response']['tradeData'], rows)
        self.assertNotIn('local_view', saved)
        self.assertEqual(json.loads(self.send.call_args.args[2])['tradeData'], {})
        self.send.assert_called_once()

    def test_exact_large_sku_keeps_every_price_without_inventing_currency(self):
        quotes = [{'copies': str(i), 'days': str(i * 3), 'settlementPrice': '2.3000'}
                  for i in range(1, 32)]
        self.goods_response([{'skuId': '9007199254740992', 'price': []},
                             {'skuId': '9007199254740993', 'price': quotes}])
        status, out, err = self.cli('call', 'F003', '--profile', 'test-a', '--execute',
                                   '--sku-id', '9007199254740993', '--summary', '--limit', '1')
        self.assertEqual(status, 0, err)
        data = json.loads(out)
        self.assertEqual(data['response']['tradeData'], [{'skuId': '9007199254740993', 'price': quotes}])
        self.assertFalse(data['local_view']['truncated'])
        self.assertEqual(json.loads(self.send.call_args.args[2])['tradeData'], {})

    def test_f002_exact_sku_does_not_match_substrings(self):
        self.goods_response([{'skuId': '123'}, {'skuId': '1234'}])
        status, out, err = self.cli('call', 'F002', '--profile', 'test-a', '--execute', '--sku-id', '123')
        self.assertEqual(status, 0, err)
        self.assertEqual(json.loads(out)['response']['tradeData'], [{'skuId': '123'}])

    def test_empty_match_is_not_business_failure(self):
        self.goods_response([{'skuId': '123'}])
        status, out, err = self.cli('call', 'F003', '--profile', 'test-a', '--execute', '--sku-id', '456')
        self.assertEqual(status, 0, err)
        data = json.loads(out)
        self.assertTrue(data['success'])
        self.assertEqual(data['response']['tradeData'], [])
        self.assertEqual(data['local_view']['matched_count'], 0)

    def test_summary_defaults_to_twenty_and_raw_default_remains_complete(self):
        self.goods_response([{'skuId': str(i), 'price': []} for i in range(31)])
        for flags, expected in ((['--summary'], 20), ([], 31)):
            status, out, err = self.cli('call', 'F003', '--profile', 'test-a', '--execute', *flags)
            self.assertEqual(status, 0, err)
            self.assertEqual(len(json.loads(out)['response']['tradeData']), expected)

    def test_filters_never_mask_business_errors_or_unexpected_response(self):
        for code, rows in (('9999', 'No permission'), ('1000', None), ('1000', [None])):
            with self.subTest(code=code, rows=rows):
                self.goods_response(rows, code)
                status, out, err = self.cli('call', 'F003', '--profile', 'test-a', '--execute', '--summary')
                self.assertEqual(status, 3 if code == '9999' else 0, err)
                self.assertEqual(json.loads(out)['response']['tradeData'], rows)

    def test_invalid_filter_options_fail_before_vault_or_network(self):
        for code, flags in (('F014', ['--summary']), ('F003', ['--country-code', 'JP']),
                            ('F003', ['--product-type', '3106']), ('F002', ['--limit', '0']),
                            ('F002', ['--limit', '-1']), ('F002', ['--sku-id', ''])):
            with self.subTest(code=code, flags=flags):
                status, out, err = self.cli('call', code, '--profile', 'test-a', '--execute', *flags)
                self.assertEqual(status, 2, err)
        self.send.assert_not_called()
        self.vault_factory.assert_not_called()

    def test_diagnostic_write_failure_keeps_unknown_and_single_attempt(self):
        failure = urllib.error.URLError(ConnectionRefusedError(61, 'sensitive raw error'))
        failure._flow_route = {'route': 'proxy', 'proxy': '127.0.0.1:7890'}
        self.send.side_effect = failure
        status, out, err = self.cli('call', 'F040', '--profile', 'test-a', '--execute', '--allow-write',
                                   '--data', json.dumps(api.operation('F040')['example_trade_data']))
        self.assertEqual(status, 4, err)
        data = json.loads(out)
        self.assertEqual(data['outcome'], 'unknown')
        self.assertEqual(data['network_error']['kind'], 'connection_refused')
        self.assertNotIn('sensitive raw error', out)
        self.send.assert_called_once()


class CliProcessTest(unittest.TestCase):
    def run_cli(self, *args, input_bytes=None):
        return subprocess.run([sys.executable, '-B', str(Path(api.__file__)), *args],
                              input=input_bytes, capture_output=True, timeout=10,
                              env=dict(os.environ, PYTHONIOENCODING='ascii', PYTHONUTF8='0'))

    def test_utf8_stdout_and_stdin_in_real_ascii_default_process(self):
        proc = self.run_cli('call', 'F002', '--data', '-',
                            input_bytes='\ufeff{"language":"1","comment":"中文"}'.encode('utf-8'))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode('utf-8'))
        self.assertEqual(json.loads(proc.stdout)['request']['tradeData']['comment'], '中文')
        self.assertIn('中文', proc.stdout.decode('utf-8'))

    def test_describe_reads_utf8_reference_with_ascii_locale(self):
        proc = self.run_cli('describe', 'F040')
        self.assertEqual(proc.returncode, 0, proc.stderr.decode('utf-8'))
        self.assertIn('Create an eSIM order', proc.stdout.decode('utf-8'))

    def test_vault_check_help_uses_utf8_without_accessing_store(self):
        script = Path(api.__file__).with_name('check_credential_store.py')
        proc = subprocess.run([sys.executable, '-B', str(script)], capture_output=True, timeout=10,
                              env=dict(os.environ, PYTHONIOENCODING='ascii', PYTHONUTF8='0'))
        self.assertEqual(proc.returncode, 0, proc.stderr.decode('utf-8'))
        self.assertIn('does not read real configuration', proc.stdout.decode('utf-8'))

    def test_utf8_stderr_and_actionable_powershell_hint(self):
        proc = self.run_cli('call', 'F002', '--data', '{language:1}')
        self.assertEqual(proc.returncode, 2)
        error = json.loads(proc.stderr.decode('utf-8'))['error']
        self.assertIn('PowerShell', error)
        self.assertIn('stdin', error)


class TransportDiagnosticsTest(unittest.TestCase):
    def test_error_categories_and_no_raw_exception_disclosure(self):
        for cause, kind in ((ssl.SSLCertVerificationError('private'), 'tls_certificate'),
                            (ssl.SSLError('private'), 'tls'), (TimeoutError('private'), 'timeout'),
                            (socket.gaierror(-2, 'private'), 'dns'),
                            (ConnectionRefusedError('private'), 'connection_refused'),
                            (OSError('private'), 'connection')):
            with self.subTest(kind=kind):
                details = cli_support.network_details(urllib.error.URLError(cause))
                self.assertEqual(details['kind'], kind)
                self.assertNotIn('private', json.dumps(details))

    @contextlib.contextmanager
    def server(self, handler):
        server = HTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_real_proxy_refusal_reports_sanitized_actual_route(self):
        # Release an ephemeral loopback port; a bound non-listening socket can time out on macOS.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            address = '127.0.0.1:' + str(sock.getsockname()[1])
        with patch('urllib.request.getproxies', return_value={'https': 'http://user:proxy-secret@' + address}), \
                patch('urllib.request.proxy_bypass', return_value=False):
            with self.assertRaises(urllib.error.URLError) as caught:
                api.send_once('https://target.invalid/invoke', {}, b'{}', 2)
        details = cli_support.network_details(caught.exception)
        self.assertEqual(details['kind'], 'connection_refused')
        self.assertEqual(details['route'], 'proxy')
        self.assertEqual(details['proxy'], address)
        self.assertNotIn('proxy-secret', json.dumps(details))
        self.assertIn('NO_PROXY', details['hint'])

    def test_real_https_proxy_407_is_not_reported_as_tls(self):
        seen = []
        class Proxy(BaseHTTPRequestHandler):
            def do_CONNECT(self):
                seen.append(self.path)
                self.send_response(407)
                self.end_headers()
            def log_message(self, *args):
                pass
        with self.server(Proxy) as server:
            address = '127.0.0.1:' + str(server.server_port)
            with patch('urllib.request.getproxies', return_value={'https': 'http://user:proxy-secret@' + address}), \
                    patch('urllib.request.proxy_bypass', return_value=False):
                with self.assertRaises(urllib.error.URLError) as caught:
                    api.send_once('https://target.invalid/invoke', {}, b'{}', 2)
        details = cli_support.network_details(caught.exception)
        self.assertEqual(details['kind'], 'proxy_authentication')
        self.assertEqual(details['proxy'], address)
        self.assertEqual(seen, ['target.invalid:443'])
        self.assertNotIn('proxy-secret', json.dumps(details))

    def test_no_proxy_reaches_direct_local_target_once(self):
        seen = []
        class Target(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"tradeCode":"1000"}')
            def log_message(self, *args):
                pass
        with self.server(Target) as server:
            with patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1',
                                         'no_proxy': '127.0.0.1'}, clear=True):
                status, raw = api.send_once('http://127.0.0.1:' + str(server.server_port), {}, b'{}', 2)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['tradeCode'], '1000')
        self.assertEqual(seen, [b'{}'])

    def test_direct_failure_not_mislabeled_as_proxy(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            with patch('urllib.request.getproxies', return_value={}):
                with self.assertRaises(urllib.error.URLError) as caught:
                    api.send_once('http://127.0.0.1:' + str(sock.getsockname()[1]), {}, b'{}', 2)
        details = cli_support.network_details(caught.exception)
        self.assertEqual(details['route'], 'direct')
        self.assertNotIn('proxy', details)


if __name__ == '__main__':
    unittest.main(verbosity=2)
