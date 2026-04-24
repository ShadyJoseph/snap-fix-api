from rest_framework.permissions import BasePermission

from .choices import ProviderVerificationStatus


class IsAwaitingOnboarding(BasePermission):
    """
    Grants access only to authenticated providers whose application is still PENDING.

    Providers are created with is_active=True (so they can authenticate via Knox)
    but verification_status=PENDING (so they cannot access active-provider features).
    Once staff approve the application, verification_status becomes VERIFIED and this
    permission blocks further onboarding mutations.
    """

    message = (
        "Access restricted to providers awaiting onboarding approval. "
        "Already-approved or already-active providers cannot modify their application."
    )

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and hasattr(user, "provider")
            and user.provider.verification_status == ProviderVerificationStatus.PENDING
        )
