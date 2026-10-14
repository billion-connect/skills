#!/usr/bin/env python3
"""Native vault acceptance using disposable synthetic credentials; no API calls."""

import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

import flow_api as api


def main():
    api.configure_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Allow creating, reading and deleting temporary synthetic system credentials')
    args = parser.parse_args()
    if not args.execute:
        print('This check creates and deletes two temporary synthetic system credentials. It does not read real configuration or call the API. Add --execute to run.')
        return 0
    from bootstrap import ensure_runtime
    status = ensure_runtime(__file__, sys.argv[1:])
    if status is not None:
        return status
    names = ['check-test-' + uuid.uuid4().hex[:12], 'check-prod-' + uuid.uuid4().hex[:12]]
    result = {'api_called': False, 'native_roundtrip': False, 'cleanup': False}
    staged = []
    backend = None
    try:
        backend = api.system_vault()
        with tempfile.TemporaryDirectory(prefix='bc-flow-vault-check-') as folder:
            config = Path(folder) / 'profiles.json'
            profiles = {}
            expected = {}
            for name, environment in zip(names, ('test', 'production')):
                value = {'environment': environment, 'channel_type': 'primary',
                         'app_key': 'synthetic-key-' + uuid.uuid4().hex,
                         'app_secret': 'synthetic-secret-' + uuid.uuid4().hex}
                profiles[name] = api.stage_credential(backend, name, value, staged)
                expected[name] = value
            api.private_write(config, {'version': 2, 'profiles': profiles})
            # Independent process proves storage is persistent, not an in-memory cache.
            code = (
                "import sys,json,hashlib;sys.path.insert(0,sys.argv[1]);import flow_api as a;"
                "p=a.load_profile(sys.argv[2],sys.argv[3]);"
                "print(json.dumps([p['environment'],hashlib.sha256(p['app_secret'].encode()).hexdigest()]))"
            )
            import hashlib
            for name in names:
                child = subprocess.run([sys.executable, '-B', '-c', code, str(Path(__file__).parent),
                                        str(config), name], capture_output=True, text=True, timeout=30)
                if child.returncode or json.loads(child.stdout) != [expected[name]['environment'],
                        hashlib.sha256(expected[name]['app_secret'].encode()).hexdigest()]:
                    raise api.ClientError('Cross-process readback failed; credentials and child-process errors were not printed.')
            result['native_roundtrip'] = True
            for name in names:
                with contextlib.redirect_stdout(io.StringIO()):
                    api.remove_profile(argparse.Namespace(config=config, profile=name))
            result['cleanup'] = all(backend.get_password(api.vault_service(name, metadata), 'credentials') is None
                                    for name, metadata in staged)
    except Exception:
        result['error'] = 'Native credential storage check failed. Check dependencies and system unlock/authorization. No API was called.'
    finally:
        if backend is not None:
            api.cleanup_staged(backend, staged)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['native_roundtrip'] and result['cleanup'] else 2


if __name__ == '__main__':
    sys.exit(main())
