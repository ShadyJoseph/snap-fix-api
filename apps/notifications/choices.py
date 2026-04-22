from django.db import models


class NotificationType(models.TextChoices):
    # ── Customer-facing ───────────────────────────────────────────
    REQUEST_ASSIGNED = "request_assigned", "Request Assigned"
    QUOTE_RECEIVED = "quote_received", "Quote Received"
    REQUEST_ACCEPTED = "request_accepted", "Request Accepted"
    JOB_STARTED = "job_started", "Job Started"
    JOB_COMPLETED = "job_completed", "Job Completed"
    REQUEST_DECLINED = "request_declined", "Request Declined"
    CANCELLED_BY_PROVIDER = "cancelled_by_provider", "Cancelled by Provider"

    # ── Provider-facing ───────────────────────────────────────────
    QUOTE_APPROVED = "quote_approved", "Quote Approved"
    QUOTE_REJECTED = "quote_rejected", "Quote Rejected"
    CANCELLED_BY_CUSTOMER = "cancelled_by_customer", "Cancelled by Customer"
    PAYMENT_SETTLED = "payment_settled", "Payment Settled"
