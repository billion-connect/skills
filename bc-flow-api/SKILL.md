---
name: bc-flow-api
description: Operate BillionConnect Flow SIM/eSIM APIs. Use for requests such as "order an eSIM", "buy an eSIM", "list eSIM products/prices", "check my balance", top-ups, usage, cancellations or after-sales service when no other platform is specified. Also use for explicit Flow, BillionConnect, new sales platform, F-series API or channel APPKEY/Secret requests. Supports only the 33 documented F APIs. Respect an explicitly selected eSIM Access/api.esimaccess.com supplier; not for platform UI or sending N-series callbacks.
---

# Flow F-series API — English edition

Covers the 33 F APIs in the new sales platform's `/apiManage/interfaceDoc`, checked against `manage-api`. The distribution page lists 11 of them. The catalog is an explicit allowlist; do not include every backend operation beginning with F.

## Request routing

- For requests such as "order an eSIM" or "buy an eSIM" without another platform specified, read this Skill and follow the F040 workflow. Users do not need to know endpoint codes.
- Respect an explicitly selected supplier, including eSIM Access. Technical discussion about eSIMs is not an instruction to place an order.
- Selecting the Skill does not select test or production. Ask only for missing environment, destination/product, plan or other required details. The Agent manages profile names. Do not default to production, use example SKUs or immediately submit an order with unspecified choices.
- If credentials are missing, help configure them using this Skill; do not switch to another provider.

## Workflow

1. Find the operation in the [API index](references/index.md) or `scripts/flow_api.py list`, then load its `references/interfaces/Fxxx.md`. Read [Protocol and environments](references/protocol.md) first; do not mix API 1.0, API 2.0 or supplier protocols.
2. Establish environment, credentials and target from the conversation. APPKEY/Secret already identifies the channel; do not ask for its name, ID or "which channel". Use `profiles` to inspect configured aliases; reuse or create an alias for the selected credentials and pass `--profile` explicitly. Users need not name it. Test/production are bound separately; see [Credentials identify the channel](references/credentials.md#credentials-identify-the-channel).
3. Query products/prices/target state first and use real business values. Prefer `--summary` for product lists, then `F003 --sku-id ID --summary` for exact quotes. `--output` preserves the full response; see [Local product and price display](references/credentials.md#local-product-and-price-display). `template Fxxx` produces only tradeData with placeholders. Interpret amounts, units, days and card quantities using the field definitions. Never copy example order IDs, ICCIDs, SKU IDs or emails into real calls.
4. Preview with `call Fxxx --data @file --profile alias`. Authorized queries can use `--execute` directly. Writes require user authorization for this action and `--allow-write` in addition to `--execute`. Do not ask again when authorization is already clear. First obtain any missing product, quantity, target order or recipient when email delivery is required.
5. Check HTTP status and `tradeCode`: API 2.0 success is `1000`, not supplier code `0000`. Report environment, operation, target and result. Verify final state through the [Business workflows](references/workflows.md); API success alone does not prove QR delivery, email delivery or refund settlement.

## Credentials and execution

Credentials can use a local `.env` (`--storage env`) or native system storage (`--storage system`). `.env` requires no keyring or Keychain authorization and can simplify setup; briefly explain that it is a private local plaintext file without adding repeated confirmations. Configure test and production separately. See [Credentials and calls](references/credentials.md).

When credentials are missing, ask: **"Please provide your API credentials."** Do not prescribe a terminal, chat input or file format; let the user choose. Accept APPKEY/Secret already supplied in the conversation and format it internally without asking the user to provide it again another way. Do not echo secrets after configuration. If only one component is missing, ask only for that component. Credentials select the channel; local aliases and channel type are not additional required user questions. Reuse the known environment, asking only when it is genuinely missing.

Run commands relative to the Skill folder; use absolute script paths from elsewhere. On macOS prefer `sh scripts/flow-api ...`; on native Windows use `.\scripts\flow-api.ps1 ...`. Direct Python invocation also works. System storage alone needs keyring: reuse current dependencies, then a usable managed virtual environment, otherwise prepare one automatically. `.env` uses only the standard library. Do not require repeated manual installation or re-entry of credentials when changing interpreters. Guide Python installation only after the launcher finds no Python 3.9+. `setup` prepares dependencies without accessing credentials or the API.

```bash
python3 scripts/flow_api.py list
python3 scripts/flow_api.py describe F040
python3 scripts/flow_api.py template F040
python3 scripts/flow_api.py profiles
python3 scripts/flow_api.py call F014 --profile test-channel --data '{}' --execute
```

`call` sends nothing by default. Templates, documentation and previews without a profile need no credentials. Prefer UTF-8 JSON files on Windows; see [PowerShell input and Unicode](references/credentials.md#powershell-input-and-unicode). Network requests do not retry or follow redirects. Keep batches within the user's specified scope; an empty query is not a reason to retry everything or change channels.

For English requests, use the documented English language value where available: commonly `language="2"`, but F059 uses `language="en"`. Check each endpoint; do not add unsupported fields. The script does not silently rewrite request data. Translate explanations for the user while retaining raw API fields, codes and identifiers. Server messages and sample response text may still be Chinese.

Handle noisy product names, missing optional fields and irrelevant unusual quotes according to the references without asking the user about each one. Reuse known channel, product and delivery choices; ask together only for details the task actually needs.

## Essential constraints

- Write operations: F006/F007/F008/F009/F016/F017/F018/F019/F040/F041/F045/F061. F041 sends real email and requires an explicit send/resend request. F045 ends plan service; do not use it as a query or refund operation.
- Timeout, disconnect, invalid JSON or gateway failure means the write outcome is unknown. Query by the original business identifiers first. Do not automatically reorder or generate new channel order IDs to bypass duplicate checks.
- Read credentials only from the selected profile's system store or local `.env`; do not search repositories, databases or historical logs for keys. User-supplied credentials can be configured, but never echo secrets/signatures or put them in the Skill, examples or Git. If system storage is unavailable, explain the `.env` option. After the user chooses it, save supplied credentials with `configure --storage env --replace` without first reading/unlocking the old vault. Do not silently switch storage or environments after failure.
- Do not substitute browser sessions, Shopify apiKeys or internal `/v3` endpoints for channel signing. Report IP allowlist or permission denials without changing permissions or impersonating another channel.
- This is an external API tool, not a replacement for any project-required UI acceptance test. Reading code/protocols does not require a browser.

## Maintenance and validation

- [Sources and coverage](references/sources.md) records source versions, 33/11 coverage, backend methods and test-branch differences. A successful test for one channel/environment does not establish universal access.
- `references/operations.json` is the client allowlist and basic validation metadata; per-operation Markdown contains full fields and business notes. New endpoints require checking the actual frontend listing, backend dispatch and read/write behavior together.
- `python3 -B -m unittest discover -s scripts -p 'test_*.py'` runs offline tests without real services or credentials.
- `scripts/check_credential_store.py --execute` checks native storage with temporary synthetic credentials and no business calls. Run only when a system-storage check is authorized; offline tests do not establish native-platform acceptance.

This maintained English Skill retains the original `~/.config/bc-flow-api` credential namespace for compatibility. Updating from an older Chinese installation does not migrate or delete credentials. See the README for installation and preserving a backup of an older edition.
