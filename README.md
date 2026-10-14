# BillionConnect Skills

Agent Skills for BillionConnect SIM/eSIM APIs.

## Available Skills

| Skill | Language | Capabilities |
|---|---|---|
| [bc-flow-api](bc-flow-api/README.md) | English | 33 documented Flow F-series APIs for products, pricing, balance, orders, usage, shipping and after-sales |

## Install

```bash
npx skills add https://github.com/billion-connect/skills --skill bc-flow-api
```

Alternatively, clone the repository and follow the [manual installation instructions](bc-flow-api/README.md#installation). Keep the complete Skill folder together. Start a new Agent session after installation.

Example request: **Use $bc-flow-api to show Japan eSIM products and prices.**

API execution requires Python 3.9+ and your channel APPKEY/Secret. Test and production credentials are configured separately. Choose a private local `.env` file or native macOS/Windows credential storage; no real credentials are included in this repository. See [credential setup](bc-flow-api/references/credentials.md).

Requests default to preview. Real calls require `--execute`; writes additionally require `--allow-write` and user authorization for the specific action. Requests are not retried automatically. API acceptance is distinct from delivery or refund completion.

## Validation

```bash
python3 -B -m unittest discover -s bc-flow-api/scripts -p 'test_*.py'
```

Offline tests use synthetic data and do not create real orders. Native Windows validation and live API outcomes are documented separately in the [Skill README](bc-flow-api/README.md#tests-and-validation-scope).

## License

The repository retains its [Apache-2.0 license](LICENSE). The separately licensed `bc-flow-api` package retains its [MIT license](bc-flow-api/LICENSE).
