# Business workflows

## Products and quotes

F001 countries → F002 products → F003 prices/plan units. Use SKU IDs returned for the current channel; distribution channels cannot reuse parent-channel product IDs. The reviewed F003 implementation may ignore the intended skuId filter: select the matching product from the response, using `--sku-id ID --summary`, without applying another SKU's quote. Handle coverage, eligibility, currency and unusual durations as described in [F002](interfaces/F002.md#selecting-products) and [F003](interfaces/F003.md#using-quotes). Absorb irrelevant catalog noise and explain only constraints affecting this choice. Use F014 for balance; isOpen=0 is different from a zero balance.

## eSIM orders, top-ups and status

1. Use F002/F003 to verify eSIM products and available units. Establish product, quantity, travel date/units and authorization before F040. email is optional; omit it if email delivery is not needed, and do not insert a real recipient merely for testing.
2. Save the completed request in one UTF-8 JSON file and reuse it for preview, execution and verification. Keep channelOrderId/channelSubOrderId stable. Do not generate new IDs to reorder after a timeout.
3. F040 accepts exactly one subOrderList object. number is card quantity; planSkuCopies or days controls the plan. Multiple cards do not mean multiple suborder objects.
4. API ordering normally synchronously executes the local order transaction and waits for a supplier response; ESIMCARD multi-quantity paths procure asynchronously. An orderId/success code does not prove profile/QR generation.
5. Reuse existing channel notifications or the user's chosen email delivery method; do not ask about notification integration before every order. Later delivery uses mechanisms such as N009, outside this Skill's callable scope. These 33 F APIs have no general QR retrieval endpoint. F042 is not a QR endpoint, and F040 does not guarantee a QR in its response. See [F040 response notes](interfaces/F040.md#response) for optional pickupCode/successFlag and their absence.
6. Primary channels can query the local order by channel order ID with F011. Once ICCID is known, use F042 for profile status and F046 for the target order's plan. Distribution channels use only documented distribution operations. If ICCID is missing and these F APIs cannot verify the result, report pending notification/manual verification without internal endpoints or switching channels.
7. F041 sends to a specified email only when explicitly requested. Acceptance does not prove delivery.

Top-up: F052 finds eligible SKUs by ICCID → F003 verifies price/units → optional F013 validation → F007 order → F046 verification. F007 suborder iccid is an array. Product rules still govern eSIM top-up restrictions. ESIMCARD top-ups may await resource results after acceptance.

## Acceleration and data boosters

- Acceleration: F015 queries products for the order/ICCID (array tradeData), or F056 queries all applicable acceleration products. F016 purchases against the original order with exactly one subOrderList object.
- Data booster: F059 queries products (`language=zh/en`) → F061 creates an order with originalOrderId, ICCID, skuId, stackDataType and stable channelOrderId. Judge failure using tradeCode/tradeMsg, not legacy tradeData.result/failReason.

## Card orders and shipping

F004/F051 query pickup points; F005 returns shipping codes. F006 creates a card order with express/selfPickup. F009 updates shipping; F011 verifies order/shipping details. These are absent from the distribution page and the client does not execute them in distribution mode.

A card-only quote's `days=0` is pricing metadata, not valid F006 order days. Without an additional plan, omit `planSkuId`, set `planSkuCopies` from the quote's valid `copies` (for example 1), and omit `days`. F006 validates supplied days/units as 1–730.

## Usage and after-sales

- F010 queries card validity; F012 card plans; F046 order/card plans; F023 daily usage. Empty results do not prove no consumption: consider query scope, supported resources and reporting delay.
- F008 cancels an order, F045 ends an activated plan, and F017 requests after-sales service. These are distinct actions and cannot substitute for one another.
- After-sales: F017 request → F020 review/refund status; F018 cancels the request; F019 modifies it. Establish the exact order, scope and refund conditions first. Stop on a test-environment permission denial; do not change allowlists or after-sales switches.
- A plan not activated and an eSIM profile not downloaded are different states. F012/F046 activation results cannot replace F042 download history. For cancellation before download, check profile records and actual delivery; an empty F042 result is not proof that no download occurred.

## Uncertain outcomes

A timeout can occur after the server has charged the account or created an order. The client does not retry automatically. Query the original identifiers and business state before deciding what comes next; if there is no suitable F query, report an unknown outcome. Read retries also need a task-specific count/time bound, not endless polling. Batch writes must stay within the authorized list; pause further writes for any item whose outcome is unknown.
