# Sources and coverage

Initial review: 2026-10-08. Scope follows the specified frontend documentation page, not a scan of all backend F constants. This file records source snapshots, not a claim about currently deployed versions.

## Source versions

- Documentation: https://portal-ts.billionconnect.com/#/apiManage/interfaceDoc
- flow-sale-frontend origin/stage: `7494f01b2b385a57affc6c243a4d68b04469c995`; the reviewed remote test branch was named stage.
- flow origin/master: `93d717b36c5f85a7809267189b7ed2febed18009`.
- flow origin/stage_20260707: `ed39e69a91bb5d8af39d9941d99ceb8c5c3d9e90`.

## Frontend paths

Paths relative to flow-sale-frontend:

- `apps/flow-sale-frontend/src/router/routes/modules/apiManage.ts` → `/apiManage/interfaceDoc`.
- `apps/flow-sale-frontend/src/views/apiManage/interfaceDoc/index.vue` selects ordinary/distribution docs by sale.type.
- `common-channel.vue` in that directory: 33 active F entries in apiList.
- `distribution-channel.vue`: 11 active F entries, excluding commented code.
- `apps/flow-sale-frontend/src/locales/langs/zh-CN/doc.json`: original field descriptions/enums.
- `apps/flow-sale-frontend/src/views/apiManage/accessGuide/tables/communication-protocol.vue`: endpoints and protocol.
- `api-playground.vue` in the documentation directory: array tradeData, JSON construction and MD5 signing.

Nested request/response fields are retained. F011 includes both card and top-up response structures/examples. The 11 distribution operations have the same request fields as their ordinary-channel counterparts, with scope marked separately. Historical dates, IDs and email addresses are format examples, not real test targets.

## Backend sources

Paths relative to flow. Unified entry: request/dispatchRequest in `manage-api/src/main/java/com/op/flow/manage/api/controller/SaleController.java`.

Authentication: `controller/base/BaseController.java` in the same module. Signing: `manage-core/src/main/java/com/op/flow/manage/core/util/SignUtil.java`. Responses: `SaleResponseBody.java` in the same package.

| F operation | Backend method | Master line |
|---|---|---|
| F001 | `SaleApiService.querySaleCoverCountrys` | 2253 |
| F002 | `SaleApiService.queryGoodsHandle` | 2013 |
| F003 | `SaleApiService.queryGoodsPrice` | 2088 |
| F004 | `SaleApiService.querySelfPickPointMsg` | 2346 |
| F005 | `SaleApiService.queryLogisticsCompanyMsg` | 2390 |
| F006 | `SaleOrderApiService.createOrderHandle` | 137 |
| F007 | `SaleOrderApiService.createOrderHandle` | 137 |
| F008 | `SaleOrderApiService.cancelOrderHandle` | 792 |
| F009 | `SaleApiService.modifyLogisticMsg` | 2431 |
| F010 | `SaleApiService.queryCardValidVersion2Point0` | 2454 |
| F011 | `SaleApiService.queryOrderInfoVersion2Point0` | 2744 |
| F012 | `SaleApiService.queryPackagesUsedMsg` | 3055 |
| F013 | `SaleApiService.queryValidateAddPackageIccids` | 3369 |
| F014 | `SaleApiService.querySaleAccountBanance` | 4264 |
| F015 | `SaleApiService.queryAccelerationPackageCommoditiesHandle` | 4286 |
| F016 | `SaleApiService.createAccelerationOrderHandle` | 4339 |
| F017 | `SaleApiService.applyAfterSale` | 4410 |
| F018 | `SaleApiService.cancelAfterSale` | 4666 |
| F019 | `SaleApiService.modifyAfterSale` | 4693 |
| F020 | `SaleApiService.queryMessageOfAfterSale` | 4775 |
| F023 | `SaleApiService.dailyFlowQuery` | 4898 |
| F040 | `SaleOrderApiService.createOrderHandle` | 137 |
| F041 | `SaleOrderApiService.reSendESIMEmail` | 1449 |
| F042 | `SaleOrderApiService.queryESIMProfileStatus` | 1492 |
| F045 | `SaleOrderApiService.manuallyEndingPackage` | 1549 |
| F046 | `SaleApiService.queryPackagesUsageInfo` | 5295 |
| F051 | `SaleApiService.querySelfPickPointBySku` | 5683 |
| F052 | `SaleApiService.queryESIMRechargeGoods` | 5709 |
| F054 | `SaleOrderApiService.queryRealNameStatus` | 1691 |
| F056 | `SaleOrderApiService.queryAllAccelerationPackageCommodities` | 1734 |
| F059 | `SaleApiService.queryBoosterPackageGoodsHandle` | 6266 |
| F060 | `SaleApiService.queryResourceSeriesCarrierFee` | 6241 |
| F061 | `SaleApiService.createBoosterPackageOrderHandle` | 6324 |

Deeper ordering chain: SaleOrderApiService → SaleOrderHandleService / DistributionOrderService → procurement, transactions and ESIMOrderService. Special multi-eSIM paths record tasks through KddiMultiESIMRecordService. AfterSaleService handles after-sales, ShutdownPlanRecordService handles F045, and BoosterOrderService handles F061.

See [Protocol and environments](protocol.md) for additional test-branch after-sales gates. Apart from the additional F017 after-sales switch, the reviewed 33 dispatched methods matched their master counterparts. This does not establish identical deeper services or production deployments.

## Excluded scope

N callbacks, M/U series, API 1.0, internal /v3, Shopify, supplier APIs and backend-only operations absent from this page, such as F021/F085. Scope changes require checking actual page entries, not merely accepting a prefix.

## Documentation additions from 2026-10-12 feedback

That update changed the Skill/CLI and guidance, not backend APIs, response fields, channel permissions or test products. It used local Flow snapshot `7225be51f5`, without verifying each deployed environment:

- `manage-api/.../SaleApiService.java`, queryGoodsPrice/getSaleGoodsPrice: F003 SKU filtering and quote days/copies relationship.
- `manage-api/.../SaleOrderApiService.java`, F040 validation: days and planSkuCopies each 1–730; no new client business gate was added for this note.
- `manage-core/.../SaleOrderHandleService.java`, getSaleGoodsStrategy and order responses: eSIM candidate types and ordering-state meaning.
- `manage-core/.../SkuConstants.java`: TYPE_ESIM_AIR=250.
- `manage-core/.../SaleResponseBody.java`, success overloads: optional pickupCode/successFlag locations, conditions and meaning.

Product-name noise, missing currency and unusual durations were documented without claiming product configuration repairs. Existing N009/email delivery was retained; no F endpoint or callback receiver was added.

## English edition

The English copy retains the current Chinese Skill's API contracts, catalog, request examples and runtime behavior. Matching field labels reuse the frontend en-US/doc.json translations, with additional translation of operational notes and CLI messages. Raw API example values and Unicode test fixtures remain unchanged; their language is not evidence of a different API contract. No new live API validation is implied by translation.
