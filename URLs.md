━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SNAPFIX API — REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All endpoints require: Authorization: Token <knox-token>
Exceptions: register and login endpoints (marked [public])

Base URL: /api/v1/

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATE FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

pending ──→ assigned ──→ confirmed ──→ in_progress ──→ completed
               │
               └──→ pending  (provider declines — returns to open pool)

CANCELLED is reachable from: pending, assigned, confirmed, in_progress.
COMPLETED and CANCELLED are terminal states.

Status       Who triggers
───────────────────────────────────────────────────────
pending      Customer creates request
assigned     Admin assigns a provider  OR
             Provider self-picks from the open pool
confirmed    Provider accepts the assignment
in_progress  Provider starts work on-site
completed    Provider finishes the job  [TERMINAL]
cancelled    Customer, provider, or admin cancels  [TERMINAL]

Guards enforced on every transition:
  Active-job guard — a provider cannot self-assign if they already
    have a job in assigned / confirmed / in_progress.
  Category guard — open pool and /pick/ only surface requests
    whose category matches one of the provider's registered categories.
    A provider cannot pick an out-of-category job even by UUID.
  Race guard — /pick/ uses a DB row lock; the second concurrent
    attempt gets 404.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHARED OBJECTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

These shapes are reused throughout the document.

<CustomerCard>  — embedded in provider history detail
{
    "id":             "uuid",
    "email":          "customer@example.com",
    "first_name":     "Shady",
    "last_name":      "Abadeer",
    "phone":          "01284688383",
    "wallet_balance": "0.00",
    "total_bookings": 5,
    "is_verified":    true,
    "date_joined":    "2025-01-01T00:00:00Z"
}

<ProviderCard>  — embedded in customer history detail and favorites
{
    "id":                "uuid",
    "email":             "provider@example.com",
    "first_name":        "Mohamed",
    "last_name":         "Ali",
    "phone":             "01284688383",
    "business_name":     "Ali Fixes",
    "bio":               "...",
    "verification_status": "verified",
    "is_available":      true,
    "rating":            4.75,
    "total_reviews":     20,
    "total_jobs":        25,
    "completed_jobs":    23,
    "completion_rate":   92.0,
    "available_balance": "1840.00",
    "total_earnings":    "2400.00",
    "hourly_rate":       "80.00",
    "years_of_experience": 5,
    "latitude":          30.044420,
    "longitude":         31.235712,
    "date_joined":       "2025-01-01T00:00:00Z"
}

<Review>  — embedded in booking responses
{
    "id":         "uuid",
    "rating":     5,
    "comment":    "Great work!",
    "created_at": "2025-08-02T10:00:00Z"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CUSTOMERS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

POST /api/v1/customers/register/   [public]

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

POST /api/v1/customers/login/   [public]

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

    latitude / longitude — floats from PostGIS PointField.
    Null when the customer has not yet shared their location.

────────────────────────────────────────────────────────

PATCH /api/v1/customers/me/

    Updates non-sensitive profile fields. All fields optional.
    Locked fields (ignored if sent): email, password, wallet_balance,
    total_cashback, total_bookings, is_verified.

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

ONBOARDING FLOW
───────────────
1. Provider registers via the app (POST /register/).
   Account is created INACTIVE — no token is issued.
2. Provider visits the nearest office with their documents.
   Staff fill in the onboarding form and submit for review.
3. Admin approves the application via the Admin Dashboard.
   Provider account is activated and verification_status
   is set to "verified".
4. Provider can now log in (POST /login/).

POST /api/v1/providers/register/   [public]

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
        "message":   "Registration received. Please visit your nearest
                      office to complete your verification. You will be
                      able to log in once approved.",
        "next_step": "Visit /api/v1/core/offices/nearest/ to find the
                      closest office to you."
    }

    No token is issued. The account is inactive until staff approval.

    Response 400: email already registered or validation failure

────────────────────────────────────────────────────────

POST /api/v1/providers/login/   [public]

    Only succeeds when:
      — credentials are valid
      — account is active (approved by staff)
      — verification_status is "verified"

    Request:
    { "email": "provider@example.com", "password": "shady123!" }

    Response 200:
    {
        "provider": <ProviderCard>,
        "token":    "<knox-token>"
    }

    Response 400: invalid credentials or account not yet verified

────────────────────────────────────────────────────────

POST /api/v1/providers/logout/

    Response 204 No Content

────────────────────────────────────────────────────────

GET /api/v1/providers/me/

    Full profile for the authenticated provider.

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

    latitude / longitude — floats from PostGIS PointField.
    Null when the provider has no saved location yet.

────────────────────────────────────────────────────────

PATCH /api/v1/providers/me/

    Updates non-sensitive profile fields. All fields optional.
    Locked fields (ignored if sent): email, password, region,
    categories, verification_status, rating, total_reviews,
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

    latitude and longitude must be provided together or not at all.

    Response 200: updated profile (same shape as GET /me/)
    Response 400: only one of latitude/longitude provided

────────────────────────────────────────────────────────

PATCH /api/v1/providers/me/location/   [provider token]

    Lightweight endpoint for updating the provider's current GPS
    position. Call approximately every 60 seconds while on an
    active job. Only updates the location — no other fields touched.
    Both fields are required.

    Request:
    {
        "latitude":  30.044420,   (required, -90 to 90)
        "longitude": 31.235712    (required, -180 to 180)
    }

    Response 200:
    {
        "latitude":  30.044420,
        "longitude": 31.235712
    }

    Response 400: missing or out-of-range coordinates
    Response 403: not a provider account

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
    Useful for directing new providers to register in person.

    Query params (both required):
        lat — e.g. 30.044420
        lng — e.g. 31.235712

    Response 200: office detail + "distance_km": 2.45
    Response 400: lat/lng missing or not valid numbers
    Response 404: no active offices found

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOTE — Office management is via the Admin Dashboard only.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — SERVICE REQUEST OBJECT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Returned by all booking action endpoints (pick, accept, start, etc.)
and by the list / detail endpoints.

{
    "id":                   "3f2a1b...",
    "status":               "pending",
    "status_display":       "Pending",
    "category":             { "id": 1, "name": "Plumbing" },
    "region":               { "id": 1, "name": "Cairo" },
    "address":              "12 Tahrir St, Apt 3",
    "floor_number":         "3",
    "apartment_number":     "12",
    "special_mark":         "Blue door on the left",
    "latitude":             30.044420,
    "longitude":            31.235712,
    "distance_km":          null,
    "provider_distance_km": null,
    "provider_eta_minutes": null,
    "title":                "Leaking pipe under sink",
    "description":          "Kitchen pipe dripping for 2 days.",
    "is_urgent":            false,
    "preferred_date":       "2025-08-01",
    "preferred_time":       "10:00:00",
    "estimated_price":      "150.00",
    "final_price":          null,
    "cancelled_by":         "",
    "cancelled_by_display": "",
    "cancellation_reason":  "",
    "decline_reason":       "",
    "created_at":           "2025-07-20T08:00:00Z",
    "assigned_at":          null,
    "confirmed_at":         null,
    "started_at":           null,
    "completed_at":         null,
    "cancelled_at":         null,
    "declined_at":          null,
    "review":               null
}

Field notes:
  floor_number, apartment_number, special_mark
      Required at creation time. Always present in responses.

  latitude / longitude
      Floats extracted from the stored PostGIS point.

  distance_km
      Straight-line distance (km) from the provider's current location
      to the job. Populated only in GET /requests/open/ when the provider
      has a saved location. Null in all other responses.

  provider_distance_km / provider_eta_minutes
      Straight-line distance (km) and estimated travel time (minutes,
      assuming 30 km/h) from the assigned provider's last known location
      to the job. Both null when no provider is assigned, or when the
      provider has not yet sent a location ping.

  decline_reason
      The reason given by the most recent provider who declined this
      assignment. Persists as an audit field even after the request is
      reassigned and completed.

  declined_at
      Timestamp of the most recent decline action. Non-null means this
      request was declined at least once before and returned to pending.
      The request can still be pending, in-progress, or completed — this
      is an audit field only, not a status indicator.

  cancelled_by / cancelled_by_display
      Empty string when the request is not cancelled.
      Values: "customer", "provider", "admin".

  review
      Null until the customer rates the completed job.
      Once rated: <Review> object.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — CUSTOMER ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/requests/   [customer token]
    ?status=<status>   (optional filter)

    Returns the customer's own service requests, newest first.

    Response 200 (paginated): { "count": N, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/   [customer token]

    Creates a new service request. Status starts as pending.
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
        "is_urgent":        false,
        "estimated_price":  "150.00"
    }

    Response 201: <ServiceRequest>
    Response 400: missing required fields or invalid coordinates
    Response 403: provider token used

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/<id>/   [customer token]

    Returns the customer's own request by ID.

    Response 200: <ServiceRequest>
    Response 404: not found or not owned by caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/cancel/   [customer token]

    Cancels the request. Allowed from any non-terminal status
    (pending, assigned, confirmed, in_progress).

    Request: { "reason": "Changed my mind" }  (optional)

    Response 200: <ServiceRequest>  (status: "cancelled", cancelled_by: "customer")
    Response 400: already completed or cancelled
    Response 404: not found or not owned by caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/rate/   [customer token]

    Customer rates the provider after a completed job.
    One review per service request. Submitting again returns the
    existing review unchanged (idempotent — safe to call twice).

    Guards: request must be completed and have an assigned provider.

    Request:
    {
        "rating":  5,             (required, 1–5)
        "comment": "Great work!"  (optional)
    }

    Response 201: <Review>   (first submission)
    Response 200: <Review>   (already rated — existing review returned)
    Response 400: request not completed, or no provider, or rating out of range
    Response 404: not found or not owned by caller

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — PROVIDER ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/requests/   [provider token]
    ?status=<status>   (optional filter)

    Returns all jobs assigned to this provider, newest first.
    Includes jobs in any status (assigned through completed/cancelled).

    Response 200 (paginated): { "count": N, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/<id>/   [provider token]

    Returns a job assigned to this provider by ID.

    Response 200: <ServiceRequest>
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/open/   [provider token]

    Pending requests available for self-assignment. Filtered to
    categories matching the provider's registered categories.

    Sort order:
      1. Urgent requests first (is_urgent=true)
      2. Nearest first — when provider has a saved location
         (distance_km populated on each result)
      3. Newest first (created_at descending)

    When the provider has no saved location, distance_km is null
    and results are sorted by urgency then recency only.

    Response 200 (paginated): { "count": 3, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

GET /api/v1/bookings/requests/incoming/   [provider token]

    Requests in assigned status for this provider — awaiting
    their accept or decline. This includes both admin-assigned
    and self-picked requests.
    Ordered by assigned_at descending.

    Response 200 (paginated): { "count": 1, "results": [ <SR>, ... ] }

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/pick/   [provider token]

    Provider self-assigns a pending request from the open pool.
    Transition: pending → assigned.

    After picking, the request appears in /incoming/ and the
    provider must still call /accept/ to confirm.

    Guards (all enforced — cannot be bypassed via UUID):
      Category guard  — request category must match provider's categories.
      Active-job guard — provider must have no active job.
      Race guard       — DB row lock; second concurrent attempt gets 404.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "assigned")
    Response 400: provider already has an active job
    Response 404: request not found, no longer pending, or
                  category does not match provider

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/accept/   [provider token]

    Provider confirms they will take the job.
    Transition: assigned → confirmed.
    Applies to both admin-assigned and self-picked requests.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "confirmed")
    Response 400: status is not assigned
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/decline/   [provider token]

    Provider rejects the assignment. Request returns to the open
    pool for reassignment.
    Transition: assigned → pending.

    declined_at is stamped as an audit trail. decline_reason
    persists until the request is completed or cancelled.

    Request: { "reason": "Not available" }  (optional)

    Response 200: <ServiceRequest>
        status:      "pending"
        provider:    null
        assigned_at: null
        declined_at: "<timestamp>"
    Response 400: status is not assigned
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/start/   [provider token]

    Provider arrives and begins work.
    Transition: confirmed → in_progress.

    Request: (no body)

    Response 200: <ServiceRequest>  (status: "in_progress")
    Response 400: status is not confirmed
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/complete/   [provider token]

    Provider finishes the job.
    Transition: in_progress → completed.

    On completion the following are updated atomically:
      Provider: completed_jobs +1, total_earnings +final_price,
                available_balance +final_price.
      Customer: total_bookings +1.

    Request: { "final_price": "150.00" }  (optional, min 0)

    Response 200: <ServiceRequest>  (status: "completed")
    Response 400: status is not in_progress
    Response 404: not found or not assigned to caller

────────────────────────────────────────────────────────

POST /api/v1/bookings/requests/<id>/provider-cancel/   [provider token]

    Provider cancels their own assignment.
    Transition: any non-terminal → cancelled.

    total_jobs is rolled back if the request was in assigned,
    confirmed, or in_progress at the time of cancellation.

    Request: { "reason": "Emergency" }  (optional)

    Response 200: <ServiceRequest>  (status: "cancelled", cancelled_by: "provider")
    Response 400: already completed or cancelled
    Response 404: not found or not assigned to caller

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOOKING — HISTORY DETAIL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET /api/v1/bookings/history/<id>/

    Full detail for a single booking. The token role determines
    the serializer and the ownership scope.

      Customer token → provider card + is_favorite_provider + review
                       + provider distance/ETA.
      Provider token → customer card + review + distance to job / ETA.

    Use GET /requests/ to browse all bookings, then this endpoint
    to load the full detail screen for a specific one.

    ── Customer token response ──────────────────────────────────

    Response 200:
    {
        "id":                   "uuid",
        "status":               "completed",
        "status_display":       "Completed",
        "category":             { "id": 1, "name": "Plumbing" },
        "region":               { "id": 1, "name": "Cairo" },
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
        "final_price":          "150.00",
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

    provider_distance_km / provider_eta_minutes:
      From the provider's last known location to the job.
      Both null when the provider has no saved location.

    ── Provider token response ───────────────────────────────────

    Response 200:
    {
        "id":                 "uuid",
        "status":             "completed",
        "status_display":     "Completed",
        "category":           { "id": 1, "name": "Plumbing" },
        "region":             { "id": 1, "name": "Cairo" },
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
        "final_price":        "150.00",
        "created_at":         "2025-07-20T08:00:00Z",
        "assigned_at":        "2025-07-21T09:00:00Z",
        "confirmed_at":       "2025-07-21T10:00:00Z",
        "started_at":         "2025-08-01T09:30:00Z",
        "completed_at":       "2025-08-01T12:00:00Z",
        "cancelled_at":       null,
        "customer":           <CustomerCard>,
        "review":             null | <Review>
    }

    distance_to_job_km / eta_to_job_minutes:
      Same calculation from the provider's perspective.
      Both null when the provider has no saved location.

    Response 404: not found or not owned by caller

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Value         Description
───────────────────────────────────────────────────────
pending       Waiting to be assigned to a provider
assigned      Provider assigned — awaiting accept or decline
confirmed     Provider accepted — job is scheduled
in_progress   Provider on-site, work has started
completed     Job finished. All stats updated.  [TERMINAL]
cancelled     Cancelled by customer / provider / admin.  [TERMINAL]

Note: "declining" is an action, not a status. When a provider
declines, the status resets to pending and declined_at is stamped.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ERROR REFERENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Code  Meaning
───────────────────────────────────────────────────────
400   Validation failure, invalid FSM transition, or
      provider already has an active job (pick guard)
401   Missing or invalid Knox token
403   Token valid but wrong role for this endpoint
404   Not found, not owned by caller, request no longer
      in the required status (e.g. race on /pick/), or
      category does not match provider (pick / open pool)
