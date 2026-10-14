# Protocol and environments

## Endpoints and versions

| Environment | POST endpoint |
|---|---|
| test | https://api-flow-ts.billionconnect.com/Flow/saler/2.0/invoke |
| production | https://api-flow.billionconnect.com/Flow/saler/2.0/invoke |

These endpoints come from the frontend integration guide. Backend class mappings support both `/Flow/sale` and `/Flow/saler`. The client uses the guide's HTTPS endpoints without HTTP downgrade or redirects. If test networking does not support the configured HTTPS address, investigate the gateway first; do not send credentials to an arbitrary replacement domain.

`portal-ts` hosts the documentation/sales platform, not the API. Its playground uses a management proxy, while this Skill directly signs requests with channel credentials. Legacy `/invoke` operation codes such as F004 differ from API 2.0; do not mix them.

## Authentication

```text
x-channel-id: <appKey>
x-sign-method: md5
x-sign-value: lowercase_hex(MD5(UTF8(appSecret) + exact_request_body_bytes))
Content-Type: application/json; charset=UTF-8
```

appKey identifies the channel. appSecret is used only for local signing and is not sent separately. This is not HMAC: do not sort fields, insert the signature into the body or reformat JSON after signing. The backend chain `BaseController.checkSaleSign` → `SignUtil.checkSaleSign` → `SignUtil.sign(String secret, String requestBody)` verifies the complete original request string. Do not use similarly named supplier-specific overloads.

```json
{"tradeType":"F014","tradeTime":"2026-10-08 12:00:00","tradeData":{}}
```

Timestamp format: `yyyy-MM-dd HH:mm:ss`. Most operations use object tradeData; F015 uses an array. Keep long order IDs, SKU IDs and ICCIDs as strings to avoid JavaScript precision loss. Most documented language fields use `1/2`; F059 uses `zh/en`. Interpret money and data units per endpoint, without eSIM Access's currency scaling.

## Responses

A raw server response may contain Chinese text:

```json
{"tradeCode":"1000","tradeMsg":"成功","tradeData":{}}
```

Check HTTP status, then tradeCode. HTTP 200 can still carry a business failure. Successful tradeData may be an object, array, null or empty string. Do not interpret null/empty arrays automatically as zero balance, zero usage, missing permission or cancellation. The backend maps supplier code `0000` to the external API's `1000`.

## Permissions and version differences

- appKey determines the actual Sale, primary/distribution identity and accessible data. Clients do not choose a channel by supplying saleId. Supplied credentials select the channel; do not additionally ask for its name/ID. The Agent manages the local profile alias, with the established test/production environment.
- The backend enforces IP allowlists and IP/channel blocklists. Preserve the meaning of errors such as `IP not in whitelist`, `No permission` and channel request queuing; do not bypass them with another profile.
- The frontend uses `sale.type===2` for distribution documentation, with 11 active F entries. Commented-out entries are excluded. Backend support alone does not mean an endpoint is exposed in that documentation.
- Reviewed test branch `ed39e69a91` checks API after-sales permission (`caseId=29`) before dispatching F008/F017/F018/F019; F017 additionally checks the channel's after-sales switch. Reviewed master `93d717b36c` lacks these added entry checks. This does not establish the production deployment's behavior.
- Full F002/F003 product/price queries and operations such as F012/F046 have backend rate limits. Avoid frequent polling; do not guess a rate-limit interval from names. The client does not automatically retry a call.
- Field tables preserve the frontend contract; see each endpoint's Backend behavior section for runtime notes. Client validation rejects clear structural errors only. Conditional requirements, product permissions, prices, balance, inventory and supplier capabilities remain server decisions.
