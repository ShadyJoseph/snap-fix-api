━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SNAPFIX API — BOOKING SYSTEM REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All endpoints require: Authorization: Token <knox-token>
(except /register/ and /login/)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATE FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

pending ──→ assigned ──→ confirmed ──→ in_progress ──→ completed
↑ │
│ └──→ declined ──→ pending (back to pool)
│
└── assigned by admin OR self-assigned by provider (pick)

CANCELLED is reachable from any non-terminal state.
COMPLETED and CANCELLED are terminal — no further transitions.

Status Who triggers it
─────────────────────────────────────────────────────────
pending Created by customer
assigned Admin assigns a provider OR
Provider picks from the open pool
confirmed Provider accepts the assignment
in_progress Provider starts work
completed Provider finishes the job
cancelled Customer, provider, or admin cancels
declined Provider rejects assignment (resets to pending)

Guard (pick only): a provider cannot self-assign if they
already have an active job (assigned / confirmed / in_progress).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CUSTOMERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

POST /api/v1/customers/register/

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
        "id":         "uuid",
        "email":      "customer@example.com",
        "first_name": "Shady",
        "last_name":  "Abadeer",
        "phone":      "01284688383",
        "token":      "<knox-token>"
    }

────────────────────────────────────────────────────────

POST /api/v1/customers/login/

    Request:
    {
        "email":    "customer@example.com",
        "password": "shady123!"
    }

    Response 200:
    {
        "token":  "<knox-token>",
        "expiry": "2025-12-31T23:59:59Z",
        "user": {
            "id":         "uuid",
            "email":      "customer@example.com",
            "first_name": "Shady"
        }
    }

────────────────────────────────────────────────────────

GET /api/v1/customers/me/

    Response 200:
    {
        "id":             "uuid",
        "email":          "customer@example.com",
        "first_name":     "Shady",
        "last_name":      "Abadeer",
        "phone":          "01284688383",
        "total_bookings": 5
    }

────────────────────────────────────────────────────────

POST /api/v1/customers/logout/

    Response 204 No Content

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROVIDERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Note: Full onboarding (categories, region, verification)
is completed via the Admin Dashboard after registration.

POST /api/v1/providers/register/

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
        "id":         "uuid",
        "email":      "provider@example.com",
        "first_name": "Shady",
        "token":      "<knox-token>"
    }

────────────────────────────────────────────────────────

POST /api/v1/providers/login/

    Request:
    {
        "email":    "provider@example.com",
        "password": "shady123!"
    }

    Response 200:
    {
        "token":  "<knox-token>",
        "expiry": "2025-12-31T23:59:59Z",
        "user": {
            "id":    "uuid",
            "email": "provider@example.com"
        }
    }

────────────────────────────────────────────────────────

GET /api/v1/providers/me/

    Response 200:
    {
        "id":                "uuid",
        "email":             "provider@example.com",
        "first_name":        "Shady",
        "total_jobs":        12,
        "completed_jobs":    10,
        "total_earnings":    "2400.00",
        "available_balance": "2400.00"
    }

────────────────────────────────────────────────────────

POST /api/v1/providers/logout/

    Response 204 No Content

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CORE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/core/categories/

    Response 200:
    [
        { "id": 1, "name": "Plumbing",   "icon": "wrench" },
        { "id": 2, "name": "Electrical", "icon": "bolt"   }
    ]

────────────────────────────────────────────────────────

GET /api/v1/core/regions/

    Response 200:
    [
        { "id": 1, "name": "Cairo" },
        { "id": 2, "name": "Giza"  }
    ]

────────────────────────────────────────────────────────

GET /api/v1/core/offices/

    Returns all active offices.

    Response 200:
    [
        {
            "id":           "uuid",
            "name":         "Cairo Main Office",
            "address":      "5 Tahrir Square, Cairo",
            "landmark":     "Next to the Egyptian Museum",
            "latitude":     "30.044420",
            "longitude":    "31.235712",
            "region_name":  "Cairo",
            "working_hours": "Sun–Thu 9:00 AM – 5:00 PM"
        }
    ]

────────────────────────────────────────────────────────

GET /api/v1/core/offices/<id>/

    Returns full detail for a single active office.

    Response 200:
    {
        "id":           "uuid",
        "name":         "Cairo Main Office",
        "address":      "5 Tahrir Square, Cairo",
        "landmark":     "Next to the Egyptian Museum",
        "latitude":     "30.044420",
        "longitude":    "31.235712",
        "region": {
            "id":        "uuid",
            "name":      "Cairo",
            "slug":      "cairo",
            "code":      "CAI",
            "country":   "Egypt",
            "latitude":  "30.044420",
            "longitude": "31.235712",
            "is_active": true
        },
        "working_hours": "Sun–Thu 9:00 AM – 5:00 PM",
        "is_active":     true,
        "created_at":    "2025-07-20T08:00:00Z"
    }

    Response 404: office not found or inactive

────────────────────────────────────────────────────────

GET /api/v1/core/offices/nearest/?lat=<lat>&lng=<lng>

    Returns the single closest active office to the given coordinates.
    Offices without a saved location are excluded.

    Query params:
        lat   (required) — user latitude  e.g. 30.044420
        lng   (required) — user longitude e.g. 31.235712

    Response 200:
    {
        "id":           "uuid",
        "name":         "Cairo Main Office",
        "address":      "5 Tahrir Square, Cairo",
        "landmark":     "Next to the Egyptian Museum",
        "latitude":     "30.044420",
        "longitude":    "31.235712",
        "region": { ... },
        "working_hours": "Sun–Thu 9:00 AM – 5:00 PM",
        "is_active":     true,
        "created_at":    "2025-07-20T08:00:00Z",
        "distance_km":   2.45
    }

    Response 400: lat or lng missing, or not valid numbers
    Response 404: no active offices with a saved location exist

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOTE — Office management (add / edit / delete) is done
exclusively via the Admin Dashboard. There are no write
endpoints for offices in the public API.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — CUSTOMER ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SERVICE REQUEST OBJECT (returned by all booking endpoints)
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
"description": "Kitchen pipe has been dripping for 2 days.",
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
"declined_at": null
}

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/

    Returns all requests belonging to the authenticated customer.

    Response 200 (paginated):
    {
        "count":    1,
        "next":     null,
        "previous": null,
        "results":  [ <ServiceRequest>, ... ]
    }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/

    Creates a new service request. Status is automatically set to pending.
    The customer is taken from the auth token — never from the body.

    Request (required fields marked with *):
    {
        "category":        1,               *
        "region":          1,               *
        "address":         "12 Tahrir St",  *
        "title":           "Leaking pipe",  *
        "description":     "Details...",    *
        "preferred_date":  "2025-08-01",    *  (YYYY-MM-DD)
        "preferred_time":  "10:00:00",      *  (HH:MM:SS)
        "latitude":        "30.044420",
        "longitude":       "31.235712",
        "is_urgent":       false,
        "estimated_price": "150.00"
    }

    Response 201: <ServiceRequest>

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/<id>/

    Returns a single request. Customer can only access their own.

    Response 200: <ServiceRequest>
    Response 404: request not found or belongs to another customer

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/cancel/

    Customer cancels a request.
    Allowed from: pending, assigned, confirmed, in_progress.

    Request:
    {
        "reason": "Changed my mind"   (optional)
    }

    Response 200: <ServiceRequest>  (status: "cancelled", cancelled_by: "customer")
    Response 400: request is already completed, cancelled, or declined

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — PROVIDER ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/requests/open/

    Browse all pending requests available for self-assignment.
    Urgent requests appear first, then by newest created_at.
    Returns 404 if a specific request is no longer pending
    (already picked by another provider).

    Response 200 (paginated):
    {
        "count":   3,
        "next":    null,
        "previous": null,
        "results": [ <ServiceRequest>, ... ]
    }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/pick/

    Provider self-assigns a pending request from the open pool.
    Transition: pending → assigned.

    Guard: fails if the provider already has a job in any of
    these statuses: assigned, confirmed, in_progress.
    Concurrent picks are safe — the first request wins via
    a database-level row lock; the second receives 404.

    Request: (no body required)

    Response 200: <ServiceRequest>  (status: "assigned", assigned_at: <timestamp>)
    Response 400: provider already has an active job
    Response 404: request not found or no longer pending

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/incoming/

    Lists requests assigned to the provider awaiting accept or decline.
    Status filter: assigned.
    Ordered by assigned_at descending.
    Includes requests assigned by admin AND self-assigned via /pick/.

    Response 200 (paginated):
    {
        "count":   1,
        "results": [ <ServiceRequest>, ... ]
    }

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/my-jobs/

    Lists all of the provider's jobs across every status.
    Ordered by created_at descending.

    Response 200 (paginated):
    {
        "count":   5,
        "results": [ <ServiceRequest>, ... ]
    }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/accept/

    Provider accepts the assignment.
    Transition: assigned → confirmed.
    Works for both admin-assigned and self-assigned requests.

    Request: (no body required)

    Response 200: <ServiceRequest>  (status: "confirmed")
    Response 400: status is not assigned

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/decline/

    Provider declines the assignment.
    Transition: assigned → pending.
    The request returns to the open pool. Admin can reassign
    or another provider can pick it.

    Request:
    {
        "reason": "Not available"   (optional)
    }

    Response 200: <ServiceRequest>  (status: "pending", provider: null)
    Response 400: status is not assigned

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/start/

    Provider starts work on the job.
    Transition: confirmed → in_progress.

    Request: (no body required)

    Response 200: <ServiceRequest>  (status: "in_progress")
    Response 400: status is not confirmed

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/complete/

    Provider marks the job as done.
    Transition: in_progress → completed.
    Provider stats (completed_jobs, total_earnings, available_balance)
    and customer stats (total_bookings) are updated atomically.

    Request:
    {
        "final_price": "150.00"   (optional, min 0)
    }

    Response 200: <ServiceRequest>  (status: "completed")
    Response 400: status is not in_progress

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/provider-cancel/

    Provider cancels the job.
    Transition: any non-terminal → cancelled.
    Provider's total_jobs is rolled back if status was
    assigned, confirmed, or in_progress.

    Request:
    {
        "reason": "Emergency"   (optional)
    }

    Response 200: <ServiceRequest>  (status: "cancelled", cancelled_by: "provider")
    Response 400: request is already completed, cancelled, or declined

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Status Description
─────────────────────────────────────────────────────────
pending Request created, waiting to be assigned
assigned Provider assigned (by admin or self-picked),
awaiting accept or decline
confirmed Provider accepted — job is scheduled
in_progress Provider has started work on-site
completed Job finished, all stats updated [TERMINAL]
cancelled Cancelled by customer, provider, or admin
declined Provider rejected assignment [TERMINAL]
(request resets to pending for reassignment)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ERROR REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Code Meaning
─────────────────────────────────────────────────────────
400 Invalid transition (wrong status), validation failure,
or provider already has an active job (pick guard)
401 Missing or invalid Knox token
403 Token valid but resource belongs to another user
404 Request UUID not found, not owned by the caller,
or no longer in the required status (e.g. picked
by another provider before this request landed)
