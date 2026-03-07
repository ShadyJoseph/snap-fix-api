from __future__ import annotations

from django.db import models

from apps.user.managers import UserManager

from .choices import OnboardingStatus


class ProviderManager(UserManager):
    pass


class ProviderOnboardingManager(models.Manager):

    def pending(self):
        return self.filter(status=OnboardingStatus.PENDING)

    def under_review(self):
        return self.filter(status=OnboardingStatus.UNDER_REVIEW)

    def approved(self):
        return self.filter(status=OnboardingStatus.APPROVED)

    def rejected(self):
        return self.filter(status=OnboardingStatus.REJECTED)

    def changes_required(self):
        return self.filter(status=OnboardingStatus.CHANGES_REQUIRED)
