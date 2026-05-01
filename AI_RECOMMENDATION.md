# AI Provider Recommendation

## 1. What this feature does

When a customer creates a service request with `booking_mode: "recommended"`, the API:

1. Saves the service request (status = `pending`).
2. Scores all eligible providers using a 5-signal weighted algorithm.
3. Calls an AI model to generate a one-sentence "why this provider is a good fit" reason for each top candidate.
4. Returns the saved request **plus** an inline `recommendations` array of up to 3 providers with scores, signal breakdowns, and AI reasons.

The customer browses the recommendation cards and taps one. The app then calls a second endpoint to atomically create the booking against that provider.

**Key difference from direct booking:** the provider does **not** need to be in the customer's favorites list.

---

## 2. The two-step flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 1                                                              │
│  POST /api/v1/bookings/requests/                                    │
│  body: { ..., booking_mode: "recommended" }                         │
│                                                                     │
│  Response 201 → ServiceRequest + recommendations: [...]             │
│                                                                     │
│  Customer sees up to 3 provider cards ranked by AI score.           │
│  Customer taps "Book" on one card.                                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │  (store service_request.id from step 1 response)
                             │  (is NOT used in step 2 body — new SR is created)
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│ STEP 2                                                              │
│  POST /api/v1/bookings/requests/recommended/                        │
│  body: { provider_id: "<chosen_provider_uuid>", ...same fields... } │
│                                                                     │
│  Response 201 → ServiceRequest (status: "assigned",                 │
│                                 booking_mode: "recommended")        │
│                                                                     │
│  Provider receives a push notification.                             │
│  Standard flow continues: quote → confirm → start → complete.       │
└─────────────────────────────────────────────────────────────────────┘
```

> **Why two separate requests?**
> Step 1 creates a pending SR that acts as a "browsing session". The customer may abandon it and the SR stays pending (invisible in the open pool). Step 2 creates the actual booked SR. Both SRs persist independently.

---

## 3. Step 1 — Create the service request (recommended mode)

### Request

`POST /api/v1/bookings/requests/`

Content-Type: `multipart/form-data`
Authorization: `Token <customer-token>`

| Field              | Type    | Required | Notes                                                 |
| ------------------ | ------- | -------- | ----------------------------------------------------- |
| `category`         | integer | ✓        | Category ID                                           |
| `region`           | integer | ✓        | Region ID                                             |
| `address`          | string  | ✓        | Street address                                        |
| `floor_number`     | string  | ✓        | e.g. `"3"`, `"Ground"`                                |
| `apartment_number` | string  | ✓        | e.g. `"12"`                                           |
| `special_mark`     | string  | ✓        | Landmark hint for the provider                        |
| `latitude`         | float   | ✓        | Service location lat                                  |
| `longitude`        | float   | ✓        | Service location lng                                  |
| `title`            | string  | ✓        | Short job title                                       |
| `description`      | string  | ✓        | Detailed description                                  |
| `preferred_date`   | date    | ✓        | `YYYY-MM-DD`                                          |
| `preferred_time`   | time    | ✓        | `HH:MM:SS`                                            |
| `photos`           | file(s) | ✓        | 1–5 images, jpg/png                                   |
| `booking_mode`     | string  | ✓        | **Must be `"recommended"`**                           |
| `is_urgent`        | boolean |          | Default: `false`                                      |
| `estimated_price`  | decimal |          | Optional customer hint                                |
| `payment_method`   | string  |          | `"cash"` \| `"card"` \| `"wallet"`. Default: `"cash"` |
| `wallet_amount`    | decimal |          | Default: `"0.00"`                                     |

### Response 201

```json
{
  "id": "3f2a1b00-...",
  "status": "pending",
  "booking_mode": "recommended",
  "category": { "id": 1, "name": "Plumbing" },
  "region":   { "id": 1, "name": "Cairo" },
  "photos":   [{ "id": "uuid", "image": "https://...", "uploaded_at": "..." }],
  "address": "12 Tahrir St",
  "floor_number": "3",
  "apartment_number": "12",
  "special_mark": "Blue door",
  "latitude": 30.044420,
  "longitude": 31.235712,
  "title": "Leaking pipe under sink",
  "description": "...",
  "is_urgent": false,
  "preferred_date": "2025-08-01",
  "preferred_time": "10:00:00",
  "estimated_price": null,
  "quoted_price": null,
  "final_price": null,
  "payment_method": "cash",
  "payment_method_display": "Cash",
  "wallet_amount": "0.00",
  "card_amount": null,
  "payment_status": "pending",
  "payment_status_display": "Pending",
  "created_at": "2026-05-02T10:00:00Z",
  "assigned_at": null,
  "confirmed_at": null,
  "started_at": null,
  "completed_at": null,
  "cancelled_at": null,
  "declined_at": null,
  "review": null,

  "recommendations": [
    {
      "id":                  "a1b2c3d4-...",
      "full_name":           "Ahmed Hassan",
      "business_name":       "Ahmed's Plumbing",
      "average_rating":      "4.60",
      "total_reviews":       38,
      "completed_jobs":      35,
      "hourly_rate":         "150.00",
      "years_of_experience": 5,
      "acceptance_rate":     0.9600,
      "distance_km":         1.2,
      "is_favorite":         false,
      "score":               87.45,
      "signals": {
        "rating":               92.0,
        "distance":             88.0,
        "completion_rate":      94.29,
        "is_favorite":          false,
        "urgency_availability": 50.0
      },
      "reason": "Highly rated and only 1.2 km away with a stellar completion record."
    },
    { ... },
    { ... }
  ]
}
```

`recommendations` is an **empty array** `[]` when no eligible providers are found.

---

## 4. The recommendations array — field reference

Each item in `recommendations` represents one scored provider candidate.

| Field                 | Type    | Description                                                                                                           |
| --------------------- | ------- | --------------------------------------------------------------------------------------------------------------------- |
| `id`                  | uuid    | Provider UUID — pass this as `provider_id` in Step 2.                                                                 |
| `full_name`           | string  | Provider's full name (first + last).                                                                                  |
| `business_name`       | string  | Trade name; may be empty string — fall back to `full_name` when empty.                                                |
| `average_rating`      | string  | Decimal string e.g. `"4.60"`. Display as stars (out of 5).                                                            |
| `total_reviews`       | integer | Number of customer ratings received.                                                                                  |
| `completed_jobs`      | integer | Jobs fully completed. Use for trust signal display.                                                                   |
| `hourly_rate`         | string  | e.g. `"150.00"` in local currency. `null` if the provider has not set a rate.                                         |
| `years_of_experience` | integer | Self-declared. `0` means not set.                                                                                     |
| `acceptance_rate`     | float   | Fraction 0–1, e.g. `0.96` = 96%. `null` for brand-new providers with 0 lifetime jobs.                                 |
| `distance_km`         | float   | Straight-line distance from the service address to the provider's registered location.                                |
| `is_favorite`         | boolean | `true` if this provider is already in the customer's favorites list.                                                  |
| `score`               | float   | Final weighted score 0–100. The array is pre-sorted highest score first.                                              |
| `signals`             | object  | Per-signal breakdown (see [Scoring signal reference](#10-scoring-signal-reference)).                                  |
| `reason`              | string  | AI-generated one-sentence explanation. Always non-empty — falls back to a signal-driven summary if AI is unavailable. |

### Rendering guidance

- **Card order** — always render in the order returned; the server sorts by `score` descending.
- **Name** — show `business_name` if non-empty, else `full_name`.
- **Rating** — render `average_rating` as a star display alongside `total_reviews` count.
- **Distance** — format as `"1.2 km away"`.
- **Acceptance rate** — display as `"96% acceptance"`. Hide if `null` (new provider).
- **Reason** — the `reason` field is ready to display verbatim as a subtitle on the card.
- **Favourite badge** — show a heart/star badge when `is_favorite: true`.
- **Score** — do **not** show the raw score number to customers. Use it only for ordering, which the server already handles.

---

## 5. Step 2 — Book the chosen provider

When the customer taps a recommendation card, call:

`POST /api/v1/bookings/requests/recommended/`

Content-Type: `multipart/form-data`
Authorization: `Token <customer-token>`

**Send all the same fields as Step 1, plus `provider_id`. Do not send `booking_mode` — it is set automatically to `"recommended"` on this endpoint.**

| Field              | Type    | Required | Notes                                         |
| ------------------ | ------- | -------- | --------------------------------------------- |
| `provider_id`      | uuid    | ✓        | The `id` from the chosen recommendation card. |
| `category`         | integer | ✓        | Same value as Step 1.                         |
| `region`           | integer | ✓        | Same value as Step 1.                         |
| `address`          | string  | ✓        | Same value as Step 1.                         |
| `floor_number`     | string  | ✓        | Same value as Step 1.                         |
| `apartment_number` | string  | ✓        | Same value as Step 1.                         |
| `special_mark`     | string  | ✓        | Same value as Step 1.                         |
| `latitude`         | float   | ✓        | Same value as Step 1.                         |
| `longitude`        | float   | ✓        | Same value as Step 1.                         |
| `title`            | string  | ✓        | Same value as Step 1.                         |
| `description`      | string  | ✓        | Same value as Step 1.                         |
| `preferred_date`   | date    | ✓        | Same value as Step 1.                         |
| `preferred_time`   | time    | ✓        | Same value as Step 1.                         |
| `photos`           | file(s) | ✓        | Re-upload the same photos (or new ones).      |
| `is_urgent`        | boolean |          | Same value as Step 1.                         |
| `estimated_price`  | decimal |          | Same value as Step 1.                         |
| `payment_method`   | string  |          | Same value as Step 1.                         |
| `wallet_amount`    | decimal |          | Same value as Step 1.                         |

> **Tip:** Store the form data from Step 1 in memory so you can replay it in Step 2 without asking the customer to fill the form twice.

### Response 201

```json
{
  "id": "9e8f7a00-...",
  "status": "assigned",
  "booking_mode": "recommended",
  "provider": {
    "id": "a1b2c3d4-...",
    "first_name": "Ahmed",
    "last_name": "Hassan",
    "business_name": "Ahmed's Plumbing",
    "rating": 4.6,
    "total_reviews": 38,
    ...
  },
  "assigned_at": "2026-05-02T10:05:00Z",
  ...
}
```

Status is immediately `"assigned"` — the booking is live.

### Provider guards checked at this step

All must pass or the API returns 400:

| Guard                  | Meaning                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------ |
| Verification           | Provider must have `verification_status: "verified"`.                                |
| Availability           | Provider must have `is_available: true`.                                             |
| Category match         | Provider must offer the requested `category`.                                        |
| Active-job check       | Provider must have no job in `assigned / quoted / confirmed / in_progress`.          |
| **No favorites check** | Unlike direct booking, the provider does NOT need to be in the customer's favorites. |

The race-condition guard (DB row lock) is also applied — if two customers somehow book the same provider concurrently, the second request returns 400.

---

## 6. After booking — lifecycle & notifications

Once Step 2 succeeds the booking follows the standard service-request lifecycle:

```
assigned → quoted → confirmed → in_progress → completed
        ↘ (provider accepts directly, skips quote)
         → confirmed → in_progress → completed
```

### Notifications fired at Step 2

| Who receives | Type                     | Message                                                   |
| ------------ | ------------------------ | --------------------------------------------------------- |
| Provider     | `direct_booking_request` | `"<CustomerName> personally requested you for «<title>»"` |

The provider app should deep-link `direct_booking_request` to the incoming requests screen.

### If the provider declines

The provider can decline from `assigned` status via their app. When this happens:

- The service request reverts to `status: "pending"`, `booking_mode: "broadcast"`.
- It enters the open pool and any matching provider can self-assign.
- The customer receives a `request_declined` push notification.
- **You do not need to handle this as a special case** — the customer's booking history will show the request has returned to pending, and they will see it in their active requests list with status `"pending"`.

---

## 7. Provider side — match score in the open pool

`GET /api/v1/bookings/requests/open/` returns the same scoring engine signals so providers can see how well they match each open request.

Each result in the open-pool list includes two extra fields:

```json
{
  "id": "...",
  "status": "pending",
  "title": "Leaking pipe",
  ...
  "match_score": 74.50,
  "match_signals": {
    "rating":               80.0,
    "distance":             70.0,
    "completion_rate":      90.0,
    "is_favorite":          false,
    "urgency_availability": 50.0
  }
}
```

| Field           | Type   | Description                                                                                                          |
| --------------- | ------ | -------------------------------------------------------------------------------------------------------------------- |
| `match_score`   | float  | Weighted score 0–100 for how well this provider fits this request. `null` if the provider has no saved location.     |
| `match_signals` | object | Per-signal scores (see [Scoring signal reference](#10-scoring-signal-reference)). `null` when `match_score` is null. |

**Note:** `booking_mode: "recommended"` requests are **excluded** from the open pool entirely. Providers only see broadcast requests here.

---

## 8. Edge cases you must handle

### 8.1 Empty recommendations

`recommendations: []` is a valid response. This happens when:

- No verified/available providers serve the customer's location.
- All providers are currently on active jobs.
- The customer's location is outside every provider's service radius.

**What to show:** An empty-state screen telling the customer no providers are currently available. Offer them the option to create a regular broadcast request instead (same form, `booking_mode: "broadcast"`).

### 8.2 Provider becomes unavailable between Step 1 and Step 2

The provider availability is checked **at Step 2**, not Step 1. If a provider in the recommendations list becomes unavailable (took another job, toggled off, etc.) between the two steps, Step 2 returns:

```json
HTTP 400
{
  "provider_id": ["This provider is not available."]
}
```

**What to show:** An error telling the customer the provider is no longer available, and prompt them to choose another from the recommendations list, or return to the recommendations screen.

### 8.3 AI reasons are unavailable

`reason` is **always non-empty**. If the AI pipeline fails (all 4 providers exhausted, no API keys, Constance flag off), the server falls back to a rule-based signal summary:

```
"Highly rated at 4.6★, very close (1.2 km away), 90% completion rate."
```

The field is safe to display verbatim in either case.

### 8.4 Fewer than 3 recommendations

The array may contain 1, 2, or 3 items. Design the UI to handle any count gracefully — do not assume exactly 3.

### 8.5 Customer abandons after Step 1

The Step 1 service request (status: `pending`, `booking_mode: "recommended"`) sits in the database but is invisible to all providers in the open pool. It is not auto-cancelled. The customer will see it in their active requests list. This is expected — encourage the customer to either complete Step 2 or cancel the request manually.

---

## 9. Error reference for this flow

### Step 1 errors

| HTTP | Field          | Cause                                        |
| ---- | -------------- | -------------------------------------------- |
| 400  | `photos`       | No photos attached, or more than 5.          |
| 400  | `booking_mode` | Value not in `["broadcast", "recommended"]`. |
| 400  | various        | Missing required fields.                     |
| 403  | —              | Provider token used (customer only).         |

### Step 2 errors

| HTTP | Field         | Cause                                                                                       |
| ---- | ------------- | ------------------------------------------------------------------------------------------- |
| 400  | `provider_id` | Provider not found, unverified, unavailable, wrong category, or currently on an active job. |
| 400  | `photos`      | No photos attached, or more than 5.                                                         |
| 400  | various       | Missing required fields.                                                                    |
| 403  | —             | Provider token used (customer only).                                                        |

All 400 errors return a JSON body with field-level messages:

```json
{
  "provider_id": ["This provider is not available."]
}
```

---

## 10. Scoring signal reference

The five signals that make up each provider's score. Same algorithm used in both recommendation cards (Step 1) and the provider open-pool view.

| Signal                 | Weight | Range    | How it is calculated                                                                                   |
| ---------------------- | ------ | -------- | ------------------------------------------------------------------------------------------------------ |
| `rating`               | 30%    | 0–100    | `(average_rating / 5.0) × 100`. A 5★ provider scores 100.                                              |
| `distance`             | 25%    | 0–100    | `max(0, (1 − distance_km / service_radius)) × 100`. Zero at the radius boundary, 100 at zero distance. |
| `completion_rate`      | 20%    | 0–100    | Percentage of assigned jobs completed. New providers (0 jobs) receive a neutral 50.                    |
| `is_favorite`          | 15%    | 0 or 100 | 100 if the provider is in the customer's favorites, 0 otherwise.                                       |
| `urgency_availability` | 10%    | 0–100    | 100 if urgent + available. 50 if available (non-urgent). 0 if unavailable.                             |

**Final score** = sum of (signal × weight). Maximum possible: 100.

The `is_favorite` field inside `signals` is a boolean, not a 0/100 number (it reflects the raw flag). All other signal values are floats 0–100.
