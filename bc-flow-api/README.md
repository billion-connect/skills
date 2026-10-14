# BillionConnect Flow API Skill — English edition

An Agent Skill for the **33 documented F-series APIs** of the BillionConnect new sales platform: products, prices, balance, SIM/eSIM orders, usage, shipping and after-sales. Distribution documentation includes 11 of them; see the [API index](references/index.md).

The package contains one `SKILL.md` entry point, API references loaded as needed, and Python scripts. It calls existing APIs with channel APPKEY/Secret credentials and retains server-side IP allowlist/blocklist controls.

## Requirements

- Python 3.9+. Local `.env` storage uses only the standard library. System storage prepares keyring automatically when needed. Offline tests use no real credentials.
- Valid channel API credentials and network access to the selected test or production API.
- Local `.env`, macOS Keychain and native Windows Credential Manager are supported by the implementation. Linux/WSL can use `.env`. Native Windows/PowerShell and discovery in other Agents still require platform-specific acceptance testing.

## Installation

Install with the Skills CLI:

```bash
npx skills add https://github.com/billion-connect/skills --skill bc-flow-api
```

The installer requires Node.js/npm. Alternatively, clone this repository and map/copy its `bc-flow-api/` folder as described below; API calls require Python, not Node.js.

Extract `bc-flow-api.zip` and place the complete `bc-flow-api/` folder in a stable location. Keep `SKILL.md`, `references/` and `scripts/` together.

From that extracted folder, create a Codex mapping:

```bash
BC_FLOW_SKILL_DIR="$(pwd -P)"
mkdir -p "$HOME/.codex/skills"
ln -s "$BC_FLOW_SKILL_DIR" "$HOME/.codex/skills/bc-flow-api"
```

This uses one physical directory and a symlink in the Agent's Skill directory. If the target already exists, inspect it before updating; do not force-overwrite an existing installation. Start a new Agent session and verify discovery of `bc-flow-api`.

On Windows, copying the complete folder into `%USERPROFILE%\.codex\skills\bc-flow-api` is also suitable when symlink creation is unavailable. Other Agents can map/copy the complete folder to their supported Skill directory; for example, Claude Code commonly uses `~/.claude/skills/`. The public repository is https://github.com/billion-connect/skills. Agent-specific discovery should be verified in a new session.

`bc-flow-api` is the maintained English Skill. If you previously installed the Chinese edition, preserve a backup before updating the Agent mapping to this folder. The credential namespace remains `~/.config/bc-flow-api`, so the same system user can reuse existing profiles. No existing credentials are packaged or migrated by copying this Skill.

## Credential setup

Use APPKEY and Secret from **API → Interface Authorization** in the intended environment's new sales platform. When missing, the Agent asks **"Please provide your API credentials."** You may choose how to provide them, including directly in the conversation. There is no requirement to re-enter them in a terminal or format a file. The Agent handles configuration without repeating your secrets.

APPKEY/Secret already identifies your channel; no extra channel name/ID is required. The Agent manages local profile aliases. It asks about test/production and order choices only when they are missing from context.

- **Local `.env`**: `--storage env`, without keyring, Keychain or system authorization. Credentials are plaintext in private local files, separate for test and production.
- **System credential store**: `--storage system`, using macOS Keychain or Windows Credential Manager. Required keyring dependencies are prepared automatically.

The Agent can configure supplied credentials internally with `configure ... --storage env --data -`. You need not understand its JSON input contract. Add `--replace` to switch an existing system profile to `.env`, without first unlocking the old vault. See [Credentials and calls](references/credentials.md).

`~/.config/bc-flow-api/profiles.json` stores only profile/environment/channel metadata and credential references. `.env` files live under its sibling `credentials/` directory. Future calls specify a profile without requesting keys again. If storage is omitted, new profiles default to system and existing profiles retain their mode.

Test and production never automatically fall back to each other. `configure ... --replace` rotates a profile; `remove-profile` removes local metadata and its credentials, without revoking platform keys. If the vault is locked, `.env` is available by choice, not a silent fallback after a failed call.

Without Python, launchers provide official installation guidance. `.env` needs no dependency downloads. macOS/Linux credential files use mode 600; Windows relies on private user-directory permissions. Credentials are excluded from this Skill, ZIP and Git. API IP checks still require the actual caller's outbound IP to match channel policy; the Skill does not bypass permissions.

## Quick start

Run commands in the Skill folder:

```bash
# No credentials or network required
python3 scripts/flow_api.py list
python3 scripts/flow_api.py describe F040
python3 scripts/flow_api.py template F040

# List configured aliases without revealing secrets
python3 scripts/flow_api.py profiles

# Query balance with a configured test profile
python3 scripts/flow_api.py call F014 --profile test-channel --data '{}' --execute
```

Example Agent requests: "Check the balance using test-channel" or "Show Japan eSIM products and prices for this channel." The Agent selects parameters from the references and uses the script for signing/calls.

"Order an eSIM" and "Buy an eSIM" select this workflow when no other platform is specified; the Agent first establishes the environment, product and other required choices. Explicit eSIM Access requests belong to that supplier's Skill. A third-party Skill that claims every eSIM keyword may cause routing conflicts; this package does not modify other installed Skills. Automatic discovery depends on the Agent and conversation, not fixed keyword matching. To select this edition explicitly, say "Use $bc-flow-api to order an eSIM."

For a write, establish the target, product and quantity, then prepare a JSON file containing only tradeData:

```bash
# Preview only; first fill trade-data.json with real values
python3 scripts/flow_api.py call F040 --profile test-channel --data @trade-data.json

# Execute only after authorization for this order
python3 scripts/flow_api.py call F040 --profile test-channel --data @trade-data.json --execute --allow-write
```

Only `--execute` sends a request; write operations additionally require `--allow-write`. These are script gates; the Agent must obtain action-specific user authorization before setting them. Existing clear authorization does not require repeated confirmation. Success requires HTTP 200 and tradeCode=1000. Order acceptance, QR delivery, activation and refund settlement are different states; verify through the [Business workflows](references/workflows.md). Requests do not retry automatically. After an unknown write, query the original order before any further action; the flags are not a persistent deduplication mechanism.

## English and Unicode

Agent instructions, API field descriptions, operation names, CLI help and client-generated diagnostics are in English. API keys, field names, status codes, request examples and raw server responses retain their original semantics. Some sample responses intentionally contain Chinese text, and Unicode regression fixtures remain unchanged.

When an endpoint supports language selection, use its documented English value: commonly `language="2"`, but F059 uses `language="en"`. Do not add language to endpoints that do not document it. The client does not rewrite supplied request data or server messages automatically; the Agent can explain responses in English while retaining their original evidence.

The client uses UTF-8. PowerShell should prefer `--data '@request.json'`; UTF-8 with BOM is supported. See [PowerShell input and Unicode](references/credentials.md#powershell-input-and-unicode) for pipeline settings and examples.

F002/F003 support `--sku-id`, `--limit`, `--summary`; F002 also supports `--country-code` and `--product-type`. Adding `--summary --limit 10 --output goods.json` shows a compact view while saving the complete redacted response. Use F003 `--sku-id ID --summary` to retain all quotes for the exact SKU. Filtering is local and does not reduce API response volume.

Network diagnostics distinguish proxy authentication, refused connection, DNS, TLS and timeout, showing the route and redacted proxy address. No automatic proxy bypass or retry is performed.

## Tests and validation scope

```bash
python3 -B -m unittest discover -s scripts -p 'test_*.py'
```

Offline regression uses synthetic credentials, mocked business responses and loopback-only diagnostic services. It covers signing, validation, channel isolation, file permissions, environment binding, migration/rotation/removal failures, unknown outcomes without retry, UTF-8/BOM, local filters, network diagnostics and `.env` lifecycle/signing in a separate process without keyring. It does not call real APIs or create orders. Translation validation runs on macOS; native Windows/PowerShell has not been revalidated on a Windows machine.

Historical test-environment acceptance on 2026-10-08 exercised 31 of 33 APIs: 24 had at least one business-success result and 7 only business rejections. F016 lacked a suitable acceleration product; F041 lacked a controlled recipient. This historical sample does not establish success for every channel or branch, and is not a new live test of this English edition. The package includes no live test credentials, order evidence or one-command reproduction of all real API checks.

`python3 scripts/check_credential_store.py --execute` can check native storage using temporary synthetic test/production entries, cross-process readback and cleanup, without real profile access or API calls. Run it only when that storage check is authorized and the native vault is available.

## Package contents

| File | Purpose |
|---|---|
| [SKILL.md](SKILL.md) | Agent entry point, workflow and boundaries |
| [references/index.md](references/index.md) | 33-operation index and per-endpoint references |
| [references/protocol.md](references/protocol.md) | Endpoints, signing, permissions and response contract |
| [references/credentials.md](references/credentials.md) | Storage, configuration, call options and exit codes |
| [references/workflows.md](references/workflows.md) | Products, orders, shipping and after-sales workflows |
| [references/sources.md](references/sources.md) | Source snapshots and coverage |
| [scripts/flow-api](scripts/flow-api) / [scripts/flow-api.ps1](scripts/flow-api.ps1) | macOS / Windows interpreter discovery |
| [scripts/bootstrap.py](scripts/bootstrap.py) | Dependency setup and interpreter switching |
| [scripts/flow_api.py](scripts/flow_api.py) | API and credential client |
| [scripts/cli_support.py](scripts/cli_support.py) | UTF-8, network diagnostics and local display |
| [scripts/test_flow_api.py](scripts/test_flow_api.py), [scripts/test_env_credentials.py](scripts/test_env_credentials.py), [scripts/test_bootstrap.py](scripts/test_bootstrap.py) | Offline regression tests |
| [scripts/check_credential_store.py](scripts/check_credential_store.py) | Native storage check using synthetic credentials |
| [requirements.txt](requirements.txt) | System storage dependencies |
| [agents/openai.yaml](agents/openai.yaml) | Codex display metadata |
| [LICENSE](LICENSE) | MIT License |

## License

This Skill uses the [MIT License](LICENSE), the same license type as the referenced eSIM Access Skill. API access still requires valid channel authorization; the software license grants no account, credit or data access.
