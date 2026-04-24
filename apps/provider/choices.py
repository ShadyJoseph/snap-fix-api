from django.db import models


class ProviderVerificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    REJECTED = "rejected", "Rejected"


class OnboardingStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Pending Review"
    UNDER_REVIEW = "under_review", "Under Review"
    CHANGES_REQUIRED = "changes_required", "Changes Required"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AIValidationStatus(models.TextChoices):
    PENDING = "pending", "Pending Validation"
    RUNNING = "running", "Running"
    PASSED = "passed", "Passed"
    FLAGGED = "flagged", "Flagged — Needs Review"
    FAILED = "failed", "Failed"
