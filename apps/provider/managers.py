from django.db import models

from .choices import OnboardingStatus


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
