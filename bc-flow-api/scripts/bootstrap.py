"""Prepare native credential dependencies before any stdin, vault or API access."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SWITCHED = 'BC_FLOW_API_BOOTSTRAPPED'


class BootstrapError(Exception):
    pass


def runtime_dir():
    return Path.home() / '.config' / 'bc-flow-api' / 'venv'


def runtime_python(folder):
    return folder / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')


def dependency_ready():
    try:
        importlib.import_module('keyring')
        importlib.import_module('keyring.backends.macOS' if sys.platform == 'darwin'
                                else 'keyring.backends.Windows')
        return True
    except Exception:
        return False


def quiet_run(command, timeout=30):
    # pip can print authenticated index/proxy URLs. Do not relay its raw output.
    # Never consume the business request arriving on stdin.
    try:
        return subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def probe(python, dependencies=True):
    code = 'import sys; assert sys.version_info >= (3,9); assert sys.prefix != sys.base_prefix;'
    if dependencies:
        code += ('import keyring; import keyring.backends.macOS' if sys.platform == 'darwin'
                 else 'import keyring; import keyring.backends.Windows')
    return quiet_run([str(python), '-I', '-B', '-c', code])


def prepare_runtime():
    if sys.version_info < (3, 9):
        raise BootstrapError('Python 3.9+ is required; use scripts/flow-api or scripts/flow-api.ps1 to find an available interpreter.')
    if sys.platform not in ('darwin', 'win32'):
        raise BootstrapError('System credential storage requires macOS or native Windows; Linux/WSL can use configure --storage env for a local .env file.')
    if dependency_ready():
        return None
    if os.environ.get(SWITCHED):
        raise BootstrapError('Dependencies are still unavailable after switching interpreters. Automatic setup stopped; no credentials were read and no API was called. Run setup to check the environment.')
    folder = runtime_dir()
    python = runtime_python(folder)
    if folder.is_symlink():
        raise BootstrapError('The managed virtual environment path is a symlink; run its Python directly or correct the managed path.')
    if folder.exists() and not (folder / 'pyvenv.cfg').is_file():
        raise BootstrapError('The managed path exists but is not a virtual environment. Its contents will not be overwritten; repair ~/.config/bc-flow-api/venv first.')
    if not folder.exists():
        print('Preparing the runtime for the first time; creating a dedicated virtual environment...', file=sys.stderr)
        if not quiet_run([sys.executable, '-I', '-m', 'venv', str(folder)], timeout=90):
            raise BootstrapError('Virtual environment creation failed. Check directory permissions, disk space and Python venv/ensurepip support. No API was called.')
    if not probe(python, dependencies=False):
        raise BootstrapError('The existing virtual environment interpreter is unusable and will not be overwritten. Rebuild ~/.config/bc-flow-api/venv with a working Python, then run again.')
    if not probe(python):
        print('Installing the keyring dependency; first-time setup requires access to a Python package index...', file=sys.stderr)
        if not quiet_run([str(python), '-I', '-m', 'pip', '--version']):
            if not quiet_run([str(python), '-I', '-m', 'ensurepip'], timeout=60):
                raise BootstrapError('The virtual environment has no pip and it could not be prepared. Check Python ensurepip support. No API was called.')
        if not quiet_run([str(python), '-I', '-m', 'pip', 'install', '--disable-pip-version-check',
                          '--no-input', '--retries', '0', '--timeout', '20',
                          '-r', str(ROOT / 'requirements.txt')], timeout=120):
            raise BootstrapError('Dependency installation failed or timed out. Check network, proxy, package index and certificates, then rerun to resume setup. No API was called; proxy and TLS checks are not bypassed.')
        if not probe(python):
            raise BootstrapError('The installed keyring/native backend failed the import check. No credentials were read and no API was called.')
    return python


def ensure_runtime(script, argv):
    """None means continue here; an integer is the one child invocation's exit status."""
    try:
        python = prepare_runtime()
        if python is None:
            return None
        env = dict(os.environ)
        env[SWITCHED] = '1'
        # Inherit stdin/TTY, working directory, argument boundaries and exit code.
        # No retries after starting the business process, even if it fails.
        return subprocess.run([str(python), str(Path(script).resolve()), *argv], env=env).returncode
    except BootstrapError as exc:
        print(json.dumps({'error': str(exc), 'phase': 'environment_setup', 'executed': False},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    except OSError:
        print(json.dumps({'error': 'Runtime path or startup failed. Check local permissions and the interpreter. No API was called.',
                          'phase': 'environment_setup', 'executed': False}, ensure_ascii=False), file=sys.stderr)
        return 2
