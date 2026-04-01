━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SNAPFIX API — REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All endpoints require: Authorization: Token <knox-token>
Exceptions: /register/ and /login/

Base URL: /api/v1/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATE FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

pending ──→ assigned ──→ confirmed ──→ in_progress ──→ completed
│
└──→ pending (provider declines — back to pool)

CANCELLED is reachable from any non-terminal state.
COMPLETED and CANCELLED are terminal.

Status Who triggers
───────────────────────────────────────────────────────
pending Customer creates request
assigned Admin assigns a provider OR
Provider self-picks from the open pool
confirmed Provider accepts the assignment
in_progress Provider starts work
completed Provider finishes the job
cancelled Customer, provider, or admin cancels
declined Provider rejects → request resets to pending

Pick guard: a provider cannot self-assign if they already
have an active job (assigned / confirmed / in_progress).

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
            "total_bookings": 0
        },
        "token": "<knox-token>"
    }

────────────────────────────────────────────────────────

POST /api/v1/customers/login/ [public]

    Request:
    { "email": "customer@example.com", "password": "shady123!" }

    Response 200:
    {
        "customer": { "id": "uuid", "email": "...", ... },
        "token": "<knox-token>"
    }

────────────────────────────────────────────────────────

POST /api/v1/customers/logout/

    Response 204 No Content

────────────────────────────────────────────────────────

GET /api/v1/customers/me/

    Response 200:
    {
        "id":             "uuid",
        "email":          "customer@example.com",
        "first_name":     "Shady",
        "last_name":      "Abadeer",
        "phone":          "01284688383",
        "profile_picture": null,
        "address":        "12 Tahrir St",
        "wallet_balance": "0.00",
        "total_cashback": "0.00",
        "total_bookings": 5,
        "is_verified":    true,
        "date_joined":    "2025-01-01T00:00:00Z"
    }

────────────────────────────────────────────────────────

GET /api/v1/customers/favorites/

    Returns the customer's saved providers.

    Response 200 (paginated):
    {
        "count": 2,
        "results": [ <Provider>, ... ]
    }

────────────────────────────────────────────────────────

POST /api/v1/customers/favorites/<provider_id>/toggle/

    Adds the provider to favorites if not already saved,
    removes them if they are. Idempotent toggle.

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

Note: Full onboarding (documents, region, verification)
is completed via the Admin Dashboard after registration.

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
        "provider": { "id": "uuid", "email": "...", ... },
        "token": "<knox-token>"
    }

────────────────────────────────────────────────────────

POST /api/v1/providers/login/ [public]

    Request:
    { "email": "provider@example.com", "password": "shady123!" }

    Response 200:
    {
        "provider": { "id": "uuid", "email": "...", ... },
        "token": "<knox-token>"
    }

    Response 400: invalid credentials, unverified account

────────────────────────────────────────────────────────

POST /api/v1/providers/logout/

    Response 204 No Content

────────────────────────────────────────────────────────

GET /api/v1/providers/me/

    Response 200:
    {
        "id":                "uuid",
        "email":             "provider@example.com",
        "first_name":        "Shady",
        "last_name":         "Abadeer",
        "phone":             "01284688383",
        "profile_picture":   null,
        "address":           "...",
        "business_name":     "Shady Fixes",
        "bio":               "...",
        "hourly_rate":       "80.00",
        "years_of_experience": 5,
        "region":            1,
        "categories":        [1, 2],
        "verification_status": "verified",
        "is_available":      true,
        "rating":            4.75,
        "total_reviews":     20,
        "total_jobs":        25,
        "completed_jobs":    23,
        "completion_rate":   92.0,
        "available_balance": "1840.00",
        "total_earnings":    "2400.00",
        "date_joined":       "2025-01-01T00:00:00Z"
    }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/core/categories/

    Response 200:
    [ { "id": 1, "name": "Plumbing", "icon": "wrench" }, ... ]

────────────────────────────────────────────────────────

GET /api/v1/core/regions/

    Response 200:
    [ { "id": 1, "name": "Cairo" }, ... ]

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
            "working_hours": "Sun–Thu 9:00 AM – 5:00 PM"
        }
    ]

────────────────────────────────────────────────────────

GET /api/v1/core/offices/<id>/

    Response 200: full office detail including nested region object
    Response 404: office not found or inactive

────────────────────────────────────────────────────────

GET /api/v1/core/offices/nearest/?lat=<lat>&lng=<lng>

    Returns the single closest active office to the given coordinates.

    Query params (both required):
        lat  — e.g. 30.044420
        lng  — e.g. 31.235712

    Response 200: office detail + "distance_km": 2.45
    Response 400: lat/lng missing or not valid numbers
    Response 404: no active offices with a saved location

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOTE — Office management is via the Admin Dashboard only.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — SERVICE REQUEST OBJECT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Returned by all booking action endpoints (accept, start, etc.).

{
"id": "3f2a1b...",
"status": "pending",
"status_display": "Pending",
"category": { "id": 1, "name": "Plumbing" },
"region": { "id": 1, "name": "Cairo" },
"address": "12 Tahrir St, Apt 3",
"latitude": "30.044420",
"longitude": "31.235712",
"title": "Leaking pipe under sink",
"description": "Kitchen pipe dripping for 2 days.",
"is_urgent": false,
"preferred_date": "2025-08-01",
"preferred_time": "10:00:00",
"estimated_price": "150.00",
"final_price": null,
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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — REQUEST ENDPOINTS  (token-aware, both roles)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/requests/
    ?status=<status>    (optional — e.g. completed, pending, cancelled)

    Role-aware list. The token determines what is returned:
      Customer → their own service requests.
      Provider → jobs assigned to them.

    Each item includes a "review" field (null until rated).

    Response 200 (paginated): { "count": N, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/   [customer token only]

    Creates a new service request. Status starts as pending.
    Customer is taken from the auth token — never from the body.

    Request (* = required):
    {
        "category":       1,               *
        "region":         1,               *
        "address":        "12 Tahrir St",  *
        "title":          "Leaking pipe",  *
        "description":    "Details...",    *
        "preferred_date": "2025-08-01",    *  (YYYY-MM-DD)
        "preferred_time": "10:00:00",      *  (HH:MM:SS)
        "latitude":       "30.044420",
        "longitude":      "31.235712",
        "is_urgent":      false,
        "estimated_price": "150.00"
    }

    Response 201: <ServiceRequest>
    Response 403: provider token used

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/<id>/

    Role-aware detail.
      Customer → scoped to their own requests.
      Provider → scoped to jobs assigned to them.

    Response 200: <ServiceRequest>
    Response 404: not found or not owned by caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/cancel/   [customer token]

    Allowed from: pending, assigned, confirmed, in_progress.

    Request: { "reason": "Changed my mind" }  (optional)

    Response 200: <ServiceRequest>  (status: "cancelled", cancelled_by: "customer")
    Response 400: already completed, cancelled, or declined

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/rate/   [customer token]

    Customer rates the provider after a completed job.
    One review per service request. Submitting twice returns
    the existing review (idempotent).

    Guard: request must be completed and have a provider.

    Request:
    {
        "rating":  5,             (required, 1–5)
        "comment": "Great work!"  (optional)
    }

    Response 201: <Review>   (first submission)
    Response 200: <Review>   (already rated — returns existing review)
    Response 400: request not completed, or rating out of range

    Review object:
    {
        "id":         "uuid",
        "rating":     5,
        "comment":    "Great work!",
        "created_at": "2025-08-02T10:00:00Z"
    }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — PROVIDER POOL & ACTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/requests/open/   [provider token]

    All pending requests available for self-assignment.
    Urgent requests appear first, then newest first.

    Response 200 (paginated): { "count": 3, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/incoming/   [provider token]

    Requests assigned to this provider awaiting accept/decline.
    Ordered by assigned_at descending.

    Response 200 (paginated): { "count": 1, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/pick/   [provider token]

    Provider self-assigns a pending request.
    Transition: pending → assigned.

    Guard: fails if provider already has an active job
    (assigned / confirmed / in_progress).
    Concurrent picks are safe — DB row lock ensures first
    request wins; the second receives 404.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "assigned")
    Response 400: provider already has an active job
    Response 404: request not found or no longer pending

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/accept/   [provider token]

    Transition: assigned → confirmed.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "confirmed")
    Response 400: status is not assigned

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/decline/   [provider token]

    Transition: assigned → pending.
    Request returns to the open pool for reassignment.

    Request: { "reason": "Not available" }  (optional)

    Response 200: <ServiceRequest>  (status: "pending", provider: null)
    Response 400: status is not assigned

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/start/   [provider token]

    Transition: confirmed → in_progress.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "in_progress")
    Response 400: status is not confirmed

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/complete/   [provider token]

    Transition: in_progress → completed.
    Provider stats (completed_jobs, total_earnings,
    available_balance) and customer total_bookings
    are updated atomically.

    Request: { "final_price": "150.00" }  (optional, min 0)

    Response 200: <ServiceRequest>  (status: "completed")
    Response 400: status is not in_progress

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/provider-cancel/   [provider token]

    Provider cancels. Rolls back total_jobs if the request
    was in assigned, confirmed, or in_progress.

    Request: { "reason": "Emergency" }  (optional)

    Response 200: <ServiceRequest>  (status: "cancelled", cancelled_by: "provider")
    Response 400: already completed, cancelled, or declined

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — HISTORY DETAIL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/history/<id>/

    Full detail for a single booking. Token role determines
    which serializer is used and what is visible:

      Customer token → provider card + is_favorite_provider + review.
      Provider token → customer card + review.

    Use the list endpoint (GET /requests/) to browse all bookings,
    then this endpoint to load the full detail screen.

    Response 200 (customer token):
    {
        "id":                 "uuid",
        "status":             "completed",
        "status_display":     "Completed",
        "category":           { ... },
        "region":             { ... },
        "address":            "12 Tahrir St",
        "latitude":           "30.044420",
        "longitude":          "31.235712",
        "title":              "Leaking pipe",
        "description":        "Details...",
        "is_urgent":          false,
        "preferred_date":     "2025-08-01",
        "preferred_time":     "10:00:00",
        "estimated_price":    "150.00",
        "final_price":        "150.00",
        "cancellation_reason": "",
        "decline_reason":     "",
        "created_at":         "2025-07-20T08:00:00Z",
        "assigned_at":        "2025-07-21T09:00:00Z",
        "confirmed_at":       "2025-07-21T10:00:00Z",
        "started_at":         "2025-08-01T09:30:00Z",
        "completed_at":       "2025-08-01T12:00:00Z",
        "provider": {
            "id":              "uuid",
            "first_name":      "Mohamed",
            "last_name":       "Ali",
            "business_name":   "Ali Fixes",
            "rating":          4.75,
            "total_reviews":   20,
            "completion_rate": 92.0,
            ...
        },
        "review": null | { "id": "uuid", "rating": 5, "comment": "...", "created_at": "..." },
        "is_favorite_provider": false
    }

    Response 200 (provider token):
    {
        "id":             "uuid",
        "status":         "completed",
        "status_display": "Completed",
        "category":       { ... },
        "region":         { ... },
        "address":        "12 Tahrir St",
        "latitude":       "30.044420",
        "longitude":      "31.235712",
        "title":          "Leaking pipe",
        "description":    "Details...",
        "is_urgent":      false,
        "preferred_date": "2025-08-01",
        "preferred_time": "10:00:00",
        "estimated_price": "150.00",
        "final_price":    "150.00",
        "created_at":     "2025-07-20T08:00:00Z",
        "assigned_at":    "2025-07-21T09:00:00Z",
        "confirmed_at":   "2025-07-21T10:00:00Z",
        "started_at":     "2025-08-01T09:30:00Z",
        "completed_at":   "2025-08-01T12:00:00Z",
        "customer": {
            "id":             "uuid",
            "first_name":     "Shady",
            "last_name":      "Abadeer",
            "total_bookings": 5,
            ...
        },
        "review": null | { "id": "uuid", "rating": 5, "comment": "...", "created_at": "..." }
    }

    Response 404: not found or not owned by caller

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Status Description
───────────────────────────────────────────────────────
pending Waiting to be assigned
assigned Provider assigned, awaiting accept/decline
confirmed Provider accepted — job scheduled
in_progress Provider on-site, work started
completed Job done, all stats updated [TERMINAL]
cancelled Cancelled by customer/provider/admin [TERMINAL]
declined Provider rejected → resets to pending

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ERROR REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Code Meaning
───────────────────────────────────────────────────────
400 Invalid transition, validation failure, or
provider already has an active job (pick guard)
401 Missing or invalid Knox token
403 Token valid but resource belongs to another user
404 Not found, not owned by caller, or no longer in
the required status (e.g. race on /pick/)
