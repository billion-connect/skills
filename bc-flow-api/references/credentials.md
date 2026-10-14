# Credentials and calls

## Credential input and storage choice

When credentials are missing, ask **"Please provide your API credentials."** Let the user choose how to provide them. Accept credentials in the conversation, an existing file, or a configuration the user creates themselves. Do not require re-entry in a terminal or conversion to a particular file format. The Agent formats the input and does not repeat secrets in its completion message.

| Option | Intended use | Storage | Keychain/keyring required |
|---|---|---|---|
| `--storage env` | Simple setup without system unlock/authorization | Plaintext `.env` in a private local directory | No; Python standard library only |
| `--storage system` | Native encrypted credential storage | macOS Keychain / Windows Credential Manager | Yes; dependencies prepared automatically |

For simpler setup, `.env` is available with a brief explanation that credentials are stored in a private local plaintext file. Users need not troubleshoot Keychain first. In env mode, configure/read/replace/delete do not access system storage or install keyring. Both modes use the same API signature and server-side IP controls.

If `--storage` is omitted, new profiles default to system; updates retain the existing storage mode. Pass `--storage env` explicitly when that option is selected. Later API calls need only `--profile`, not another storage choice or credentials.

## Credentials identify the channel

APPKEY identifies the actual channel and is sent as `x-channel-id`; Secret signs the request. One supplied APPKEY/Secret pair selects the channel. Do not additionally ask for its name, ID, saleId or "which channel".

A `profile` is a local alias, not another business channel parameter. The Agent reuses an appropriate existing alias or creates an environment-specific name such as `test-channel` / `prod-channel`. If that name belongs to different credentials, choose an unused name instead of overwriting it. Users do not need to name profiles; the Agent satisfies the explicit `--profile` requirement.

Credentials identify the channel, but their strings alone do not reliably identify test versus production. Reuse the environment already established in context; ask only if it is missing. Do not try credentials across environments. If the user supplies several pairs and their intended selection is unclear, clarify which pair to use rather than requesting extra channel details.

`channel_type` controls local documentation scope, not actual channel identity. Retain an existing value; use distribution when explicitly known, otherwise keep the client default for a new profile. Do not make it a routine additional question or claim the default proves identity. Server authentication decides actual identity/permissions; do not bypass denial with another credential set.

## Agent configuration input

These are internal Agent commands, not a requirement for users to prepare JSON or operate a terminal. Normalize supplied credentials to `app_key` / `app_secret` and pass them through standard input, not command-line argument values.

```bash
python3 scripts/flow_api.py configure --profile test-channel --environment test --storage env --data -
python3 scripts/flow_api.py configure --profile prod-channel --environment production --storage env --data -
```

`--data -` reads a JSON object with string fields `app_key` and `app_secret` from stdin. The Agent converts the user's input to this internal contract. `--data @existing.json` is also supported. Users who choose interactive configuration can omit `--data` to enter APPKEY/Secret through hidden prompts. Inline credential JSON in command-line arguments is rejected to avoid process-list exposure; this does not restrict users from providing credentials in chat.

Output contains configuration success, profile, environment, storage and local paths, not secrets. `setup --storage env` checks the entry point without credential access or network calls.

## Local .env files

Default path: `~/.config/bc-flow-api/credentials/<environment>-<profile>-<reference>.env`. `profiles.json` contains environment, channel type, `storage=env` and a reference only. With `--config`, the credentials directory follows that configuration file's directory, not the working directory. Do not discover/load unrelated project `.env` files.

Each profile has its own file containing profile/environment/channel binding and APPKEY/Secret. Reads validate the binding; test and production do not share a file or fall back to each other. Generated fields are `BC_FLOW_PROFILE`, `BC_FLOW_ENVIRONMENT`, `BC_FLOW_CHANNEL_TYPE`, `BC_FLOW_APP_KEY`, `BC_FLOW_APP_SECRET`. Users need not edit them manually. Values are read literally: no variable expansion or shell execution. Quotes, backslashes and valid Unicode secret characters are preserved.

`.env` is plaintext, not encrypted system storage. On macOS/Linux new directories are mode 700 and files mode 600; Windows relies on the private user directory's ACL. Normal API calls read files without updating configuration or creating runtime locks. Credential files stay outside the Skill, ZIP, Git, logs and replies; `.gitignore` excludes local credential files. Removing a profile deletes its `.env` but does not revoke the platform key.

Switch from system storage to `.env` using the same profile/environment/channel type:

```bash
python3 scripts/flow_api.py configure --profile test-channel --environment test --storage env --replace --data -
```

Use the credentials already supplied by the user; do not first access/unlock the old vault. Its old entry remains, with a reference for later cleanup, without blocking current use. Switching back with `--storage system --replace` saves the new system credential successfully before removing the old `.env`. Rotation within either mode similarly saves and verifies new credentials before updating references and removing old ones.

## Automatic runtime setup

Python 3.9+ is required. `.env` mode skips dependency setup. For system storage, first configuration or execution prepares dependencies automatically:

1. If the current Python imports keyring and the native backend, continue directly.
2. Otherwise check `~/.config/bc-flow-api/venv`; switch to it if usable, or install missing dependencies if its interpreter works.
3. If absent, create a dedicated virtual environment there, install `requirements.txt`, verify imports and execute the original command with it.

Installation is confined to this virtual environment, without system Python changes or administrator privileges. Test/production share the runtime while retaining separate credentials. The virtual environment is not distributed in the ZIP. Documentation, templates, profile metadata and previews remain usable offline without keyring.

Run from the Skill directory; launchers discover a usable interpreter:

```bash
# Prepare system-storage dependencies without reading credentials or calling the API
sh scripts/flow-api setup
sh scripts/flow-api configure --profile test-channel --environment test
sh scripts/flow-api call F014 --profile test-channel --execute
```

```powershell
# Native Windows: py -3, then python/python3, then the managed virtual environment
.\scripts\flow-api.ps1 setup
.\scripts\flow-api.ps1 configure --profile test-channel --environment test
.\scripts\flow-api.ps1 call F014 --profile test-channel --execute
```

Direct `python3 scripts/flow_api.py ...` / `py -3 scripts/flow_api.py ...` also supports setup. If PowerShell policy blocks `.ps1`, use `py -3 scripts/flow_api.py setup` without changing machine-wide execution policy.

If no working Python is found, the launcher provides the [official Python download link](https://www.python.org/downloads/). Install Python 3.9+ (enable PATH or the launcher on Windows), reopen the terminal and rerun. A Python script cannot install its own missing interpreter. The launcher does not silently install system software or open Microsoft Store. Managed devices may need an administrator to provide Python; this is not automatically solved.

First-time system dependency setup needs package-index network access. Progress goes to stderr and business JSON to stdout. Network/proxy/certificate/permission errors identify the failed stage and state that no API was called. Correct the environment and rerun to resume setup; do not request credentials again because of dependency failure. An existing non-venv directory or broken interpreter is not overwritten automatically.

Runtime setup uses no lock file: reuse a ready environment and create/install only when needed. Interpreter switching happens before reading business stdin, credentials or sending requests; arguments, working directory, stdin and exit status are preserved. A business failure, timeout or nonzero exit never triggers another execution. A ready runtime does not imply an unlocked native credential store.

Manual/offline preinstallation is supported: install requirements with the managed environment's Python, or preinstall keyring in the current interpreter. Do not put secrets in package-index settings or installation arguments. This uses standard [Python venv](https://docs.python.org/3/library/venv.html); activation scripts are unnecessary.

## Configure test and production once each

Use existing APPKEY/Secret from the corresponding environment's new sales platform, **API → Interface Authorization**. Do not obtain/reset platform keys on the user's behalf. Optional interactive commands, for users who choose this method:

```bash
python3 scripts/flow_api.py configure --profile test-channel --environment test
python3 scripts/flow_api.py configure --profile prod-channel --environment production
python3 scripts/flow_api.py configure --profile test-distributor --environment test --channel-type distribution
```

Interactive entry is hidden; Agent stdin configuration is equally supported. appKey must be an ASCII identifier suitable for an HTTP header. Future calls read the selected profile's credentials and sign locally without repeated input.

Each profile is fixed to one environment and channel type. Updating an existing profile cannot change these bindings; create a different profile when switching environment. Credentials cannot be verified as test/production offline solely from their contents, so configure the pair issued by the intended environment.

```bash
python3 scripts/flow_api.py profiles
python3 scripts/flow_api.py call F014 --profile test-channel --environment test --execute
python3 scripts/flow_api.py call F014 --profile prod-channel --environment production --execute
```

`call --environment` is an optional assertion, not an override. A mismatch fails before reading secrets or sending a request. Production actions still need authorization for the task. No profile means no automatic channel/environment choice; missing credentials do not cause another environment to be tried.

## System storage and access boundaries

| Platform | Native backend |
|---|---|
| macOS | `keyring.backends.macOS.Keyring`, login Keychain |
| Native Windows | `keyring.backends.Windows.WinVaultKeyring`, Credential Manager generic credentials |

System mode selects only these native backends, not automatically discovered plugins or null storage. env mode is a separate local file implementation. Windows uses `CRED_PERSIST_LOCAL_MACHINE`: same user and machine after logout/login, without cross-machine roaming; this does not grant other users access. Linux/WSL/containers can use `.env`; no bridge to the host vault is provided.

APPKEY/Secret are stored together with profile/environment/channel binding, checked on read. Native entry names are `BillionConnect/bc-flow-api/<environment>/<profile>/<random-reference>`; environments, profiles and credential versions have distinct entries.

`~/.config/bc-flow-api/profiles.json` stores metadata only:

```json
{
  "version": 2,
  "profiles": {
    "test-channel": {
      "environment": "test",
      "channel_type": "primary",
      "storage": "system",
      "credential_id": "<generated-reference-do-not-enter-manually>"
    }
  }
}
```

Configuration mutations use atomic replacement and a `.lock` file to prevent simultaneous modifications. This configuration lock is separate from runtime preparation and is not opened during normal calls. New macOS directories/files use 700/600; Windows protection uses user-directory ACLs, not POSIX chmod as encryption. Sensitive response files on Windows also belong in a private user directory.

Pass `--config /path/profiles.json` before the subcommand to use other metadata. Agents running as the same system user can share this configuration. Copying the Skill or metadata alone does not copy secrets; another user/machine needs its own setup. Copies of metadata still reference the same native entries, so do not treat them as independent backups for rotation/deletion.

- List, template, profiles and previews do not read stored secrets; execution reads them just before signing.
- If system storage fails, stop the call without fallback. Offer `.env`; configure it with supplied credentials if the user chooses it.
- Do not print credentials in arguments, logs or output. Responses echoing current credentials/signature are redacted.
- Native storage does not prevent a malicious process running as the same user with sufficient permissions from accessing secrets. Do not promise exclusive access by this Skill. Do not proactively read/display saved keys; accepting user-supplied keys is allowed.

## Rotation, removal and legacy migration

Updating a test profile leaves production unchanged:

```bash
python3 scripts/flow_api.py configure --profile test-channel --environment test --replace
python3 scripts/flow_api.py remove-profile --profile test-channel
```

Rotation: save new entry → read back and verify → atomically update metadata → remove old entry. Save failure retains the original configuration; cleanup failures are reported. Removal deletes the selected local profile and its system entry or `.env`, **not the platform key**. If native deletion succeeds but metadata saving fails, rerun removal to finish cleanup.

Legacy plaintext metadata requires explicit migration:

```bash
python3 scripts/flow_api.py migrate-credentials
```

All legacy profiles retain their environment, channel type and original keys. Save/read back every native entry before replacing metadata and removing plaintext fields. On failure, retain the original configuration and attempt cleanup of staged entries. No extra plaintext backup is created; historical backups, disk snapshots and old logs are outside this command's cleanup scope. Legacy plaintext profiles cannot be used directly for API calls and are not silently migrated during ordinary execution.

A forcibly terminated configuration process can leave a `.lock` or unreferenced native entry. Verify that no configuration process is running before cleanup; do not remove credentials used by another environment.

## Building and executing requests

Input contains only `tradeData`. The script creates `tradeType` and Shanghai-time `tradeTime`, serializes UTF-8 once, and uses the identical bytes for signing and HTTP.

```bash
python3 scripts/flow_api.py template F040
# Fill the template with real tradeData, then preview
python3 scripts/flow_api.py call F040 --profile test-channel --data @/absolute/path/trade-data.json
# Execute only after authorization and required order/recipient choices are clear
python3 scripts/flow_api.py call F040 --profile test-channel --data @/absolute/path/trade-data.json --execute --allow-write
python3 scripts/flow_api.py call F014 --profile test-channel --data '{}' --execute
```

`--data -` accepts JSON from stdin. Business input files must not contain authentication headers or appSecret. Replace `<field>` placeholders; actual execution rejects them.

Default timeout is 60 seconds; `--timeout` allows 1–300. A longer timeout does not authorize another order attempt. `--output /absolute/path/result.json` saves the complete redacted result with mode 600 on POSIX; the terminal normally shows only output path/success. With filters or summary options, it also shows the processed view. Avoid overwriting important files.

## PowerShell input and Unicode

Run in the Skill folder. Prefer UTF-8 JSON files (BOM supported) for both Windows PowerShell 5.1 and PowerShell 7; single-quote the `@path` argument. Do not put credentials in business request files.

```powershell
@{ language = "2"; countryCode = "JP" } | ConvertTo-Json -Compress | Set-Content -Encoding UTF8 .\query.json
.\scripts\flow-api.ps1 call F002 --profile test-channel --data '@.\query.json' --summary --execute
# Preview and authorized execution use the same file and channel order IDs
.\scripts\flow-api.ps1 call F040 --profile test-channel --data '@.\order.json'
.\scripts\flow-api.ps1 call F040 --profile test-channel --data '@.\order.json' --execute --allow-write
```

The client uses UTF-8 for stdin/stdout/stderr and documentation. PowerShell pipeline encoding is separate; if an older terminal displays Unicode incorrectly or sends non-ASCII text through pipes, set only the current session's encoding:

```powershell
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
@{ language = "2"; countryCode = "JP" } | ConvertTo-Json -Compress | .\scripts\flow-api.ps1 call F002 --profile test-channel --data - --summary --execute
```

Prefer `--output` to shell `>` redirection, which may re-encode output in older PowerShell. On JSON parsing errors, use file/stdin input instead of repeatedly experimenting with inline escaping. `describe F040` or a preview without `--execute` can check local encoding without credentials or an order.

## Local product and price display

These options process successful response tradeData locally. They do not change request bytes, signatures, server scope or rate limits. Multiple filters intersect; filtering precedes the display limit.

| Option | Operations | Behavior |
|---|---|---|
| `--sku-id ID` | F002/F003 | Exact full SKU ID match; no floating-point conversion |
| `--country-code JP` | F002 | Case-insensitive `country[].mcc` match using codes from F001/F002 |
| `--product-type 3106` | F002 | Exact type match, not a guarantee of F040 eligibility |
| `--limit 10` | F002/F003 | At most 10 products; does not truncate a SKU's price array |
| `--summary` | F002/F003 | F002 selection fields and country names/codes; F003 all quotes per selected SKU. Default 20 products; override with --limit |

```bash
python3 scripts/flow_api.py call F002 --profile test-channel --data @query.json --country-code JP --summary --limit 10 --output goods.json --execute
# Replace <SKU_ID> with the complete selected ID from F002
python3 scripts/flow_api.py call F003 --profile test-channel --data '{}' --sku-id '<SKU_ID>' --summary --output prices.json --execute
```

The view records received/matched/shown counts and whether it is truncated. No match means no match in this response, not proof of absence across other channels/scopes. Unexpected tradeData shapes preserve the original response. The output file always holds the complete redacted result, not just displayed rows; reuse it when appropriate instead of repeating full API requests.

## Network failures

Diagnostics distinguish proxy authentication (407), connection refusal, DNS, TLS and timeout. They show the actual route and a redacted proxy address. A refused localhost proxy port suggests checking the proxy process/port; a timeout through a proxy alone does not prove the proxy is broken. The client follows Python/system proxy settings and NO_PROXY and does not clear proxies, alter NO_PROXY, disable TLS verification or retry automatically. Users may adjust networking according to their network policy; server-side IP controls still apply. Unknown writes require checking the original order identifiers.

## Results and exit codes

| Exit | Meaning |
|---|---|
| 0 | Preview/local operation succeeded, or HTTP 200 with tradeCode=1000 |
| 2 | Local configuration, allowlist, parameters or execution conditions failed; preflight/vault failures send no request |
| 3 | Valid API response with business failure; inspect response.tradeCode/tradeMsg |
| 4 | Network, TLS, HTTP/redirect or invalid response; no retry, write outcome unknown |
| 5 | API succeeded but saving the result failed; complete result printed to stdout; do not repeat the write |
| 130 | Interrupted; if a request was sent, query to verify the outcome |

`executed=true` means sending was attempted, not business success. `success=true` means API success, not completed fulfillment. Endpoint selection and previews remain possible without credentials; ask for credentials only when an actual call needs them.

## Native storage check

```bash
python3 scripts/check_credential_store.py --execute
```

Creates synthetic test/production entries, reads them back from a separate Python process, then deletes them. Does not read real profiles or call a business API. Locked or unauthorized storage causes failure; this is not a completed native-storage acceptance result. The same script can be used for an authorized native Windows check.

Implementation references: [keyring](https://keyring.readthedocs.io/en/stable/), [Windows credential types and persistence](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw).
