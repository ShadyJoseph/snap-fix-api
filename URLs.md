━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SNAPFIX API — REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All endpoints require: Authorization: Token <knox-token>
Exceptions: register and login endpoints (marked [public])

Base URL: /api/v1/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATE FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Normal (with price negotiation):
pending → assigned → quoted → confirmed → in_progress → completed

Skip-quote path (provider accepts without negotiating):
pending → assigned → confirmed → in_progress → completed

Rejection / decline paths:
quoted → pending (customer rejects quote — back to open pool)
assigned → pending (provider declines — back to open pool)

CANCELLED is reachable from: pending, assigned, quoted, confirmed, in_progress.
COMPLETED and CANCELLED are terminal states.

Status Who triggers
───────────────────────────────────────────────────────
pending Customer creates request
assigned Admin assigns a provider OR
Provider self-picks from the open pool
quoted Provider submits a price quote
confirmed Customer approves the quote OR
Provider accepts directly (skip-quote path)
in_progress Provider starts work on-site
completed Provider finishes the job [TERMINAL]
cancelled Customer, provider, or admin cancels [TERMINAL]

Guards enforced on every transition:
Photo guard — create requires ≥1 photo (max 5).
Active-job guard — a provider cannot self-assign if they already
have a job in assigned / quoted / confirmed /
in_progress.
Category guard — open pool and /pick/ only surface requests
whose category matches one of the provider's
registered categories.
Race guard — /pick/ uses a DB row lock; the second concurrent
attempt gets 404.
Price lock — final_price is set at approve-quote and cannot
be changed at /complete/. No body param accepted.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PAYMENT FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

payment_method and wallet_amount are set by the customer at booking time
and can be adjusted when approving a quote.

Three payment_method values:
"cash" — provider collects in person (default)
"card" — Stripe charges the card for the non-wallet portion
"wallet" — entire amount from wallet (wallet_amount == final_price)

wallet_amount — how much comes from the wallet (0 means no wallet use).
card_amount — computed: final_price − wallet_amount (read-only in API).

CASH
At /complete/: payment_status → "paid" immediately (honor system).
Provider collects cash. Platform does not handle the cash portion so
available_balance is NOT credited for the cash portion.
total_earnings is credited for tracking.

CARD
Customer calls /initiate-card-payment/ after approving the quote to
attach a Stripe PaymentMethod ID. A PaymentIntent is created with
capture_method="manual" — card is authorized but NOT yet charged.
At /complete/: the PaymentIntent is captured automatically.
payment_status → "paid". Provider available_balance credited.

WALLET (full or partial)
wallet_amount is deducted from the customer's wallet at /complete/
under a DB row lock. If payment_method == "wallet", wallet_amount
covers the entire final_price.
payment_status → "paid". Provider available_balance credited.

Pricing fields on the service request object:
estimated_price — optional hint provided by the customer at creation
quoted_price — set by the provider via /quote/; cleared on reject
final_price — locked from quoted_price when customer calls
/approve-quote/. The canonical charge amount for all
payment calculations. Cannot be changed after this point.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHARED OBJECTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

<CustomerCard> — embedded in provider history detail
{
"id": "uuid",
"email": "customer@example.com",
"first_name": "Shady",
"last_name": "Abadeer",
"phone": "01284688383",
"wallet_balance": "0.00",
"total_bookings": 5,
"is_verified": true,
"date_joined": "2025-01-01T00:00:00Z"
}

<ProviderCard> — embedded in customer history detail and favorites
{
"id": "uuid",
"email": "provider@example.com",
"first_name": "Mohamed",
"last_name": "Ali",
"phone": "01284688383",
"business_name": "Ali Fixes",
"bio": "...",
"verification_status": "verified",
"is_available": true,
"rating": 4.75,
"total_reviews": 20,
"total_jobs": 25,
"completed_jobs": 23,
"completion_rate": 92.0,
"available_balance": "1840.00",
"total_earnings": "2400.00",
"hourly_rate": "80.00",
"years_of_experience": 5,
"latitude": 30.044420,
"longitude": 31.235712,
"date_joined": "2025-01-01T00:00:00Z"
}

<Review> — embedded in booking responses
{
"id": "uuid",
"rating": 5,
"comment": "Great work!",
"created_at": "2025-08-02T10:00:00Z"
}

<Photo> — item in the photos array
{
"id": "uuid",
"image": "https://res.cloudinary.com/.../photo.jpg",
"uploaded_at": "2025-08-01T08:00:00Z"
}

<Notification> — item returned by GET /api/v1/notifications/
{
"id": "uuid",
"type": "quote_received",
"title": "New Quote",
"body": "You received a quote of 500.00 for «Fix AC». Tap to review.",
"data": { "service_request_id": "uuid" },
"is_read": false,
"created_at": "2026-04-11T10:00:00Z"
}

type values and their meaning:
request_assigned — provider picked the request
quote_received — provider submitted a price
request_accepted — provider accepted directly (no quote)
job_started — provider began work on-site
job_completed — provider marked the job done
request_declined — provider turned down the assignment
cancelled_by_provider — provider cancelled the job
quote_approved — customer approved the quoted price
quote_rejected — customer rejected the quoted price
cancelled_by_customer — customer cancelled the request
payment_settled — job completed, provider earnings credited
onboarding_approved — provider onboarding application approved
onboarding_rejected — provider application rejected (includes reason + resubmit date)
onboarding_changes_required — changes requested before approval
onboarding_resubmit_available — 30-day rejection cooldown has expired

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CUSTOMERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

POST /api/v1/customers/register/ [public]

    Request:
    {
        "email":      "customer@example.com",
        "first_name": "Shady",
        "last_name":  "Abadeer",
        "phone":      "01284688383",
        "password":   "shady123!"
    }

    Response 201:
    {
        "customer": {
            "id":             "uuid",
            "email":          "customer@example.com",
            "first_name":     "Shady",
            "last_name":      "Abadeer",
            "phone":          "01284688383",
            "wallet_balance": "0.00",
            "total_bookings": 0,
            "is_verified":    false,
            "date_joined":    "2025-01-01T00:00:00Z"
        },
        "token": "<knox-token>"
    }

    Response 400: email already registered or validation failure

────────────────────────────────────────────────────────

POST /api/v1/customers/login/ [public]

    Request:
    { "email": "customer@example.com", "password": "shady123!" }

    Response 200:
    {
        "customer": {
            "id":             "uuid",
            "email":          "customer@example.com",
            "first_name":     "Shady",
            "last_name":      "Abadeer",
            "phone":          "01284688383",
            "wallet_balance": "0.00",
            "total_bookings": 5,
            "is_verified":    true,
            "date_joined":    "2025-01-01T00:00:00Z"
        },
        "token": "<knox-token>"
    }

    Response 400: invalid credentials or account disabled

────────────────────────────────────────────────────────

POST /api/v1/customers/logout/

    Response 204 No Content

────────────────────────────────────────────────────────

GET /api/v1/customers/me/

    Response 200:
    {
        "id":              "uuid",
        "email":           "customer@example.com",
        "first_name":      "Shady",
        "last_name":       "Abadeer",
        "phone":           "01284688383",
        "profile_picture": null,
        "address":         "12 Tahrir St",
        "latitude":        30.044420,
        "longitude":       31.235712,
        "wallet_balance":  "0.00",
        "total_cashback":  "0.00",
        "total_bookings":  5,
        "is_verified":     true,
        "date_joined":     "2025-01-01T00:00:00Z"
    }

    latitude / longitude — null when the customer has not shared their location.

────────────────────────────────────────────────────────

PATCH /api/v1/customers/me/

    All fields optional. Locked fields (ignored if sent): email, password,
    wallet_balance, total_cashback, total_bookings, is_verified.

    Request (all optional):
    {
        "first_name":      "Shady",
        "last_name":       "Joseph",
        "phone":           "01284688383",
        "profile_picture": <file>,
        "address":         "15 Tahrir St",
        "latitude":        30.044420,
        "longitude":       31.235712
    }

    latitude and longitude must be provided together or not at all.

    Response 200: updated profile (same shape as GET /me/)
    Response 400: only one of latitude/longitude provided

────────────────────────────────────────────────────────

GET /api/v1/customers/favorites/

    Returns the customer's saved providers.

    Response 200 (paginated):
    {
        "count": 2,
        "results": [ <ProviderCard>, ... ]
    }

────────────────────────────────────────────────────────

POST /api/v1/customers/favorites/<provider_id>/toggle/

    Adds or removes the provider from favorites (idempotent toggle).

    Request: (no body)

    Response 200:
    {
        "is_favorite": true,
        "provider_id": "uuid"
    }

    Response 404: provider not found

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROVIDERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ONBOARDING FLOW
───────────────

Self-service from the mobile app — no office visit required.

1. Register → POST /register/ (issues onboarding_token).
2. Fill in personal & professional details → PATCH /onboarding/personal/
3. Upload documents → PATCH /onboarding/documents/
4. Submit for review → POST /onboarding/submit/
   - Status moves to "pending".
   - AI validates documents automatically (multi-provider pipeline: OpenAI GPT-4o-mini, Google Gemini, Groq Llama, Anthropic Claude; configured via Constance → AI_VALIDATION_PROVIDER).
5. Poll for updates → GET /onboarding/status/
6. Staff make the final decision via the Admin Dashboard:
   - approved → verification_status → "verified" + FCM push
   - rejected → 30-day cooldown before resubmit + FCM push
   - changes_required → provider updates and resubmits + FCM push
7. After approval, provider logs in → POST /login/.

Onboarding FSM:
draft → pending → under_review → approved
→ rejected (cooldown → resubmit → draft)
→ changes_required → pending (repeat)

Auth note: the onboarding_token returned at registration grants access to all
/onboarding/\* endpoints. It is scoped to providers with verification_status="pending".
Full app access (bookings, jobs) requires logging in after approval.

────────────────────────────────────────────────────────

<OnboardingApplication> — returned by all onboarding endpoints

{
"id": "uuid",
"status": "draft", // draft | pending | under_review | approved | rejected | changes_required
"ai_validation_status": "pending", // pending | running | passed | flagged | failed
"ai_report_summary": null, // see below when available
"rejection_reason": "",
"change_requests": "",
"can_resubmit": false,
"can_resubmit_after": null, // ISO datetime, set on rejection
"submitted_at": "2026-04-23T10:00:00Z",
"updated_at": "2026-04-23T10:00:00Z"
}

ai_report_summary (non-null once AI completes):
{
"status": "passed", // passed | flagged | failed
"issues": [], // list of problem strings
"overall_confidence": 0.92 // float 0-1
}

────────────────────────────────────────────────────────

POST /api/v1/providers/register/ [public]

    Request:
    {
        "first_name": "Shady",
        "last_name":  "Abadeer",
        "email":      "provider@example.com",
        "phone":      "01284688383",
        "password":   "shady123!"
    }

    Response 201:
    {
        "message":         "Registration successful. Use the onboarding_token to complete your profile...",
        "onboarding_token": "<knox-token>",
        "next_step":       "Submit your personal info at /api/v1/providers/onboarding/personal/"
    }

    Response 400: email already registered or validation failure

────────────────────────────────────────────────────────

POST /api/v1/providers/login/ [public]

    Only succeeds when credentials are valid, account is active,
    and verification_status is "verified".

    Request: { "email": "provider@example.com", "password": "shady123!" }

    Response 200: { "provider": <ProviderCard>, "token": "<knox-token>" }
    Response 400: invalid credentials or account not yet verified

────────────────────────────────────────────────────────

POST /api/v1/providers/logout/

    Response 204 No Content

────────────────────────────────────────────────────────

GET /api/v1/providers/me/

    Response 200:
    {
        "id":                  "uuid",
        "email":               "provider@example.com",
        "first_name":          "Shady",
        "last_name":           "Abadeer",
        "phone":               "01284688383",
        "profile_picture":     null,
        "address":             "15 Tahrir St",
        "latitude":            30.044420,
        "longitude":           31.235712,
        "business_name":       "Shady Fixes",
        "bio":                 "10 years experience...",
        "hourly_rate":         "80.00",
        "years_of_experience": 5,
        "region":              1,
        "categories":          [1, 2],
        "verification_status": "verified",
        "is_available":        true,
        "rating":              4.75,
        "total_reviews":       20,
        "total_jobs":          25,
        "completed_jobs":      23,
        "completion_rate":     92.0,
        "available_balance":   "1840.00",
        "total_earnings":      "2400.00",
        "date_joined":         "2025-01-01T00:00:00Z"
    }

    latitude / longitude — null when the provider has no saved location.

────────────────────────────────────────────────────────

PATCH /api/v1/providers/me/

    All fields optional. Locked fields (ignored if sent): email, password,
    region, categories, verification_status, rating, total_reviews,
    total_jobs, completed_jobs, available_balance, total_earnings.

    Request (all optional):
    {
        "first_name":          "Shady",
        "last_name":           "Joseph",
        "phone":               "01284688383",
        "profile_picture":     <file>,
        "address":             "15 Tahrir St",
        "latitude":            30.044420,
        "longitude":           31.235712,
        "business_name":       "Shady Fixes Pro",
        "bio":                 "10 years experience...",
        "hourly_rate":         "100.00",
        "years_of_experience": 10,
        "is_available":        true
    }

    Response 200: updated profile (same shape as GET /me/)
    Response 400: only one of latitude/longitude provided

────────────────────────────────────────────────────────

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROVIDER SELF-SERVICE ONBOARDING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All endpoints require: Authorization: Token <onboarding_token>
Permission: verification_status must be "pending" (IsAwaitingOnboarding).
Exception: GET /onboarding/status/ accepts any authenticated provider token.

────────────────────────────────────────────────────────

GET /api/v1/providers/onboarding/status/

    Returns the current onboarding application state.
    Accessible with any provider token (pending or verified).

    Response 200: <OnboardingApplication>
    Response 404: no application exists yet — call PATCH /personal/ first

────────────────────────────────────────────────────────

PATCH /api/v1/providers/onboarding/personal/ [onboarding_token]

    Creates a DRAFT application if none exists, or updates an existing
    DRAFT / CHANGES_REQUIRED application.

    Identity fields (first_name, last_name, email, phone) are locked to the
    registered provider — they cannot be overridden in the request body.

    If the previous application was REJECTED and the 30-day cooldown has
    expired, calling this endpoint automatically resets it to DRAFT.

    Request (all optional on update; date_of_birth required to submit):
    {
        "date_of_birth":      "1998-05-20",    // YYYY-MM-DD, must be 18+
        "address":            "123 Cairo St",
        "region":             1,
        "category":           3,
        "hourly_rate":        "150.00",
        "years_of_experience": 5,
        "bio":                "..."
    }

    Response 200: <OnboardingApplication>
    Response 400: application is not in DRAFT or CHANGES_REQUIRED status,
                  or applicant is under 18
    Response 403: application rejected and 30-day cooldown not yet expired
                  (body includes can_resubmit_after)

────────────────────────────────────────────────────────

PATCH /api/v1/providers/onboarding/documents/ [onboarding_token]

    Upload or replace documents on an existing DRAFT / CHANGES_REQUIRED
    application. Must call /personal/ first to create the application.
    Send as multipart/form-data.

    Files accepted: jpg, jpeg, png, pdf (max 5 MB each).

    Request (all optional; nid_front, nid_back, police_clearance_certificate
    are required before submitting):
    {
        "nid_front":                    <file>,    // required for submit
        "nid_back":                     <file>,    // required for submit
        "police_clearance_certificate": <file>,    // required for submit
        "professional_certificate":     <file>,    // optional
        "profile_photo":                <file>     // optional, jpg/jpeg/png only
    }

    Response 200: <OnboardingApplication>
    Response 404: no application found — call /personal/ first
    Response 400: application is not in DRAFT or CHANGES_REQUIRED status,
                  or file too large / wrong extension

────────────────────────────────────────────────────────

POST /api/v1/providers/onboarding/submit/ [onboarding_token]

    Finalise a DRAFT or CHANGES_REQUIRED application and submit for review.
    Validates that all required fields are present before transitioning.

    Required fields: date_of_birth, address, region, category, hourly_rate,
                     nid_front, nid_back, police_clearance_certificate.

    On success:
      - status → "pending"
      - Claude Vision AI validation is enqueued (async, non-blocking)
      - Staff are notified in the Admin Dashboard

    Response 200:
    {
        "detail":      "Application submitted successfully...",
        "application": <OnboardingApplication>
    }
    Response 400: missing required fields (body lists missing_fields),
                  or application is not in DRAFT / CHANGES_REQUIRED
    Response 404: no application found

Notification types sent to the provider (FCM push):
onboarding_approved — "Your application has been approved!"
onboarding_rejected — includes rejection reason + resubmit date
onboarding_changes_required — includes list of changes to make
onboarding_resubmit_available — daily reminder when 30-day window opens

────────────────────────────────────────────────────────

PATCH /api/v1/providers/me/location/ [provider token]

    Lightweight GPS ping. Call ~every 60 seconds while on an active job.
    Both fields required.

    Request:
    {
        "latitude":  30.044420,   (required, -90 to 90)
        "longitude": 31.235712    (required, -180 to 180)
    }

    Response 200: { "latitude": 30.044420, "longitude": 31.235712 }
    Response 400: missing or out-of-range coordinates
    Response 403: not a provider account

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/core/categories/

    Response 200: [ { "id": 1, "name": "Plumbing", "icon": "wrench" }, ... ]

────────────────────────────────────────────────────────

GET /api/v1/core/regions/

    Response 200: [ { "id": 1, "name": "Cairo" }, ... ]

────────────────────────────────────────────────────────

GET /api/v1/core/offices/

    Response 200:
    [
        {
            "id":            "uuid",
            "name":          "Cairo Main Office",
            "address":       "5 Tahrir Square, Cairo",
            "landmark":      "Next to the Egyptian Museum",
            "latitude":      "30.044420",
            "longitude":     "31.235712",
            "region_name":   "Cairo",
            "working_hours": "Sun-Thu 9:00 AM - 5:00 PM"
        }
    ]

────────────────────────────────────────────────────────

GET /api/v1/core/offices/<id>/

    Response 200: full office detail including nested region object
    Response 404: office not found or inactive

────────────────────────────────────────────────────────

GET /api/v1/core/offices/nearest/?lat=<lat>&lng=<lng>

    Returns the single closest active office to the given coordinates.

    Response 200: office detail + "distance_km": 2.45
    Response 400: lat/lng missing or not valid numbers
    Response 404: no active offices found

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOTE — Office management is via the Admin Dashboard only.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — SERVICE REQUEST OBJECT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Returned by all booking action endpoints and by list / detail.

{
"id": "3f2a1b...",
"status": "pending",
"status_display": "Pending",
"category": { "id": 1, "name": "Plumbing" },
"region": { "id": 1, "name": "Cairo" },
"photos": [ <Photo>, ... ],
"address": "12 Tahrir St, Apt 3",
"floor_number": "3",
"apartment_number": "12",
"special_mark": "Blue door on the left",
"latitude": 30.044420,
"longitude": 31.235712,
"distance_km": null,
"provider_distance_km": null,
"provider_eta_minutes": null,
"title": "Leaking pipe under sink",
"description": "Kitchen pipe dripping for 2 days.",
"is_urgent": false,
"preferred_date": "2025-08-01",
"preferred_time": "10:00:00",
"estimated_price": "150.00",
"quoted_price": null,
"final_price": null,
"payment_method": "cash",
"payment_method_display": "Cash",
"wallet_amount": "0.00",
"card_amount": null,
"payment_status": "pending",
"payment_status_display": "Pending",
"cancelled_by": "",
"cancelled_by_display": "",
"cancellation_reason": "",
"decline_reason": "",
"created_at": "2025-07-20T08:00:00Z",
"assigned_at": null,
"confirmed_at": null,
"started_at": null,
"completed_at": null,
"cancelled_at": null,
"declined_at": null,
"review": null
}

Field notes:

photos
Array of <Photo> objects. Populated immediately after creation.
Visible to both customer and provider on all endpoints.

estimated_price
Optional hint set by the customer. Not used in any calculation.

quoted_price
Set by the provider via /quote/. Cleared if the customer rejects.

final_price
Locked from quoted_price when the customer calls /approve-quote/.
The canonical charge amount for all payment calculations.
Cannot be changed after this point.

payment_method / payment_method_display
"cash", "card", or "wallet". Set at booking time; can be updated
when approving a quote via the approve-quote request body.

wallet_amount
How much of final_price the customer pays from their wallet (0 = none).

card_amount
Computed: final_price − wallet_amount. The portion charged to the card
(payment_method == "card") or collected as cash ("cash"). Read-only.

payment_status / payment_status_display
"pending" until settlement. "paid" once payment is collected.
Cash jobs: "paid" at /complete/ (honor system).
Card jobs: "paid" at /complete/ once Stripe capture succeeds.
Wallet jobs: "paid" at /complete/ if balance is sufficient.

distance_km
Straight-line distance (km) from the provider's current location
to the job. Populated only in GET /requests/open/ when the provider
has a saved location. Null in all other responses.

provider_distance_km / provider_eta_minutes
Distance and estimated travel time (at 30 km/h) from the assigned
provider's last known GPS ping to the job location.
Both null when no provider is assigned or provider has no location.

decline_reason / declined_at
Audit fields. Non-null means this request was declined at least once
and returned to pending. Not a status indicator — the request may
now be completed.

cancelled_by / cancelled_by_display
Empty string when not cancelled. Values: "customer", "provider", "admin".

review
Null until the customer rates the job. Once rated: <Review> object.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — CUSTOMER ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/requests/ [customer token]
?status=<status> (optional filter)

    Returns the customer's own service requests, newest first.

    Response 200 (paginated): { "count": N, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/ [customer token]

    Creates a new service request. Status starts as "pending".
    Must be multipart/form-data (photos are required).
    Customer is taken from the auth token — never from the body.

    Request (* = required):
    {
        "category":         1,                               *
        "region":           1,                               *
        "address":          "12 Tahrir St",                  *
        "floor_number":     "3",                             *
        "apartment_number": "12",                            *
        "special_mark":     "Blue door on the left",         *
        "latitude":         30.044420,                       *
        "longitude":        31.235712,                       *
        "title":            "Leaking pipe",                  *
        "description":      "Details...",                    *
        "preferred_date":   "2025-08-01",                    *  (YYYY-MM-DD)
        "preferred_time":   "10:00:00",                      *  (HH:MM:SS)
        "photos":           <file>, <file>, ...              *  (1-5 images, jpg/png)
        "is_urgent":        false,
        "estimated_price":  "150.00",
        "payment_method":   "cash",                             ("cash" | "card" | "wallet", default: "cash")
        "wallet_amount":    "0.00"                              (optional, default: 0)
    }

    Response 201: <ServiceRequest>  (includes photos array)
    Response 400: missing required fields, invalid coordinates,
                  or no photos / more than 5 photos attached
    Response 403: provider token used

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/<id>/ [customer token]

    Response 200: <ServiceRequest>
    Response 404: not found or not owned by caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/cancel/ [customer token]

    Cancels the request. Allowed from: pending, assigned, quoted,
    confirmed, in_progress.

    Request: { "reason": "Changed my mind" }  (optional)

    Response 200: <ServiceRequest>  (status: "cancelled", cancelled_by: "customer")
    Response 400: already completed or cancelled
    Response 404: not found or not owned by caller

    Notification fired (only when a provider is assigned):
      cancelled_by_customer → provider

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/approve-quote/ [customer token]

    Customer accepts the provider's quoted price.
    Transition: quoted → confirmed.
    Locks final_price = quoted_price. Customer may update their payment split here.

    Request (all optional — omit to keep values set at booking time):
    {
        "wallet_amount":  "50.00",   (how much to pay from wallet; 0 = none)
        "payment_method": "card"     ("cash" | "card" | "wallet")
    }

    If payment_method is "wallet", wallet_amount is automatically set to the
    full quoted_price. Wallet balance is re-validated inside a DB row lock.

    Response 200: <ServiceRequest>  (status: "confirmed", final_price set)
    Response 400: insufficient wallet balance, or invalid payment split
    Response 404: not found, not owned by caller, or status is not "quoted"

    Notification fired:
      quote_approved → provider

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/reject-quote/ [customer token]

    Customer rejects the provider's price. Request returns to the open
    pool. Provider's total_jobs is decremented. quoted_price is cleared.
    Transition: quoted → pending.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "pending", provider: null)
    Response 404: not found, not owned by caller, or status is not "quoted"

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/initiate-card-payment/ [customer token]

    Required for card payments (payment_method == "card" and card_amount > 0).
    Must be called after /approve-quote/ and before the provider calls /complete/.

    Attaches a Stripe PaymentMethod to the request and creates a PaymentIntent
    with capture_method="manual". The card is authorized but not charged yet.
    Capture happens automatically when the provider calls /complete/.

    Request:
    {
        "stripe_payment_method_id": "pm_xxx"   (required, from Stripe client SDK)
    }

    Response 200: <ServiceRequest> + { "stripe_client_secret": "pi_xxx_secret_xxx" }
    Response 400: payment_method is not "card", no card amount to charge,
                  or Stripe error
    Response 404: not found, not owned by caller, or status is not
                  "confirmed" or "in_progress"

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/rate/ [customer token]

    Rate the provider after a completed job. One review per request.
    Idempotent — submitting again returns the existing review unchanged.

    Request:
    {
        "rating":  5,             (required, 1-5)
        "comment": "Great work!"  (optional)
    }

    Response 201: <Review>   (first submission)
    Response 200: <Review>   (already rated — existing review returned)
    Response 400: request not completed, no provider, or rating out of range
    Response 404: not found or not owned by caller

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — PROVIDER ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/requests/ [provider token]
?status=<status> (optional filter)

    Returns all jobs assigned to this provider (any status), newest first.

    Response 200 (paginated): { "count": N, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/<id>/ [provider token]

    Returns a job assigned to this provider by ID.

    Response 200: <ServiceRequest>
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/open/ [provider token]

    Pending requests available for self-assignment, filtered to the
    provider's registered categories.

    Sort order:
      1. Urgent first (is_urgent=true)
      2. Nearest first — when provider has a saved location
         (distance_km populated on each result)
      3. Newest first

    Response 200 (paginated): { "count": N, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/incoming/ [provider token]

    Jobs in "assigned" status for this provider — awaiting a quote or direct accept.
    Ordered by assigned_at descending.

    Response 200 (paginated): { "count": N, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/pick/ [provider token]

    Self-assign a pending request from the open pool.
    Transition: pending → assigned.

    Guards:
      Category guard   — request category must match provider's categories.
      Active-job guard — provider must have no active job
                         (assigned / quoted / confirmed / in_progress).
      Race guard       — DB row lock; second concurrent attempt gets 404.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "assigned")
    Response 400: provider already has an active job
    Response 404: not found, not pending, or category does not match

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/quote/ [provider token]

    Submit a price for the assigned job.
    Transition: assigned → quoted.
    Customer receives the quote and must approve or reject it.

    Request: { "price": "150.00" }  (required, min 0)

    Response 200: <ServiceRequest>  (status: "quoted", quoted_price set)
    Response 400: invalid price (negative)
    Response 404: not found, not assigned to caller, or status is not "assigned"

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/accept/ [provider token]

    Skip the quote step and accept the job directly.
    Transition: assigned → confirmed.
    Only valid from "assigned" — cannot bypass a pending customer approval.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "confirmed")
    Response 404: not found, not assigned to caller, or status is not "assigned"

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/decline/ [provider token]

    Reject the assignment. Request returns to the open pool.
    Transition: assigned → pending.
    Provider total_jobs is decremented. declined_at is stamped.

    Request: { "reason": "Not available" }  (optional)

    Response 200: <ServiceRequest>  (status: "pending", provider: null)
    Response 400: status is not "assigned"
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/start/ [provider token]

    Provider arrives and begins work.
    Transition: confirmed → in_progress.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "in_progress")
    Response 400: status is not "confirmed"
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/complete/ [provider token]

    Provider finishes the job.
    Transition: in_progress → completed.

    final_price is locked from the quote approval step — no body param
    is accepted or needed. Payment is settled automatically.

    Payment is settled automatically at this point (see PAYMENT FLOW).
    On completion:
      Provider: completed_jobs +1, total_earnings +final_price.
      Provider available_balance: +wallet_amount + card_amount
        (cash portion goes directly to the provider, not via platform).
      Customer: total_bookings +1.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "completed", payment_status updated)
    Response 400: status is not "in_progress"
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/provider-cancel/ [provider token]

    Provider cancels their own assignment.
    Transition: any non-terminal → cancelled.
    Provider total_jobs is decremented if status was assigned / quoted /
    confirmed / in_progress.

    Request: { "reason": "Emergency" }  (optional)

    Response 200: <ServiceRequest>  (status: "cancelled", cancelled_by: "provider")
    Response 400: already completed or cancelled
    Response 404: not found or not assigned to caller

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — HISTORY DETAIL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/history/<id>/

    Full detail for a single booking. The token role determines
    both the serializer and the ownership scope.

    Customer token → provider card + is_favorite_provider + review
                     + provider distance/ETA.
    Provider token → customer card + review + distance to job / ETA.

    ── Customer token response ──────────────────────────────────

    Response 200:
    {
        "id":                   "uuid",
        "status":               "completed",
        "status_display":       "Completed",
        "category":             { "id": 1, "name": "Plumbing" },
        "region":               { "id": 1, "name": "Cairo" },
        "photos":               [ <Photo>, ... ],
        "address":              "12 Tahrir St",
        "floor_number":         "3",
        "apartment_number":     "12",
        "special_mark":         "Blue door on the left",
        "latitude":             30.044420,
        "longitude":            31.235712,
        "provider_distance_km": 1.34,
        "provider_eta_minutes": 3,
        "title":                "Leaking pipe",
        "description":          "Details...",
        "is_urgent":            false,
        "preferred_date":       "2025-08-01",
        "preferred_time":       "10:00:00",
        "estimated_price":      "150.00",
        "quoted_price":         "150.00",
        "final_price":          "150.00",
        "payment_method":       "wallet",
        "payment_method_display": "Wallet",
        "wallet_amount":        "150.00",
        "card_amount":          "0.00",
        "payment_status":       "paid",
        "payment_status_display": "Paid",
        "cancellation_reason":  "",
        "decline_reason":       "",
        "created_at":           "2025-07-20T08:00:00Z",
        "assigned_at":          "2025-07-21T09:00:00Z",
        "confirmed_at":         "2025-07-21T10:00:00Z",
        "started_at":           "2025-08-01T09:30:00Z",
        "completed_at":         "2025-08-01T12:00:00Z",
        "cancelled_at":         null,
        "provider":             <ProviderCard>,
        "review":               null | <Review>,
        "is_favorite_provider": false
    }

    ── Provider token response ───────────────────────────────────

    Response 200:
    {
        "id":                 "uuid",
        "status":             "completed",
        "status_display":     "Completed",
        "category":           { "id": 1, "name": "Plumbing" },
        "region":             { "id": 1, "name": "Cairo" },
        "photos":             [ <Photo>, ... ],
        "address":            "12 Tahrir St",
        "floor_number":       "3",
        "apartment_number":   "12",
        "special_mark":       "Blue door on the left",
        "latitude":           30.044420,
        "longitude":          31.235712,
        "distance_to_job_km": 1.34,
        "eta_to_job_minutes": 3,
        "title":              "Leaking pipe",
        "description":        "Details...",
        "is_urgent":          false,
        "preferred_date":     "2025-08-01",
        "preferred_time":     "10:00:00",
        "estimated_price":    "150.00",
        "quoted_price":       "150.00",
        "final_price":        "150.00",
        "payment_method":     "wallet",
        "payment_method_display": "Wallet",
        "wallet_amount":      "150.00",
        "card_amount":        "0.00",
        "payment_status":     "paid",
        "payment_status_display": "Paid",
        "created_at":         "2025-07-20T08:00:00Z",
        "assigned_at":        "2025-07-21T09:00:00Z",
        "confirmed_at":       "2025-07-21T10:00:00Z",
        "started_at":         "2025-08-01T09:30:00Z",
        "completed_at":       "2025-08-01T12:00:00Z",
        "cancelled_at":       null,
        "customer":           <CustomerCard>,
        "review":             null | <Review>
    }

    provider_distance_km / provider_eta_minutes / distance_to_job_km /
    eta_to_job_minutes — null when the provider has no saved location.

    Response 404: not found or not owned by caller

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Value Description
───────────────────────────────────────────────────────
pending Waiting to be assigned to a provider
assigned Provider assigned — awaiting quote or direct accept
quoted Provider submitted a price; awaiting customer decision
confirmed Price agreed (or skip-quote accepted) — job is scheduled
in_progress Provider on-site, work has started
completed Job finished. All stats updated. [TERMINAL]
cancelled Cancelled by customer / provider / admin. [TERMINAL]

Note: "declining" and "rejecting quote" are actions, not statuses.
Both reset the request to "pending".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ERROR REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Code Meaning
───────────────────────────────────────────────────────
400 Validation failure, illegal FSM transition, provider
already has an active job, insufficient wallet balance,
or no photos attached on create
401 Missing or invalid Knox token
403 Token valid but wrong role for this endpoint
404 Not found, not owned / assigned to caller, request is
not in the required status for this action (status-
filtered endpoints return 404 rather than 400 for
wrong-status requests), or category does not match
provider (pick / open pool)
