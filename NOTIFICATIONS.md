# Notification System

## Architecture

```
Booking view / Admin save_model  (FSM transition)
        │
        ▼
service.notify()                         ← always runs synchronously
        │
        ├─► Notification.objects.create()        DB inbox row (immediate, reliable)
        │                                        recipient can read it the moment
        │                                        the transition completes
        │
        └─► send_push_notification.delay()       Celery task queued in Redis
                    │                            If Redis is temporarily down,
                    │                            the error is caught and logged;
                    │                            the inbox row is already saved.
                    │
                    ▼ (async, in the background)
              FCM (Firebase Cloud Messaging)
                    │
                    ▼
              Device (Android / iOS / Web)
```

Periodic cleanup tasks run via Celery Beat:

```
Celery Beat scheduler
        │
        ├─► purge_stale_fcm_devices   (daily)   Deactivate FCM devices silent for 90+ days
        └─► purge_old_notifications   (weekly)  Delete read notifications older than 90 days
```

### Why two steps?

| Concern                 | DB write (sync)                   | FCM push (async via Celery)                            |
| ----------------------- | --------------------------------- | ------------------------------------------------------ |
| Inbox always up-to-date | Yes — even if Redis is down       | Not applicable                                         |
| Non-blocking            | No, but it is one INSERT          | Yes — Gunicorn worker is freed immediately             |
| Retries on failure      | Not needed (Postgres is reliable) | Yes — 3x with exponential back-off (60s → 120s → 240s) |
| What it powers          | In-app notification list          | OS notification tray                                   |

The DB write is the source of truth. The FCM push is best-effort delivery to the lock screen. If the Celery broker is unreachable, the inbox row is still saved and a warning is logged — the HTTP response never fails because of a missed push.

---

## Notification Types

| `type`                  | Recipient | Triggered when                                           | FSM transition            | Trigger path                                                |
| ----------------------- | --------- | -------------------------------------------------------- | ------------------------- | ----------------------------------------------------------- |
| `request_assigned`              | Customer  | Provider picks from pool **or** admin assigns            | `pending → assigned`              | View + Admin `save_model`                                   |
| `direct_booking_request`        | Provider  | Customer directly books this provider (from favorites **or** AI recommendation) | `pending → assigned` (at creation) | View (`DirectBookingView`, `RecommendedBookingView`)        |
| `quote_received`                | Customer  | Provider submits a price                                 | `assigned → quoted`               | View                                                        |
| `request_accepted`              | Customer  | Provider accepts directly (no quote)                     | `assigned → confirmed`            | View                                                        |
| `job_started`                   | Customer  | Provider begins work                                     | `confirmed → in_progress`         | View                                                        |
| `job_completed`                 | Customer  | Provider marks job done                                  | `in_progress → completed`         | View                                                        |
| `request_declined`              | Customer  | Provider turns down the assignment                       | `assigned → pending`              | View                                                        |
| `cancelled_by_provider`         | Customer  | Provider cancels the job                                 | `any → cancelled`                 | View                                                        |
| `quote_approved`                | Provider  | Customer approves the quoted price                       | `quoted → confirmed`              | View                                                        |
| `quote_rejected`                | Provider  | Customer rejects the quoted price                        | `quoted → pending`                | View (provider snapshot passed, sr.provider cleared by FSM) |
| `cancelled_by_customer`         | Provider  | Customer cancels the request (only if provider assigned) | `any → cancelled`                 | View (provider snapshot passed)                             |
| `payment_settled`               | Provider  | Job completed, earnings credited                         | `in_progress → completed`         | View                                                        |
| `onboarding_approved`           | Provider  | Staff approves the onboarding application                | `under_review → approved`         | Admin `save_model`                                          |
| `onboarding_rejected`           | Provider  | Staff rejects the application                            | `under_review → rejected`         | Admin `save_model`                                          |
| `onboarding_changes_required`   | Provider  | Staff requests corrections before approval               | `under_review → changes_required` | Admin `save_model`                                          |
| `onboarding_resubmit_available` | Provider  | 30-day (configurable) rejection cooldown has expired     | —                                 | Celery Beat daily task                                      |

---

## Inbox API

All endpoints require `Authorization: Token <knox_token>`.

### List notifications

```
GET /api/v1/notifications/
GET /api/v1/notifications/?unread=true
```

Response (paginated array):

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "quote_received",
    "title": "New Quote",
    "body": "You received a quote of 500.00 for «Fix AC». Tap to review.",
    "data": { "service_request_id": "a1b2c3d4-..." },
    "is_read": false,
    "created_at": "2026-04-11T10:00:00Z"
  }
]
```

### Unread badge count

```
GET /api/v1/notifications/unread-count/
```

```json
{ "unread_count": 3 }
```

### Mark one as read

```
POST /api/v1/notifications/<id>/read/
```

### Mark all as read

```
POST /api/v1/notifications/read-all/
```

```json
{ "marked_read": 3 }
```

---

## Device Token API

### Register device token

```
POST /api/v1/notifications/devices/register/
{
  "registration_id": "<fcm_token>",
  "type": "android"   // or "ios" or "web"
}
```

Call this on every app launch — the FCM token can rotate. The call is idempotent (safe to repeat with the same token).

**Constraints:**

- Rate-limited to **10 registration attempts per hour** per user.
- A user may have at most **5 active devices** simultaneously. Re-registering an existing token does not count against the cap. To register a 6th device, first delete an existing one.
- Token must be **50-512 characters**, containing only `[A-Za-z0-9\-_:]`. Tokens outside this range are rejected immediately (before reaching Firebase).

**Responses:**

- `201 Created` — new device registered
- `200 OK` — existing token refreshed (idempotent)
- `400 Bad Request` — invalid token format or device cap reached
- `429 Too Many Requests` — rate limit exceeded

### Unregister device token

```
DELETE /api/v1/notifications/devices/<registration_id>/
```

Call this on logout so the user stops receiving pushes on that device its okay not to logout so the user keep notified.

The path parameter is validated using the same format rules as registration (`[A-Za-z0-9\-_:]`, max 512 chars). Malformed tokens return `400 Bad Request` immediately.

---

## Push Notification Payload

Every push has two parts: a `notification` block (rendered by the OS) and a `data` block (available in the app even when backgrounded or killed):

```json
{
  "notification": {
    "title": "New Quote",
    "body": "You received a quote of 500.00 for «Fix AC». Tap to review."
  },
  "data": {
    "type": "quote_received",
    "service_request_id": "a1b2c3d4-..."
  }
}
```

`data.type` tells the app which screen to navigate to without an extra API call. `data.service_request_id` tells it which record to load.

> **Note:** All values in `data` are coerced to strings before sending (FCM requirement). Parse numbers/booleans on the mobile side.

---

## Celery Task Details

### `send_push_notification`

```
Task:        apps.notifications.tasks.send_push_notification
Queue:       default
Retries:     3 (4 total attempts)
Retry schedule: 60s → 120s → 240s (exponential back-off)
acks_late:   True  (re-queued if worker dies mid-execution)
reject_on_worker_lost: True
```

Behaviour:

- Skips silently if the user has no active FCM devices.
- Retries on any Firebase exception.
- After 4 failures the task is marked failed (visible in Flower / Celery logs).
- If the broker (Redis) is unavailable when `notify()` is called, the push is skipped with a warning log — the inbox DB row is still saved.

### `purge_stale_fcm_devices` (Beat, daily at 03:00 UTC)

Deactivates FCM device records whose `date_created` is older than 90 days and are still marked `active=True`. These are devices that went silent without a Firebase error (e.g. app uninstalled without logging out). `FCM_DJANGO_SETTINGS.DELETE_INACTIVE_DEVICES` handles removal on Firebase send failure; this task covers the silent-dropout case.

### `purge_old_notifications` (Beat, Sundays at 04:00 UTC)

Deletes `Notification` rows that are both `is_read=True` and `created_at` older than 90 days. Unread notifications are never deleted automatically.

---

## Mobile Integration Guide

### Step 1 — Firebase one-time setup

1. Firebase Console → Project Settings → Your Apps → download:
   - Android: `google-services.json` → place in `android/app/`
   - iOS: `GoogleService-Info.plist` → place in `ios/`
2. Follow the [React Native Firebase installation guide](https://rnfirebase.io/) for your platform.

### Step 2 — Get the FCM token

```js
// React Native
import messaging from "@react-native-firebase/messaging";

const token = await messaging().getToken();
```

### Step 3 — Register the token with the backend

Call this right after login **and** on every app launch (token can change between launches):

```http
POST /api/v1/notifications/devices/register/
Authorization: Token <knox_token>
Content-Type: application/json

{
  "registration_id": "<token_from_step_2>",
  "type": "android"
}
```

Handle token rotation:

```js
messaging().onTokenRefresh(async (newToken) => {
  await api.post("/notifications/devices/register/", {
    registration_id: newToken,
    type: "android",
  });
});
```

### Step 4 — Listen for incoming pushes

**App in foreground** — Firebase fires a foreground message handler. Use it to refresh the inbox and update the badge:

```js
import messaging from "@react-native-firebase/messaging";

messaging().onMessage(async (remoteMessage) => {
  const { type, service_request_id } = remoteMessage.data;
  // Refresh notification list, update badge, show in-app toast.
  navigateIfNeeded(type, service_request_id);
});
```

**App in background or killed** — The OS renders the `notification` block in the tray automatically. When the user taps it, `data.type` is immediately available for deep-linking without an API call:

```js
// App in background, user taps the notification:
messaging().onNotificationOpenedApp((remoteMessage) => {
  const { type, service_request_id } = remoteMessage.data;
  navigate(type, service_request_id);
});

// App was killed, re-launched by tapping the notification:
messaging()
  .getInitialNotification()
  .then((remoteMessage) => {
    if (remoteMessage) {
      const { type, service_request_id } = remoteMessage.data;
      navigate(type, service_request_id);
    }
  });
```

### Step 5 — Deep-link routing

Use `data.type` from the push payload directly — it is identical to the `type` stored in the inbox and requires no extra API call.

| `type`                  | Navigate to                                     |
| ----------------------- | ----------------------------------------------- |
| `request_assigned`      | Request detail screen                           |
| `direct_booking_request` | Incoming jobs screen → request detail (provider was personally chosen — direct or recommended) |
| `quote_received`        | Request detail → Quote review section           |
| `request_accepted`      | Request detail screen                           |
| `job_started`           | Request detail → In-progress view               |
| `job_completed`         | Request detail → Leave review CTA               |
| `request_declined`      | Request list (request is back in the open pool) |
| `cancelled_by_provider` | Request detail → Cancelled state                |
| `quote_approved`        | Job detail screen (provider side)               |
| `quote_rejected`        | Job list (provider side)                        |
| `cancelled_by_customer` | Job list (provider side)                        |
| `payment_settled`       | Earnings screen                                 |

### Step 6 — Logout

Deregister the token so the user stops receiving pushes after signing out:

```http
DELETE /api/v1/notifications/devices/<registration_id>/
Authorization: Token <knox_token>
```

### Step 7 — Inbox polling

Fetch `GET /api/v1/notifications/` on app open and after each incoming push to keep the list fresh. Use `GET /api/v1/notifications/unread-count/` to drive the badge number on the tab bar icon.

---

## Environment Variables

| Variable                              | Where to set                              | What it does                                               |
| ------------------------------------- | ----------------------------------------- | ---------------------------------------------------------- |
| `GOOGLE_APPLICATION_CREDENTIALS`      | Local `.env` / docker-compose secrets     | Path to the Firebase service-account JSON file (local dev) |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | Railway → Variables                       | Full JSON content of the service-account file (production) |
| `REDIS_URL`                           | Set automatically by Railway Redis plugin | Celery broker + result backend                             |
| `ANTHROPIC_API_KEY`                   | Railway → Variables / `.env`              | Anthropic Claude Haiku — AI document validation + provider recommendations |
| `OPENAI_API_KEY`                      | Railway → Variables / `.env`              | OpenAI GPT-4o-mini — AI document validation + provider recommendations     |
| `GROQ_API_KEY`                        | Railway → Variables / `.env`              | Groq Llama — AI document validation + provider recommendations             |
| `GEMINI_API_KEY`                      | Railway → Variables / `.env`              | Google Gemini Flash — AI document validation + provider recommendations     |

**Production startup behaviour:** If neither credential variable is set, or if Firebase initialization fails for any reason (e.g. malformed JSON, invalid key), the app raises at startup and refuses to start when `DEBUG=False`. In development (`DEBUG=True`) it logs a warning and continues — push notifications will not be delivered but the inbox API works normally.

---

## Firebase Credential Handling (Production)

In production the service-account JSON is passed as the environment variable `GOOGLE_APPLICATION_CREDENTIALS_JSON`. At startup (`NotificationsConfig.ready()`):

1. The JSON string is written to a temporary file.
2. `firebase_admin.initialize_app()` is called with that file path.
3. The temporary file is **immediately deleted** in a `finally` block — it never persists on disk beyond the initialisation call.

This avoids leaving credential material in `/tmp` between container restarts.
