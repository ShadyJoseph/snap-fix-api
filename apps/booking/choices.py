from django.db import models


def max_length(choices_class):
    return max(len(value) for value, _ in choices_class.choices)


class ServiceRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ASSIGNED = "assigned", "Assigned"
    QUOTED = "quoted", "Quoted"
    CONFIRMED = "confirmed", "Confirmed"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class PaymentMethod(models.TextChoices):
    """
    How the customer pays the NON-wallet portion of the bill.

    CASH  — provider collects cash in person; platform never touches the money.
    CARD  — Stripe charges the card for the card portion.
    WALLET— entire amount comes from the wallet (wallet_amount == final_price).

    wallet_amount on the ServiceRequest holds how much is deducted from the wallet.
    If wallet_amount < final_price the gap is covered by CASH or CARD.
    """

    CASH = "cash", "Cash"
    CARD = "card", "Card (Stripe)"
    WALLET = "wallet", "Wallet"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"


class CancelledBy(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    PROVIDER = "provider", "Provider"
    ADMIN = "admin", "Admin"


class BookingMode(models.TextChoices):
    BROADCAST = "broadcast", "Broadcast to All Providers"
    DIRECT = "direct", "Direct (Favorites)"
    RECOMMENDED = "recommended", "AI Recommended"


class AIRecommendationOutcome(models.TextChoices):
    SUCCESS = "success", "Success"
    FALLBACK = "fallback", "Fallback (generic reasons)"
    BYPASSED = "bypassed", "Bypassed (flag off)"
    ERROR = "error", "Error"
