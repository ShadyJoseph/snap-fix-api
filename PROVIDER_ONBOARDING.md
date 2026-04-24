# Provider Self-Service Onboarding — Mobile Integration Guide

---

## 1. Overview

Providers register themselves through the mobile app. The flow is:

```
Register → Fill Personal Info → Upload Documents → Submit
    ↓
AI validates documents automatically (background)
    ↓
Staff review in admin → Approve / Reject / Request Changes
    ↓
Provider gets FCM push → Can now log in fully
```

Key design decisions that affect the mobile UX:

- **Two-token model**: after registration the provider gets an `onboarding_token` that only works on the onboarding endpoints. The full login token is only issued after approval.
- **DRAFT is sticky**: providers can save progress and come back. All onboarding endpoints accept partial data.
- **AI validation is non-blocking**: it runs in the background after submission and never stalls the onboarding queue — if AI fails, staff still see the application.

---

## 2. Authentication Model

| Stage                   | Token                                  | What it unlocks           |
| ----------------------- | -------------------------------------- | ------------------------- |
| After `POST /register/` | `onboarding_token` (Knox)              | Onboarding endpoints only |
| After staff approval    | Full login token (from `POST /login/`) | All provider features     |

**The `onboarding_token` returned at registration IS a valid Knox auth token.** Use it as a Bearer token on all `/onboarding/*` endpoints. It will be rejected on active-provider endpoints (`/me/`, `/logout/`, booking endpoints) until approval because `verification_status` stays `pending` until then.

Store `onboarding_token` locally — the provider needs it to resume onboarding if they close the app mid-flow.

---

## 3. Step-by-Step Flow

### Step 1 — Register

```
POST /api/v1/providers/register/
```

Creates the provider account. Response includes `onboarding_token` to use on all subsequent onboarding calls.

### Step 2 — Personal & Professional Info

```
PATCH /api/v1/providers/onboarding/personal/
Authorization: Token <onboarding_token>
```

Save DOB, address, region, category, hourly rate, etc. Can be called multiple times to update — only DRAFT and CHANGES_REQUIRED applications accept updates.

### Step 3 — Document Upload

```
PATCH /api/v1/providers/onboarding/documents/
Authorization: Token <onboarding_token>
Content-Type: multipart/form-data
```

Upload NID front, NID back, police clearance. Optional: professional cert, profile photo. Can be called independently from personal info — call it as many times as needed before submitting.

### Step 4 — Submit

```
POST /api/v1/providers/onboarding/submit/
Authorization: Token <onboarding_token>
```

Finalises the application. The API validates all required fields are present before accepting. On success:

- Application moves to `status: pending`
- AI validation starts in the background (`ai_validation_status: running`)
- Provider should see a "submitted, we'll review" screen

### Step 5 — Poll for Status (Optional)

```
GET /api/v1/providers/onboarding/status/
Authorization: Token <onboarding_token>
```

The app can poll this to show status updates. Recommended: poll on app foreground resume and on FCM notification receipt. Do not poll more than once every 30 seconds.

### Step 6 — Full Login After Approval

```
POST /api/v1/providers/login/
```

Only works after staff approve. Returns a full-access Knox token.

---

## 4. API Endpoints Reference

All onboarding endpoints are under: `POST /api/v1/providers/`

Base URL prefix for onboarding: `/api/v1/providers/onboarding/`

---

### `POST /api/v1/providers/register/`

**Auth:** None (public)

**Request body:**

```json
{
  "first_name": "Ahmed",
  "last_name": "Hassan",
  "email": "ahmed@example.com",
  "phone": "01012345678",
  "password": "securepassword"
}
```

**Phone format:** Egyptian mobile number — `01XXXXXXXXX` or `+2001XXXXXXXXX`. Accepted prefixes: 010, 011, 012, 015.

**Success `201`:**

```json
{
  "message": "Registration successful. Use the onboarding_token to complete your profile...",
  "onboarding_token": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "next_step": "Submit your personal info at /api/v1/providers/onboarding/personal/"
}
```

---

### `PATCH /api/v1/providers/onboarding/personal/`

**Auth:** `Authorization: Token <onboarding_token>`

**Request body (all optional on each call, builds up progressively):**

```json
{
  "date_of_birth": "1995-06-15",
  "address": "12 Tahrir Square, Cairo",
  "region": 3,
  "category": 7,
  "hourly_rate": "150.00",
  "years_of_experience": 5,
  "bio": "Experienced electrician with 5 years in Cairo."
}
```

> `first_name`, `last_name`, `email`, `phone` are read directly from the registered account — do not send them here.

**Required for submission (not required to save a draft):**

- `date_of_birth` — must be 18+
- `address`
- `region`
- `category`
- `hourly_rate`

**Success `200`:** Returns the full `OnboardingStatus` object (see status endpoint below).

---

### `PATCH /api/v1/providers/onboarding/documents/`

**Auth:** `Authorization: Token <onboarding_token>`

**Request:** `multipart/form-data`

| Field                          | Required         | Accepted formats    | Max size                     |
| ------------------------------ | ---------------- | ------------------- | ---------------------------- |
| `nid_front`                    | Yes (for submit) | jpg, jpeg, png, pdf | Configurable (default 10 MB) |
| `nid_back`                     | Yes (for submit) | jpg, jpeg, png, pdf | Configurable (default 10 MB) |
| `police_clearance_certificate` | Yes (for submit) | jpg, jpeg, png, pdf | Configurable (default 10 MB) |
| `professional_certificate`     | No               | jpg, jpeg, png, pdf | Configurable (default 10 MB) |
| `profile_photo`                | No               | jpg, jpeg, png      | Configurable (default 10 MB) |

Each call replaces the uploaded files (no append). Documents can be re-uploaded as many times as needed while status is `draft` or `changes_required`.

**Success `200`:** Returns the full `OnboardingStatus` object.

---

### `POST /api/v1/providers/onboarding/submit/`

**Auth:** `Authorization: Token <onboarding_token>`

**Request body:** Empty `{}` or no body.

**Pre-submit check:** The API will reject with `400` and a `missing_fields` list if any required field is missing:

```json
{
  "missing_fields": ["date_of_birth", "nid_front"],
  "detail": "Please complete all required fields before submitting."
}
```

**Success `200`:**

```json
{
  "detail": "Application submitted successfully. We will review your documents and notify you of the decision.",
  "application": {
    "id": "uuid",
    "status": "pending",
    "ai_validation_status": "pending",
    ...
  }
}
```

---

### `GET /api/v1/providers/onboarding/status/`

**Auth:** `Authorization: Token <onboarding_token>`

**Success `200`:**

```json
{
  "id": "3f4e1a2b-...",
  "status": "pending",
  "ai_validation_status": "running",
  "ai_report_summary": null,
  "rejection_reason": "",
  "change_requests": "",
  "can_resubmit": false,
  "can_resubmit_after": null,
  "submitted_at": "2026-04-25T10:00:00Z",
  "updated_at": "2026-04-25T10:01:00Z"
}
```

When AI validation is done, `ai_report_summary` will contain:

```json
{
  "status": "passed",
  "issues": [],
  "overall_confidence": 0.92
}
```

---

### `POST /api/v1/providers/login/`

**Auth:** None (public)

**Request body:**

```json
{
  "email": "ahmed@example.com",
  "password": "securepassword"
}
```

**Success `200`:**

```json
{
  "provider": { ... provider profile object ... },
  "token": "xxxxxxxxxxxxxxxxxxxx"
}
```

**Failure states (all return `400`):**

- Invalid credentials
- Account is disabled
- `verification_status` is still `pending` → `"Your application is still under review. You will be notified once it is approved."`

---

### `POST /api/v1/providers/logout/`

**Auth:** `Authorization: Token <full_login_token>`

No body. Invalidates the current Knox token.

---

### `GET /api/v1/providers/me/`

**Auth:** `Authorization: Token <full_login_token>` (approved providers only)

Returns full provider profile.

---

### `PATCH /api/v1/providers/me/`

**Auth:** `Authorization: Token <full_login_token>`

Updatable fields:

```json
{
  "first_name": "Ahmed",
  "last_name": "Hassan",
  "phone": "01012345678",
  "profile_picture": "<file>",
  "address": "New address",
  "business_name": "Ahmed's Plumbing",
  "bio": "Updated bio",
  "hourly_rate": "200.00",
  "years_of_experience": 6,
  "is_available": true,
  "latitude": 30.0444,
  "longitude": 31.2357
}
```

> `latitude` and `longitude` must always be sent together or not at all.

---

### `PATCH /api/v1/providers/me/location/`

**Auth:** `Authorization: Token <full_login_token>`

Lightweight location ping (call every ~60 seconds while on an active job):

```json
{
  "latitude": 30.0444,
  "longitude": 31.2357
}
```

---

## 5. Onboarding Status State Machine

```
                    ┌──────────────────┐
                    │      DRAFT       │ ← Initial state (also reset from REJECTED)
                    └────────┬─────────┘
                             │ POST /submit/
                             ▼
                    ┌──────────────────┐
                    │     PENDING      │ ← AI running in background
                    └────────┬─────────┘
                             │ Staff picks up application
                             ▼
                    ┌──────────────────┐
                    │  UNDER_REVIEW    │ ← Staff is actively reviewing
                    └────────┬─────────┘
               ┌─────────────┼─────────────┐
               ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌────────────────────┐
        │ APPROVED │  │ REJECTED │  │  CHANGES_REQUIRED  │
        └──────────┘  └────┬─────┘  └────────┬───────────┘
                           │                  │ Provider updates &
                           │ After 30-day     │ re-submits
                           │ cooldown expires ▼
                           └────────→ DRAFT (resubmit)
```

| Status             | What the app should show                                    |
| ------------------ | ----------------------------------------------------------- |
| `draft`            | Form in progress, prompt to continue                        |
| `pending`          | "Under review" screen, show AI validation status            |
| `under_review`     | "Our team is reviewing your application"                    |
| `changes_required` | Show `change_requests` field, allow re-upload and re-submit |
| `approved`         | Prompt to log in with full access                           |
| `rejected`         | Show `rejection_reason`, show `can_resubmit_after` date     |

---

## 6. AI Validation Statuses

The `ai_validation_status` field on the status response tracks the background document check:

| Value     | Meaning                                   | Action in app                  |
| --------- | ----------------------------------------- | ------------------------------ |
| `pending` | Not yet started                           | —                              |
| `running` | AI is inspecting documents                | Show spinner/processing state  |
| `passed`  | All documents look good                   | No action needed               |
| `flagged` | Issues found — staff will review manually | No action needed from provider |
| `failed`  | Documents likely invalid                  | Staff will contact provider    |

> **Important:** `ai_validation_status` is informational only. The provider cannot and should not take action based on it — only the top-level `status` field drives the UX. A `flagged` AI result does not mean rejection; a human reviewer makes the final call.

The `ai_report_summary` object when available:

```json
{
  "status": "flagged",
  "issues": [
    "NID card appears expired",
    "Police clearance is older than 5 months"
  ],
  "overall_confidence": 0.61
}
```

---

## 7. Push Notifications (FCM)

All notifications are sent via FCM and also persisted in-app. The mobile app should handle both the FCM data payload and the in-app inbox.

Every FCM message includes a `type` field in the data payload for routing on the client side.

### Onboarding Notification Types

| `type` value                    | Trigger                    | Title                      | What to show                             |
| ------------------------------- | -------------------------- | -------------------------- | ---------------------------------------- |
| `onboarding_approved`           | Staff approves application | "Application Approved!"    | Congratulations screen, prompt to log in |
| `onboarding_rejected`           | Staff rejects application  | "Application Not Approved" | Show rejection reason and resubmit date  |
| `onboarding_changes_required`   | Staff requests changes     | "Changes Required"         | Show required changes, re-enable form    |
| `onboarding_resubmit_available` | 30-day cooldown expires    | "You Can Reapply Now"      | Prompt to reopen the application form    |

### FCM Data Payload Examples

**`onboarding_approved`**

```json
{
  "type": "onboarding_approved",
  "onboarding_id": "3f4e1a2b-..."
}
```

**`onboarding_rejected`**

```json
{
  "type": "onboarding_rejected",
  "onboarding_id": "3f4e1a2b-...",
  "rejection_reason": "NID card is expired.",
  "can_resubmit_after": "2026-05-25"
}
```

**`onboarding_changes_required`**

```json
{
  "type": "onboarding_changes_required",
  "onboarding_id": "3f4e1a2b-...",
  "change_requests": "Please upload a clearer photo of your NID back."
}
```

**`onboarding_resubmit_available`**

```json
{
  "type": "onboarding_resubmit_available"
}
```

### Handling Notifications in the Onboarding Screen

On any onboarding-related FCM notification, immediately call `GET /onboarding/status/` to refresh the application state — the data payload is a hint, not a source of truth.

---

## 8. Error Responses

### Common HTTP codes

| Code  | Reason                                                                                   |
| ----- | ---------------------------------------------------------------------------------------- |
| `400` | Validation error (see `detail` or field-level errors)                                    |
| `401` | Missing or invalid token                                                                 |
| `403` | Wrong token type (e.g. using `onboarding_token` on `/me/`) or application in wrong state |
| `404` | No onboarding application found yet                                                      |

### Blocked states

Calling a write endpoint (`/personal/`, `/documents/`, `/submit/`) when the application is in `pending`, `under_review`, `approved`, or `rejected` (within cooldown) returns `400`:

```json
{
  "detail": "Cannot update personal info while application status is 'pending'.",
  "status": "pending"
}
```

Calling with a non-provider user or an already-approved provider returns `403` with:

```json
{
  "detail": "Access restricted to providers awaiting onboarding approval..."
}
```

---

## 9. Rejection & Resubmission

When the application is rejected:

1. Provider receives FCM `onboarding_rejected` push.
2. `GET /onboarding/status/` returns `status: rejected`, `rejection_reason`, and `can_resubmit_after`.
3. The app should show a countdown / date until the provider can reapply (default cooldown: 30 days).
4. Once `can_resubmit` is `true` on the status response:
   - Call `PATCH /onboarding/personal/` with any data — this automatically resets the application to `DRAFT`.
   - Provider goes through the full form again and re-submits.

> The provider does NOT need to re-register. Their account and token are still valid.

---

## 10. Field Constraints

| Field                 | Constraint                                                    |
| --------------------- | ------------------------------------------------------------- |
| `phone`               | Egyptian mobile: `01[0125]XXXXXXXX` or `+2001[0125]XXXXXXXX`  |
| `password`            | Minimum 8 characters                                          |
| `date_of_birth`       | Provider must be 18 or older                                  |
| `hourly_rate`         | Decimal ≥ 0                                                   |
| `years_of_experience` | Integer ≥ 0                                                   |
| `latitude`            | −90 to 90                                                     |
| `longitude`           | −180 to 180                                                   |
| Document files        | jpg, jpeg, png, pdf only (profile photo: jpg, jpeg, png only) |
| Document file size    | Max configurable via admin (default 10 MB)                    |
