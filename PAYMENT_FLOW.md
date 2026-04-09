# SnapFix — Payment Flow Guide

### Mobile Team Handover Document

---

## 1. Overview

Every service request carries a **payment split** made of two parts:

```
final_price  =  wallet_amount  +  card/cash amount
```

| Field            | What it means                                                      |
| ---------------- | ------------------------------------------------------------------ |
| `payment_method` | How the **non-wallet** portion is paid: `cash` / `card` / `wallet` |
| `wallet_amount`  | How much is deducted from the customer's in-app wallet             |
| `card_amount`    | **Read-only, computed** = `final_price − wallet_amount`            |
| `final_price`    | Locked when customer approves the quote — never changes after that |
| `payment_status` | `pending` → `paid` / `failed`                                      |

### Payment method values

| Value      | Meaning                                                                  |
| ---------- | ------------------------------------------------------------------------ |
| `"cash"`   | Provider collects cash in person. Platform never touches that money.     |
| `"card"`   | Card is charged via Stripe for the `card_amount` portion.                |
| `"wallet"` | Entire `final_price` comes from wallet (`wallet_amount == final_price`). |

> **Wallet + card combo:** Set `payment_method = "card"` and `wallet_amount > 0`.
> The wallet covers part of the bill; the card covers the rest.

---

## 2. Payment Fields on Every Service Request Response

```json
{
  "payment_method": "card",
  "payment_method_display": "Card (Stripe)",
  "wallet_amount": "50.00",
  "card_amount": "150.00",
  "payment_status": "pending",
  "payment_status_display": "Pending",
  "estimated_price": "200.00",
  "quoted_price": "200.00",
  "final_price": "200.00"
}
```

`final_price` is `null` until the customer approves the quote.
`quoted_price` is `null` until the provider submits a quote.
`card_amount` is always `final_price − wallet_amount` (or `null` if no final price yet).

---

## 3. The Three Payment Flows

---

### Flow A — Cash (simplest)

Customer pays the provider directly in person. The platform does not process money.

```
POST /api/v1/bookings/requests/
  payment_method: "cash"
  wallet_amount:  0         ← optional, defaults to 0

      ↓ (provider quotes, customer approves, job runs)

POST /api/v1/bookings/requests/<id>/complete/
  → payment_status becomes "paid" automatically (honor system)
  → provider's available_balance is NOT credited (cash goes to them directly)
  → provider's total_earnings IS credited (for tracking)
```

**No Stripe calls. No card screens. Nothing for the mobile app to do.**

---

### Flow B — Wallet (full amount from wallet)

Customer's in-app wallet covers the entire bill.

```
POST /api/v1/bookings/requests/
  payment_method: "wallet"
  wallet_amount:  <estimated_price or 0>   ← set to your best estimate; re-validated later

      ↓ provider quotes, customer approves quote ↓

POST /api/v1/bookings/requests/<id>/approve-quote/
  {
    "payment_method": "wallet"
    // wallet_amount is auto-set to full quoted_price by the backend
  }
  → 400 if wallet_balance < quoted_price

      ↓ job runs ↓

POST /api/v1/bookings/requests/<id>/complete/
  → wallet_amount deducted from customer balance (row-locked)
  → payment_status → "paid"
  → provider's available_balance credited
```

**No Stripe. Show wallet balance on the approve-quote screen.**

---

### Flow C — Card (Stripe) — requires mobile integration

The card covers `card_amount = final_price − wallet_amount`.
`wallet_amount` can be 0 (pure card) or > 0 (wallet + card combo).

```
Step 1 ── Customer creates request
  POST /api/v1/bookings/requests/
  {
    "payment_method": "card",
    "wallet_amount":  0       ← or any amount ≤ estimated_price
  }

Step 2 ── Provider submits quote
  POST /api/v1/bookings/requests/<id>/quote/
  { "price": "200.00" }

Step 3 ── Customer approves quote  [can adjust wallet_amount here]
  POST /api/v1/bookings/requests/<id>/approve-quote/
  {
    "payment_method": "card",
    "wallet_amount":  50.00   ← optional: use 50 from wallet, 150 from card
  }
  → status becomes "confirmed"
  → final_price is now locked

Step 4 ── Customer initiates card payment  ★ KEY STEP ★
  POST /api/v1/bookings/requests/<id>/initiate-card-payment/
  {
    "stripe_payment_method_id": "pm_xxx"   ← from Stripe SDK on the device
  }

  Response 200:
  {
    ...service_request_fields...,
    "stripe_client_secret": "pi_xxx_secret_yyy"   ← use this to confirm on device if needed
  }

  What happens on the backend:
  - Creates a Stripe PaymentIntent for card_amount (capture_method="manual")
  - Card is AUTHORIZED (hold placed) but NOT yet charged
  - Stores stripe_payment_intent_id on the service request

Step 5 ── Provider completes the job
  POST /api/v1/bookings/requests/<id>/complete/
  → Stripe PaymentIntent.capture() is called automatically
  → Card is charged for card_amount
  → Wallet is deducted for wallet_amount
  → payment_status → "paid"
  → provider's available_balance credited (wallet + card portions)
```

---

## 4. Approve-Quote — Adjusting Payment at Price Confirmation

The customer can change their payment split when they see the real price:

```
POST /api/v1/bookings/requests/<id>/approve-quote/

Body (all fields optional — omit to keep the values from booking time):
{
  "wallet_amount":  50.00,    // how much to use from wallet
  "payment_method": "card"    // how to cover the remainder
}
```

| Scenario             | Body to send                                                                |
| -------------------- | --------------------------------------------------------------------------- |
| Full cash, no wallet | `{ "payment_method": "cash", "wallet_amount": 0 }`                          |
| Full wallet          | `{ "payment_method": "wallet" }` — backend sets wallet_amount = final_price |
| Wallet + card        | `{ "payment_method": "card", "wallet_amount": 50 }`                         |
| Pure card            | `{ "payment_method": "card", "wallet_amount": 0 }`                          |
| No change            | Send empty body `{}`                                                        |

**Errors:**

- `400` if `payment_method = "wallet"` and `wallet_balance < quoted_price`
- `400` if `wallet_amount > wallet_balance`

---

## 5. Does the Mobile App Need the Stripe SDK?

Yes — but **only for card payments**. Cash and wallet flows have no Stripe involvement.

### Why the SDK is required

The mobile app must call `stripe.createPaymentMethod(cardDetails)` on-device, which returns a `pm_xxx` token. Raw card numbers **never touch your backend** — this is how Stripe enforces PCI compliance.

### What the SDK does

1. Renders the card input UI (number, expiry, CVC)
2. Sends card data directly to Stripe's servers (not your backend)
3. Returns a `pm_xxx` payment method ID to the app
4. App sends only that `pm_xxx` to `/initiate-card-payment/`

### SDK packages by platform

| Platform     | Package                       |
| ------------ | ----------------------------- |
| React Native | `@stripe/stripe-react-native` |

### Initializing the SDK

Use the **publishable key** (not the secret key) to initialize Stripe on the mobile side.
The publishable key (`pk_test_...`) is safe to embed in the app — ask the backend team for it.

---

## 6. Initiate Card Payment — Stripe SDK Integration

### What the mobile app must do

1. Collect card details using **Stripe's native SDK** (iOS/Android).
2. Call `stripe.createPaymentMethod(card)` → returns a `pm_xxx` string.
3. POST that `pm_xxx` to `/initiate-card-payment/`.
4. The response includes `stripe_client_secret` — use it to call `stripe.confirmPayment()` if 3D Secure is required.

```
POST /api/v1/bookings/requests/<id>/initiate-card-payment/
Authorization: Token <customer_token>

{
  "stripe_payment_method_id": "pm_1Abc123..."
}
```

**Validation errors:**
| Error | Cause |
|---|---|
| `400` "Card payment initiation is only required when payment method is CARD." | `payment_method` is not `"card"` on this request |
| `400` "No card amount to charge — wallet covers the full price." | `wallet_amount == final_price` so there's nothing to charge |
| `400` "Stripe error: ..." | Stripe rejected the PaymentMethod (invalid card, etc.) |

**When to call this:**

- After `approve-quote` → status is `confirmed`
- Before the provider starts/completes the job
- Can be called again to replace the PaymentMethod if the customer wants to use a different card

---

## 6. Full Status + Payment State Table

| Status               | payment_status | What the mobile app should show                     |
| -------------------- | -------------- | --------------------------------------------------- |
| `pending`            | `pending`      | Waiting for a provider                              |
| `assigned`           | `pending`      | Provider assigned, waiting for quote                |
| `quoted`             | `pending`      | Show quoted price, approve/reject buttons           |
| `confirmed` (cash)   | `pending`      | Job confirmed, waiting for provider                 |
| `confirmed` (card)   | `pending`      | **Show "Set up card payment" prompt**               |
| `confirmed` (wallet) | `pending`      | Job confirmed, wallet will be charged at completion |
| `in_progress` (card) | `pending`      | Job in progress — card will be charged when done    |
| `completed`          | `paid`         | Job done, payment settled                           |
| `cancelled`          | `pending`      | Request cancelled                                   |

---

## 7. Stripe Test Cards (Sandbox)

Use any future expiry date, any 3-digit CVC, any postal code.

| Card number           | Scenario                          |
| --------------------- | --------------------------------- |
| `4242 4242 4242 4242` | Success — payment goes through    |
| `4000 0025 0000 3155` | Requires 3D Secure authentication |
| `4000 0000 0000 9995` | Declined — insufficient funds     |
| `4000 0000 0000 0002` | Declined — generic decline        |

To get a `pm_xxx` for Postman testing (no mobile SDK needed):

```bash
curl https://api.stripe.com/v1/payment_methods \
  -u sk_test_YOUR_KEY: \
  -d type=card \
  -d "card[number]=4242424242424242" \
  -d "card[exp_month]=12" \
  -d "card[exp_year]=2026" \
  -d "card[cvc]=123"
```

Copy the `id` from the response (`pm_...`) and use it in `/initiate-card-payment/`.

---

## 8. Error Reference

| Endpoint                       | Status | Message                                      | Fix                                            |
| ------------------------------ | ------ | -------------------------------------------- | ---------------------------------------------- |
| `POST /requests/`              | `400`  | `wallet_amount: Insufficient wallet balance` | Show wallet balance, reduce wallet_amount      |
| `POST /approve-quote/`         | `400`  | `Insufficient wallet balance`                | Customer wallet was depleted since booking     |
| `POST /initiate-card-payment/` | `400`  | `Stripe error: Your card was declined.`      | Ask customer to use a different card           |
| `POST /complete/`              | `500`  | `Card payment failed: ...`                   | Stripe capture failed — check Stripe dashboard |

---

## 9. Provider Balance — What Gets Credited

After `/complete/`:

| Payment method        | `available_balance` credited                 | `total_earnings` credited |
| --------------------- | -------------------------------------------- | ------------------------- |
| `cash`                | ✗ (provider collected cash directly)         | ✓ full `final_price`      |
| `card`                | ✓ full `final_price`                         | ✓ full `final_price`      |
| `wallet`              | ✓ full `final_price`                         | ✓ full `final_price`      |
| `card` + wallet combo | ✓ `card_amount + wallet_amount` = full price | ✓ full `final_price`      |

`available_balance` is what the provider can withdraw. `total_earnings` is lifetime tracking only.

---

## 10. Quick Cheat Sheet

```
Cash job (simplest):
  Create → (assigned) → Quote → Approve → Start → Complete ✓

Wallet job:
  Create (wallet_amount≈estimate) → Quote → Approve (wallet_method, wallet covers all)
  → Start → Complete ✓  [wallet deducted at complete]

Card job:
  Create (payment_method=card) → Quote → Approve → initiate-card-payment (pm_xxx)
  → Start → Complete ✓  [card captured at complete]

Wallet + Card combo:
  Create (payment_method=card, wallet_amount=50) → Quote → Approve
  → initiate-card-payment → Complete ✓  [wallet deducted + card captured at complete]
```
