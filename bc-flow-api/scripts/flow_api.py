#!/usr/bin/env python3
"""Flow API 2.0 client. OS vault or explicit local .env credentials; no request retries."""

import argparse
import contextlib
import datetime as dt
import getpass
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import uuid

from cli_support import configure_stdio, display_result, has_view, network_details, request_route, validate_view

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = Path.home() / '.config' / 'bc-flow-api' / 'profiles.json'
ENDPOINTS = {
    'test': 'https://api-flow-ts.billionconnect.com/Flow/saler/2.0/invoke',
    'production': 'https://api-flow.billionconnect.com/Flow/saler/2.0/invoke',
}
SHANGHAI = dt.timezone(dt.timedelta(hours=8))


class ClientError(Exception):
    pass


def load_catalog():
    return json.loads((ROOT / 'references' / 'operations.json').read_text(encoding='utf-8'))


def operation(code):
    entry = load_catalog().get(code)
    if entry is None:
        raise ClientError('The operation is not in the documented F API allowlist; use list to see supported operations.')
    return entry


def private_read_text(path):
    if Path(path).is_symlink():
        raise ClientError('Refusing to read a symlinked configuration.')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (os.name != 'nt' and info.st_mode & 0o077):
                raise ClientError('Credential files must be regular files with mode 600.')
            if hasattr(os, 'getuid') and info.st_uid != os.getuid():
                raise ClientError('Credential files must belong to the current user.')
            return stream.read()
    except (OSError, ValueError):
        raise ClientError('Cannot read credential configuration; run configure first and check file format and permissions.') from None


def private_read(path):
    try:
        data = json.loads(private_read_text(path))
    except ValueError:
        raise ClientError('Invalid credential configuration format.') from None
    if (not isinstance(data, dict) or not isinstance(data.get('profiles'), dict)
            or any(not isinstance(v, dict) for v in data['profiles'].values())):
        raise ClientError('Invalid credential configuration format.')
    return data


def private_write_text(path, text):
    """Atomic replacement; private bytes never pass through shell arguments."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ClientError('Refusing to write to a symlink.')
    fd, tmp = tempfile.mkstemp(prefix='.flow-api-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            if os.name != 'nt':
                os.fchmod(stream.fileno(), 0o600)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def private_write(path, data):
    private_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def system_vault():
    """Select only native backends; never auto-discover plaintext or null plugins."""
    try:
        if sys.platform == 'darwin':
            from keyring.backends.macOS import Keyring
            backend = Keyring()
        elif sys.platform == 'win32':
            from keyring.backends.Windows import WinVaultKeyring
            backend = WinVaultKeyring()
            backend.persist = 'local machine'  # same user, same machine, survives logout
        else:
            raise ClientError('System credential storage requires macOS or native Windows; alternatively configure a local .env with configure --storage env.')
        if backend.priority <= 0:
            raise RuntimeError('unavailable')
        return backend
    except ClientError:
        raise
    except Exception:
        raise ClientError('System credential storage is unavailable. Check system unlock/authorization, or provide the credentials again with configure --storage env (add --replace for an existing profile) to use a local .env. No automatic switch was made.') from None


def vault_call(backend, method, *args):
    try:
        return getattr(backend, method)(*args)
    except Exception:
        # Native errors may contain credential contents. Never echo them.
        raise ClientError('System credential storage operation failed. Check system unlock/authorization, or provide the credentials again with configure --storage env --replace to use a local .env. No automatic switch was made.') from None


def validate_identity(name, value):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
        raise ClientError('Profile names must contain 1–64 letters, digits, underscores or hyphens.')
    if not isinstance(value, dict) or value.get('environment') not in ENDPOINTS:
        raise ClientError('Profile environment must be test or production.')
    if value.get('channel_type') not in ('primary', 'distribution'):
        raise ClientError('Profile channel_type must be primary or distribution.')


def validate_keys(value):
    for key in ('app_key', 'app_secret'):
        val = value.get(key)
        if not isinstance(val, str) or not val.strip() or '\n' in val or '\r' in val:
            raise ClientError('app_key/app_secret is missing or invalid.')
    if not value['app_key'].isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value['app_key']):
        raise ClientError('appKey must be a nonempty ASCII identifier suitable for an HTTP header. No request was sent.')


def vault_service(name, value):
    validate_identity(name, value)
    ref = value.get('credential_id')
    if value.get('storage') != 'system' or not isinstance(ref, str) or not re.fullmatch(r'[0-9a-f]{32}', ref):
        raise ClientError('Missing a valid system credential reference; run migrate-credentials for legacy plaintext configuration first.')
    return 'BillionConnect/bc-flow-api/' + value['environment'] + '/' + name + '/' + ref


def profile_metadata(path, name):
    value = private_read(path)['profiles'].get(name)
    if not isinstance(value, dict):
        raise ClientError('The specified profile does not exist; use profiles to list configured names.')
    validate_identity(name, value)
    return value


def read_vault_profile(backend, name, value):
    raw = vault_call(backend, 'get_password', vault_service(name, value), 'credentials')
    if raw is None:
        raise ClientError('System credentials for this profile do not exist. Run configure again as the current system user; no other environment will be used.')
    try:
        secret = json.loads(raw)
    except (ValueError, TypeError):
        raise ClientError('Invalid system credential format; run configure again.') from None
    if not isinstance(secret, dict) or any(secret.get(k) != v for k, v in
            [('profile', name), ('environment', value['environment']), ('channel_type', value['channel_type'])]):
        raise ClientError('System credentials do not match the profile/environment/channel binding. No request was sent.')
    validate_keys(secret)
    return dict(value, app_key=secret['app_key'], app_secret=secret['app_secret'])


ENV_FIELDS = {'BC_FLOW_PROFILE': 'profile', 'BC_FLOW_ENVIRONMENT': 'environment',
              'BC_FLOW_CHANNEL_TYPE': 'channel_type', 'BC_FLOW_APP_KEY': 'app_key',
              'BC_FLOW_APP_SECRET': 'app_secret'}


def env_credential_path(config, name, metadata):
    validate_identity(name, metadata)
    ref = metadata.get('credential_id')
    if metadata.get('storage') != 'env' or not isinstance(ref, str) or not re.fullmatch(r'[0-9a-f]{32}', ref):
        raise ClientError('Missing a valid .env credential reference; run configure --storage env again.')
    folder = Path(config).parent / 'credentials'
    if folder.is_symlink():
        raise ClientError('The credentials directory must not be a symlink; use a private local directory.')
    return folder / (metadata['environment'] + '-' + name + '-' + ref + '.env')


def read_env_profile(config, name, metadata):
    try:
        raw = private_read_text(env_credential_path(config, name, metadata))
        payload = {}
        for line in raw.lstrip('\ufeff').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if not sep or key not in ENV_FIELDS or ENV_FIELDS[key] in payload:
                raise ValueError()
            # Literal values only: no shell execution or environment interpolation.
            if value.startswith('"'):
                value = json.loads(value)
            elif value.startswith("'"):
                if len(value) < 2 or not value.endswith("'"):
                    raise ValueError()
                value = value[1:-1]
            if not isinstance(value, str):
                raise ValueError()
            payload[ENV_FIELDS[key]] = value
        if any(payload.get(k) != v for k, v in [('profile', name),
                ('environment', metadata['environment']), ('channel_type', metadata['channel_type'])]):
            raise ValueError()
        validate_keys(payload)
    except (OSError, ValueError, ClientError):
        raise ClientError('Local .env credentials are unavailable or do not match the profile. Please provide your API credentials. You can also check that only the current user can read the file. No request was sent.') from None
    return dict(metadata, app_key=payload['app_key'], app_secret=payload['app_secret'])


def stage_env_credential(config, name, value, staged):
    validate_identity(name, value)
    validate_keys(value)
    metadata = {'environment': value['environment'], 'channel_type': value['channel_type'],
                'storage': 'env', 'credential_id': uuid.uuid4().hex}
    staged.append((name, metadata))
    payload = dict(value, profile=name)
    text = '# bc-flow-api local credentials: plaintext; keep private.\n'
    text += ''.join(key + '=' + json.dumps(payload[field], ensure_ascii=False) + '\n'
                    for key, field in ENV_FIELDS.items())
    private_write_text(env_credential_path(config, name, metadata), text)
    checked = read_env_profile(config, name, metadata)
    if any(checked[k] != value[k] for k in ('app_key', 'app_secret')):
        raise ClientError('.env readback did not match the saved values; the original configuration is retained.')
    return metadata


def cleanup_profiles(config, backend, entries):
    for name, metadata in entries:
        if metadata.get('storage') == 'env':
            try:
                env_credential_path(config, name, metadata).unlink(missing_ok=True)
            except (OSError, ClientError):
                print('Old .env cleanup is incomplete. Check the local credentials directory; a successfully saved new configuration remains usable.', file=sys.stderr)
        elif backend is not None:
            cleanup_staged(backend, [(name, metadata)])
        else:
            # Switching away from a locked vault must never access that vault again.
            print('Switched to .env. The old system credential remains and can be removed later in the system credential manager: ' +
                  vault_service(name, metadata), file=sys.stderr)


def configured_storage(args):
    if args.storage:
        return args.storage
    if args.config.exists():
        old = private_read(args.config)['profiles'].get(args.profile)
        if old is not None and old.get('storage') in ('system', 'env'):
            return old['storage']
    return 'system'


def load_profile(path, name):
    value = profile_metadata(path, name)
    if 'app_key' in value or 'app_secret' in value:
        raise ClientError('Legacy plaintext credentials detected. Run migrate-credentials first; direct use and silent fallback are prohibited.')
    if value.get('storage') == 'env':
        return read_env_profile(path, name, value)
    return read_vault_profile(system_vault(), name, value)


@contextlib.contextmanager
def config_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = path.with_name(path.name + '.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ClientError('Configuration is being modified. If the previous process has exited, verify this and remove the .lock file in the same directory before retrying.') from None
    try:
        os.close(fd)
        yield
    finally:
        lock.unlink()


def stage_credential(backend, name, value, staged):
    validate_identity(name, value)
    validate_keys(value)
    metadata = {'environment': value['environment'], 'channel_type': value['channel_type'],
                'storage': 'system', 'credential_id': uuid.uuid4().hex}
    service = vault_service(name, metadata)
    payload = json.dumps(dict(profile=name, environment=value['environment'], channel_type=value['channel_type'],
                              app_key=value['app_key'], app_secret=value['app_secret']), ensure_ascii=False)
    # Windows generic credential blob limit is 2560 bytes (keyring writes UTF-16).
    if len(payload.encode('utf-16-le')) > 2560:
        raise ClientError('Credentials exceed the cross-platform system credential size limit; nothing was saved.')
    staged.append((name, metadata))
    vault_call(backend, 'set_password', service, 'credentials', payload)
    checked = read_vault_profile(backend, name, metadata)
    if any(checked[k] != value[k] for k in ('app_key', 'app_secret')):
        raise ClientError('System credential readback did not match the saved values; the original configuration is retained.')
    return metadata


def delete_vault_profile(backend, name, metadata):
    service = vault_service(name, metadata)
    if vault_call(backend, 'get_password', service, 'credentials') is not None:
        vault_call(backend, 'delete_password', service, 'credentials')
    if vault_call(backend, 'get_password', service, 'credentials') is not None:
        raise ClientError('System credential deletion is incomplete; retry the deletion.')


def cleanup_staged(backend, staged):
    for name, metadata in staged:
        try:
            delete_vault_profile(backend, name, metadata)
        except ClientError:
            print('Credential cleanup is incomplete. Delete this reference in the system credential manager: ' + vault_service(name, metadata), file=sys.stderr)


def configure(args):
    args.storage = configured_storage(args)
    validate_identity(args.profile, vars(args))
    if not args.data and not sys.stdin.isatty():
        raise ClientError('Please provide your API credentials.')
    with config_lock(args.config):
        data = private_read(args.config) if args.config.exists() else {'profiles': {}}
        if any('app_key' in v or 'app_secret' in v for v in data['profiles'].values()):
            raise ClientError('Configuration contains legacy plaintext credentials; run migrate-credentials first.')
        old = data['profiles'].get(args.profile)
        if old is not None:
            if not args.replace:
                raise ClientError('Profile already exists; use --replace to update credentials.')
            if old.get('environment') != args.environment or old.get('channel_type') != args.channel_type:
                raise ClientError("An existing profile's environment and channel type cannot change; use separate test and production profiles.")
        backend = system_vault() if args.storage == 'system' else None
        if args.storage == 'env':
            print('Credentials will be stored in a plaintext .env file in your private user directory. No Keychain access is required; do not share or commit this file.', file=sys.stderr)
        if args.data:
            if args.data != '-' and not args.data.startswith('@'):
                raise ClientError('Invalid credential input argument; credentials must not be passed directly as command-line arguments.')
            supplied = parse_data(args.data)
            if not isinstance(supplied, dict):
                raise ClientError('Please provide your API credentials.')
            value = dict(environment=args.environment, channel_type=args.channel_type,
                         app_key=supplied.get('app_key'), app_secret=supplied.get('app_secret'))
        else:
            value = dict(environment=args.environment, channel_type=args.channel_type,
                         app_key=getpass.getpass('appKey (hidden input): ').strip(),
                         app_secret=getpass.getpass('appSecret (hidden input): ').strip())
        staged = []
        try:
            data['profiles'][args.profile] = (stage_env_credential(args.config, args.profile, value, staged)
                    if args.storage == 'env' else stage_credential(backend, args.profile, value, staged))
            data['version'] = 2
            private_write(args.config, data)
        except Exception:
            cleanup_profiles(args.config, backend, staged)
            raise
        if old:
            cleanup_profiles(args.config, backend, [(args.profile, old)])
    result = {'configured': args.profile, 'environment': args.environment,
              'storage': args.storage, 'path': str(args.config)}
    if args.storage == 'env':
        result['credential_file'] = str(env_credential_path(args.config, args.profile, data['profiles'][args.profile]))
    print(json.dumps(result, ensure_ascii=False))


def migrate_credentials(args):
    with config_lock(args.config):
        data = private_read(args.config)
        legacy = [(n, v) for n, v in data['profiles'].items() if 'app_key' in v or 'app_secret' in v]
        if not legacy:
            print(json.dumps({'migrated': [], 'note': 'No legacy plaintext credentials found.'}, ensure_ascii=False))
            return
        for name, value in legacy:
            validate_identity(name, value)
            validate_keys(value)
        backend = system_vault()
        staged = []
        try:
            # Stage and verify ALL profiles before replacing any plaintext metadata.
            for name, value in legacy:
                data['profiles'][name] = stage_credential(backend, name, value, staged)
            data['version'] = 2
            private_write(args.config, data)
        except Exception:
            cleanup_staged(backend, staged)
            raise
    print(json.dumps({'migrated': [n for n, _ in legacy], 'storage': 'system',
                      'plaintext_removed_from_config': True}, ensure_ascii=False))


def remove_profile(args):
    with config_lock(args.config):
        data = private_read(args.config)
        value = data['profiles'].get(args.profile)
        if value is None:
            raise ClientError('Profile does not exist.')
        if 'app_key' in value or 'app_secret' in value:
            raise ClientError('Run migrate-credentials before deleting system credentials.')
        if value.get('storage') == 'env':
            env_credential_path(args.config, args.profile, value).unlink(missing_ok=True)
        else:
            delete_vault_profile(system_vault(), args.profile, value)
        del data['profiles'][args.profile]
        private_write(args.config, data)
    print(json.dumps({'removed': args.profile, 'platform_key_revoked': False}))


def missing(obj, key):
    return key not in obj or obj[key] is None or obj[key] == '' or obj[key] == []


def require(obj, *keys):
    if not isinstance(obj, dict):
        raise ClientError('Request entries must be JSON objects.')
    absent = [key for key in keys if missing(obj, key)]
    if absent:
        raise ClientError('Missing required fields: ' + ', '.join(absent))


def validate_data(code, data):
    entry = operation(code)
    expected = list if entry['trade_data_type'] == 'array' else dict
    if not isinstance(data, expected):
        raise ClientError(code + ' tradeData must be ' + entry['trade_data_type'])
    if isinstance(data, dict) and ('tradeType' in data or 'tradeData' in data):
        raise ClientError('--data accepts only tradeData, not the complete envelope.')
    rows = data if isinstance(data, list) else [data]
    if not rows:
        raise ClientError('tradeData array must not be empty.')
    for row in rows:
        require(row, *entry.get('required', []))
    if code in ('F010', 'F013'):
        ids = data['iccid']
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or not x.strip() for x in ids):
            raise ClientError('iccid must be a nonempty array of nonempty strings.')
        if code == 'F010' and len(ids) > 100:
            raise ClientError('F010 supports at most 100 cards per request.')
    if code == 'F051' and (not isinstance(data['skuIds'], list) or not data['skuIds']):
        raise ClientError('skuIds must be a nonempty array.')
    if code == 'F046' and missing(data, 'orderId') and missing(data, 'channelOrderId'):
        raise ClientError('F046 requires orderId or channelOrderId.')
    if code in ('F006', 'F007', 'F016', 'F040'):
        subs = data['subOrderList']
        if not isinstance(subs, list) or not subs:
            raise ClientError('subOrderList must be a nonempty array.')
        if code in ('F016', 'F040') and len(subs) != 1:
            raise ClientError(code + ' supports exactly one suborder object; plan units/card quantity are fields inside it.')
        if code in ('F006', 'F007') and len(subs) > 5:
            raise ClientError(code + ' supports at most 5 suborders.')
        for sub in subs:
            require(sub, 'channelSubOrderId')
            if code in ('F006', 'F040'):
                require(sub, 'deviceSkuId', 'number')
                if missing(sub, 'planSkuCopies') and missing(sub, 'days'):
                    raise ClientError('A suborder requires planSkuCopies or days.')
                if code == 'F006':
                    for field in ('planSkuCopies', 'days'):
                        if not missing(sub, field):
                            value = sub[field]
                            if (isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value))
                                    or not 1 <= int(value) <= 730):
                                raise ClientError('F006 field ' + field + ' must be an integer from 1 to 730. For card-only products, use copies from a valid quote; do not pass quoted days=0.')
            elif code == 'F007':
                require(sub, 'skuId', 'iccid')
                if missing(sub, 'copies') and missing(sub, 'days'):
                    raise ClientError('A top-up suborder requires copies or days.')
                if not isinstance(sub['iccid'], list) or not sub['iccid']:
                    raise ClientError('F007 suborder iccid must be a nonempty array.')
            else:
                require(sub, 'iccid', 'skuId')
        if code == 'F006' and missing(data, 'express') and missing(data, 'selfPickup'):
            raise ClientError('F006 requires express or selfPickup.')


def parse_data(source):
    try:
        if source == '-':
            raw = sys.stdin.read()
        elif source.startswith('@'):
            raw = Path(source[1:]).read_text(encoding='utf-8-sig')
        else:
            raw = source
        return json.loads(raw.removeprefix('\ufeff'), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (OSError, ValueError):
        raise ClientError("--data must be JSON, @file-path or - (stdin), without NaN/Infinity. For PowerShell, prefer --data '@request.json' (UTF-8 file) or --data - (stdin).") from None


def body_bytes(code, data, trade_time=None):
    value = {'tradeType': code,
             'tradeTime': trade_time or dt.datetime.now(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S'),
             'tradeData': data}
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def signed_headers(app_key, app_secret, body):
    signature = hashlib.md5(app_secret.encode('utf-8') + body).hexdigest()
    return {'Content-Type': 'application/json; charset=UTF-8', 'x-channel-id': app_key,
            'x-sign-method': 'md5', 'x-sign-value': signature}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send_once(endpoint, headers, body, timeout):
    request = urllib.request.Request(endpoint, data=body, headers=headers, method='POST')
    # No redirect, no retries: signed bodies and channel IDs remain at the selected endpoint.
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            return response.status, response.read()
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        exc._flow_route = request_route(request)
        raise


def has_placeholder(value):
    if isinstance(value, str):
        return bool(re.search(r'<[^>]+>', value))
    if isinstance(value, list):
        return any(has_placeholder(x) for x in value)
    if isinstance(value, dict):
        return any(has_placeholder(x) for x in value.values())
    return False


def run_call(args):
    if args.output and args.output.resolve() == args.config.resolve():
        raise ClientError('The result file must not overwrite credential configuration.')
    entry = operation(args.code)
    try:
        validate_view(args)
    except ValueError as exc:
        raise ClientError(str(exc)) from None
    data = parse_data(args.data)
    validate_data(args.code, data)
    if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 300:
        raise ClientError('--timeout must be between 1 and 300 seconds.')
    profile = profile_metadata(args.config, args.profile) if args.profile else None
    environment = profile['environment'] if profile else 'test'
    if args.environment and args.environment != environment:
        raise ClientError("--environment does not match the profile's bound environment. No request was sent.")
    if profile and profile['channel_type'] == 'distribution' and not entry['distribution_documented']:
        raise ClientError("This operation is outside the distribution documentation scope; do not substitute another channel's credentials.")
    body = body_bytes(args.code, data)
    result = {'operation': args.code, 'name': entry['name'], 'mode': entry['mode'],
              'profile': args.profile, 'environment': environment, 'endpoint': ENDPOINTS[environment]}
    if not args.execute:
        result.update({'executed': False, 'request': json.loads(body),
                       'headers': {'x-channel-id': '<profile appKey>', 'x-sign-method': 'md5',
                                   'x-sign-value': '<computed only for execution>'}})
        return result, 0
    if profile is None:
        raise ClientError('Actual calls require an explicit --profile; channel/environment selection is not automatic.')
    if entry['mode'] == 'write' and not args.allow_write:
        raise ClientError('This is a write operation. After the user authorizes this action, use --execute --allow-write.')
    if has_placeholder(data):
        raise ClientError('The request still contains template placeholders and cannot be executed.')
    channel_type = profile['channel_type']
    profile = load_profile(args.config, args.profile)
    if profile['environment'] != environment or profile['channel_type'] != channel_type:
        raise ClientError('The profile environment/channel type changed during the call. No request was sent.')
    headers = signed_headers(profile['app_key'], profile['app_secret'], body)
    result['executed'] = True
    result['success'] = False
    result['outcome'] = 'unknown'
    try:
        status, raw = send_once(ENDPOINTS[environment], headers, body, args.timeout)
        result['http_status'] = status
        response = json.loads(raw)
        if not isinstance(response, dict) or 'tradeCode' not in response:
            raise ValueError('missing tradeCode')
        # A server error must never echo the configured secret into output.
        redacted = json.dumps(response, ensure_ascii=False)
        for private_value in (profile['app_secret'], profile['app_key'], headers['x-sign-value']):
            redacted = redacted.replace(json.dumps(private_value, ensure_ascii=False)[1:-1], '[REDACTED]')
        result['response'] = json.loads(redacted)
        result['success'] = status == 200 and str(response.get('tradeCode')) == '1000'
        result['outcome'] = 'api_success' if result['success'] else 'business_error'
        result['note'] = 'API success does not mean QR delivery, activation, top-up or refund completion. Verify business state using the endpoint documentation.'
        return result, 0 if result['success'] else 3
    except urllib.error.HTTPError as exc:
        result['http_status'] = exc.code
        result['error'] = 'HTTP request failed or redirected; no automatic retry was made.'
        if exc.code == 407:
            result['network_error'] = network_details(exc)
            result['error'] = result['network_error']['hint'] + ' No automatic retry was made.'
        exc.close()
    except (ValueError, UnicodeError):
        result['error'] = 'The response is not a valid API 2.0 JSON envelope; no automatic retry was made.'
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        result['network_error'] = network_details(exc)
        result['error'] = result['network_error']['hint'] + ' No automatic retry was made.'
    result['note'] = ('Write outcome is unknown. Verify using the original channel order ID/target record; do not replay automatically or change order IDs.'
                      if entry['mode'] == 'write' else 'This query did not obtain a verifiable business result.')
    redacted = json.dumps(result, ensure_ascii=False)
    for value in (profile['app_secret'], profile['app_key'], headers['x-sign-value']):
        redacted = redacted.replace(json.dumps(value, ensure_ascii=False)[1:-1], '[REDACTED]')
    return json.loads(redacted), 4


def sanitized_template(value, key=''):
    identifiers = {'channelOrderId', 'channelSubOrderId', 'orderId', 'subOrderId', 'afterSaleId',
                   'originalOrderId', 'originalSaleGoodsId', 'deviceSkuId', 'planSkuId', 'skuId',
                   'skuIds', 'iccid', 'pickupPointId', 'logisticsId', 'userName', 'userPhone',
                   'address', 'email', 'estimatedUseTime', 'orderCreateTime', 'totalAmount',
                   'discountAmount', 'deviceSkuPrice', 'planSkuPrice', 'price',
                   'settlementPrice', 'refundAmount', 'expressFee'}
    if isinstance(value, dict):
        return {k: sanitized_template(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitized_template(v, key) for v in value]
    return '<' + key + '>' if key in identifiers and value != '' else value


def main(argv=None, auto_bootstrap=False):
    configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest='command', required=True)
    ls = commands.add_parser('list', help='List documented operations in the allowlist')
    ls.add_argument('--channel-type', choices=['primary', 'distribution'], default='primary')
    for name in ('describe', 'template'):
        p = commands.add_parser(name)
        p.add_argument('code')
    conf = commands.add_parser('configure', help='Configure credentials in system storage or a local .env')
    conf.add_argument('--profile', required=True)
    conf.add_argument('--environment', required=True, choices=ENDPOINTS)
    conf.add_argument('--channel-type', choices=['primary', 'distribution'], default='primary')
    conf.add_argument('--replace', action='store_true')
    conf.add_argument('--data', help='Agent configuration input: - reads stdin; @path reads JSON; plaintext credentials are not accepted as command-line arguments')
    conf.add_argument('--storage', choices=['system', 'env'],
                      help='system=system credential store; env=local plaintext .env; omission preserves existing storage and defaults new profiles to system')
    commands.add_parser('migrate-credentials', help='Migrate all legacy plaintext credentials to system storage; remove plaintext fields after verification')
    remove = commands.add_parser('remove-profile', help='Delete the local profile and its credentials; does not revoke platform keys')
    remove.add_argument('--profile', required=True)
    setup = commands.add_parser('setup', help='Prepare the selected storage runtime without reading credentials or calling the API')
    setup.add_argument('--storage', choices=['system', 'env'], default='system')
    commands.add_parser('profiles', help='Show profile names, environments and channel types without credentials')
    call = commands.add_parser('call', help='Preview by default; --execute sends the request')
    call.add_argument('code')
    call.add_argument('--profile')
    call.add_argument('--environment', choices=ENDPOINTS, help='Optional environment assertion; must match the profile and cannot override it')
    call.add_argument('--data', default='{}', help='tradeData JSON, @file or -')
    call.add_argument('--execute', action='store_true')
    call.add_argument('--allow-write', action='store_true')
    call.add_argument('--timeout', type=float, default=60)
    call.add_argument('--output', type=Path, help='Save the result as a JSON file with mode 600')
    call.add_argument('--sku-id', help='Filter F002/F003 responses by exact SKU without changing the request')
    call.add_argument('--country-code', help='Filter F002 responses by country[].mcc')
    call.add_argument('--product-type', help='Filter F002 responses by exact type')
    call.add_argument('--limit', type=int, help="Maximum products displayed locally; does not truncate a SKU's price array")
    call.add_argument('--summary', action='store_true', help='Compact F002/F003 display; defaults to at most 20 products')
    args = parser.parse_args(argv)
    try:
        if args.command == 'configure':
            args.storage = configured_storage(args)
        needs_runtime = args.command == 'migrate-credentials' or (args.command == 'setup' and args.storage == 'system')
        if args.command == 'configure':
            needs_runtime = args.storage == 'system'
        elif args.command == 'remove-profile' or (args.command == 'call' and args.execute):
            needs_runtime = not args.profile or profile_metadata(args.config, args.profile).get('storage') != 'env'
        if needs_runtime and (auto_bootstrap or args.command == 'setup'):
            from bootstrap import ensure_runtime
            status = ensure_runtime(__file__, list(argv) if argv is not None else sys.argv[1:])
            if status is not None:
                return status
        if args.command == 'setup':
            print(json.dumps({'ready': True, 'storage': args.storage, 'python': sys.executable, 'api_called': False, 'vault_accessed': False}))
            return 0
        if args.command == 'configure':
            configure(args)
            return 0
        if args.command == 'migrate-credentials':
            migrate_credentials(args)
            return 0
        if args.command == 'remove-profile':
            remove_profile(args)
            return 0
        if args.command == 'profiles':
            data = private_read(args.config)
            result = [{'profile': k, 'environment': v.get('environment'),
                       'channel_type': v.get('channel_type'),
                       'storage': 'legacy-plaintext' if 'app_key' in v or 'app_secret' in v else v.get('storage')} for k, v in data['profiles'].items()]
        elif args.command == 'list':
            result = [{'code': k, 'name': v['name'], 'mode': v['mode'],
                       'distribution_documented': v['distribution_documented']}
                      for k, v in load_catalog().items()
                      if args.channel_type == 'primary' or v['distribution_documented']]
        elif args.command == 'describe':
            operation(args.code)
            print((ROOT / 'references' / 'interfaces' / (args.code + '.md')).read_text(encoding='utf-8'))
            return 0
        elif args.command == 'template':
            result = sanitized_template(operation(args.code)['example_trade_data'])
        else:
            result, exit_code = run_call(args)
            view = display_result(result, args)
            if args.output:
                try:
                    private_write(args.output, result)
                except (OSError, ClientError):
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                    print('Could not save the result file. The call result was printed; do not retry a write because of this failure.', file=sys.stderr)
                    return exit_code or 5
                if has_view(args):
                    print(json.dumps(dict(view, output=str(args.output)), ensure_ascii=False, indent=2))
                else:
                    print(json.dumps({'output': str(args.output), 'success': result.get('success'),
                                      'executed': result.get('executed')}, ensure_ascii=False))
            else:
                print(json.dumps(view, ensure_ascii=False, indent=2))
            return exit_code
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ClientError, OSError) as exc:
        message = str(exc) if isinstance(exc, ClientError) else 'Local file operation failed; check paths and permissions.'
        print(json.dumps({'error': message}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print('Operation interrupted. If a request was sent, verify the write outcome by querying its state.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main(auto_bootstrap=True))
