import logging

from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .choices import OnboardingStatus, ProviderVerificationStatus
from .models import Provider, ProviderOnboarding

# Setup logger
logger = logging.getLogger(__name__)


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    """Admin interface for Provider model"""

    list_display = (
        'email',
        'first_name',
        'last_name',
        'region',
        'verification_badge',
        'average_rating',
        'completion_rate_display',
        'is_available',
        'date_joined'
    )

    list_filter = (
        'verification_status',
        'is_available',
        'is_verified',
        'is_active',
        'region',
        'date_joined'
    )

    search_fields = (
        'email',
        'first_name',
        'last_name',
        'business_name',
        'phone'
    )

    readonly_fields = (
        'date_joined',
        'last_login',
        'updated_at',
        'total_earnings',
        'total_jobs',
        'completed_jobs',
        'average_rating',
        'total_reviews',
        'completion_rate_display'
    )

    filter_horizontal = ('categories',)

    fieldsets = (
        ('User Information', {
            'fields': (
                'email',
                'first_name',
                'last_name',
                'phone',
                'profile_picture'
            )
        }),
        ('Service Information', {
            'fields': ('categories', 'region')
        }),
        ('Business Information', {
            'fields': (
                'business_name',
                'bio',
                'years_of_experience',
                'hourly_rate'
            )
        }),
        ('Verification', {
            'fields': ('verification_status', 'id_document', 'certification')
        }),
        ('Financial', {
            'fields': ('total_earnings', 'available_balance')
        }),
        ('Availability', {
            'fields': ('is_available', 'service_radius')
        }),
        ('Location', {
            'fields': ('address', 'latitude', 'longitude')
        }),
        ('Statistics', {
            'fields': (
                'total_jobs',
                'completed_jobs',
                'completion_rate_display',
                'average_rating',
                'total_reviews'
            )
        }),
        ('Status', {
            'fields': ('is_active', 'is_verified')
        }),
        ('Timestamps', {
            'fields': ('date_joined', 'last_login', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = [
        'verify_providers',
        'reject_providers',
        'make_available',
        'make_unavailable'
    ]

    def get_queryset(self, request):
        """Optimize queries with select_related"""
        qs = super().get_queryset(request)
        return qs.select_related('region').prefetch_related('categories')

    def verification_badge(self, obj):
        """Display colored verification status badge"""
        colors = {
            ProviderVerificationStatus.PENDING: 'orange',
            ProviderVerificationStatus.VERIFIED: 'green',
            ProviderVerificationStatus.REJECTED: 'red'
        }
        color = colors.get(obj.verification_status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_verification_status_display()
        )
    verification_badge.short_description = 'Verification'

    def completion_rate_display(self, obj):
        """Display completion rate percentage"""
        return f"{obj.get_completion_rate()}%"
    completion_rate_display.short_description = 'Completion Rate'

    def verify_providers(self, request, queryset):
        """Verify selected providers"""
        updated = queryset.update(
            verification_status=ProviderVerificationStatus.VERIFIED,
            is_verified=True
        )
        logger.info(f"Admin {request.user} verified {updated} provider(s)")
        self.message_user(
            request,
            f'{updated} provider(s) verified successfully.',
            messages.SUCCESS
        )
    verify_providers.short_description = "Verify selected providers"

    def reject_providers(self, request, queryset):
        """Reject selected providers"""
        updated = queryset.update(
            verification_status=ProviderVerificationStatus.REJECTED,
            is_verified=False
        )
        logger.info(f"Admin {request.user} rejected {updated} provider(s)")
        self.message_user(
            request,
            f'{updated} provider(s) rejected.',
            messages.WARNING
        )
    reject_providers.short_description = "Reject selected providers"

    def make_available(self, request, queryset):
        """Mark providers as available"""
        updated = queryset.update(is_available=True)
        self.message_user(
            request,
            f'{updated} provider(s) marked as available.',
            messages.SUCCESS
        )
    make_available.short_description = "Mark as available"

    def make_unavailable(self, request, queryset):
        """Mark providers as unavailable"""
        updated = queryset.update(is_available=False)
        self.message_user(
            request,
            f'{updated} provider(s) marked as unavailable.',
            messages.WARNING
        )
    make_unavailable.short_description = "Mark as unavailable"


class ProviderOnboardingAdminForm(forms.ModelForm):
    """Custom form for onboarding admin with better widgets"""

    class Meta:
        model = ProviderOnboarding
        fields = '__all__'
        widgets = {
            'admin_notes': forms.Textarea(attrs={'rows': 3}),
            'rejection_reason': forms.Textarea(attrs={'rows': 3}),
            'change_requests': forms.Textarea(attrs={'rows': 3}),
            'bio': forms.Textarea(attrs={'rows': 4}),
        }


@admin.register(ProviderOnboarding)
class ProviderOnboardingAdmin(admin.ModelAdmin):
    """Admin interface for Provider Onboarding with FSM workflow"""

    form = ProviderOnboardingAdminForm

    list_display = (
        'get_full_name',
        'email',
        'category',
        'region',
        'status_badge',
        'age',
        'hourly_rate',
        'submitted_at',
    )

    list_filter = (
        'status',
        'category',
        'region',
        'submitted_at',
        'reviewed_at',
    )

    search_fields = (
        'first_name',
        'last_name',
        'email',
        'phone',
    )

    readonly_fields = (
        'id',
        'submitted_at',
        'reviewed_at',
        'approved_at',
        'rejected_at',
        'updated_at',
        'age',
        'provider_link',
        'document_preview',
    )

    fieldsets = (
        ('Application Status', {
            'fields': ('status', 'provider_link'),
            'classes': ('wide',),
        }),
        ('Personal Information', {
            'fields': (
                'first_name',
                'last_name',
                'email',
                'phone',
                'date_of_birth',
                'age',
                'profile_photo',
            )
        }),
        ('Location & Service', {
            'fields': (
                'address',
                'region',
                'category',
            )
        }),
        ('Professional Details', {
            'fields': (
                'hourly_rate',
                'years_of_experience',
                'bio',
            )
        }),
        ('Documents', {
            'fields': (
                'document_preview',
                'nid_front',
                'nid_back',
                'police_clearance_certificate',
                'professional_certificate',
            ),
            'classes': ('wide',),
        }),
        ('Admin Review', {
            'fields': (
                'reviewed_by',
                'admin_notes',
                'rejection_reason',
                'change_requests',
            ),
            'classes': ('wide',),
        }),
        ('Timestamps', {
            'fields': (
                'id',
                'submitted_at',
                'reviewed_at',
                'approved_at',
                'rejected_at',
                'updated_at',
            ),
            'classes': ('collapse',)
        }),
    )

    actions = [
        'action_move_to_review',
        'action_approve_applications',
        'action_reject_applications',
    ]

    def get_queryset(self, request):
        """Optimize queries with select_related and prefetch_related"""
        qs = super().get_queryset(request)
        return qs.select_related(
            'region',
            'category',
            'reviewed_by',
            'provider'
        )

    def status_badge(self, obj):
        """Display colored status badge"""
        colors = {
            OnboardingStatus.PENDING: '#FFA500',
            OnboardingStatus.UNDER_REVIEW: '#2196F3',
            OnboardingStatus.CHANGES_REQUIRED: '#FF9800',
            OnboardingStatus.APPROVED: '#4CAF50',
            OnboardingStatus.REJECTED: '#F44336',
        }
        color = colors.get(obj.status, '#757575')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 4px 12px; border-radius: 12px; font-weight: bold; '
            'font-size: 10px; text-transform: uppercase; '
            'letter-spacing: 0.5px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def provider_link(self, obj):
        """Link to created provider account"""
        if obj.provider:
            url = reverse(
                'admin:provider_provider_change',
                args=[obj.provider.pk]
            )
            return format_html(
                '<a href="{}" style="color: #4CAF50; font-weight: bold; '
                'text-decoration: none; padding: 8px 15px; '
                'background: #E8F5E9; border-radius: 4px; '
                'display: inline-block;">View Provider Account</a>',
                url
            )
        return format_html(
            '<span style="color: {}; font-style: italic;">{}</span>',
            '#999',
            'Not created yet'
        )
    provider_link.short_description = 'Provider Account'

    def document_preview(self, obj):
        """Preview uploaded documents with proper layout"""
        html_parts = [
            '<div style="display: grid; grid-template-columns: 1fr 1fr; '
            'gap: 15px; padding: 10px;">'
        ]

        # NID Front
        if obj.nid_front:
            html_parts.append(
                '<div style="border: 2px solid #e0e0e0; padding: 10px; '
                'border-radius: 8px;">'
                '<strong style="color: #666;">NID Front:</strong><br><br>'
                f'<img src="{obj.nid_front.url}" alt="NID Front" '
                'style="max-width: 100%; max-height: 200px; '
                'border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">'
                '</div>'
            )

        # NID Back
        if obj.nid_back:
            html_parts.append(
                '<div style="border: 2px solid #e0e0e0; padding: 10px; '
                'border-radius: 8px;">'
                '<strong style="color: #666;">NID Back:</strong><br><br>'
                f'<img src="{obj.nid_back.url}" alt="NID Back" '
                'style="max-width: 100%; max-height: 200px; '
                'border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">'
                '</div>'
            )

        # Police Clearance Certificate
        if obj.police_clearance_certificate:
            html_parts.append(
                '<div style="border: 2px solid #e0e0e0; padding: 15px; '
                'border-radius: 8px;">'
                '<strong style="color: #666;">Police Clearance:</strong>'
                '<br><br>'
                f'<a href="{obj.police_clearance_certificate.url}" '
                'target="_blank" rel="noopener noreferrer" '
                'style="color: #2196F3; text-decoration: none; '
                'font-size: 14px;">'
                'View Document'
                '</a>'
                '</div>'
            )

        # Professional Certificate
        if obj.professional_certificate:
            html_parts.append(
                '<div style="border: 2px solid #e0e0e0; padding: 15px; '
                'border-radius: 8px;">'
                '<strong style="color: #666;">Professional Certificate:'
                '</strong><br><br>'
                f'<a href="{obj.professional_certificate.url}" '
                'target="_blank" rel="noopener noreferrer" '
                'style="color: #2196F3; text-decoration: none; '
                'font-size: 14px;">'
                'View Document'
                '</a>'
                '</div>'
            )

        html_parts.append('</div>')
        return mark_safe(''.join(html_parts))
    document_preview.short_description = 'Document Preview'

    def action_move_to_review(self, request, queryset):
        """Move selected applications to under review"""
        success_count = 0
        error_count = 0

        for application in queryset:
            try:
                logger.info(
                    f"Attempting to move application {application.pk} "
                    f"(status: {application.status}) to review"
                )
                if application.can_review():
                    application.move_to_review(request.user)
                    success_count += 1
                    logger.info(
                        f"Successfully moved application {application.pk} to review"
                    )
                else:
                    error_count += 1
                    logger.warning(
                        f"Cannot move application {application.pk} "
                        f"from {application.status} to review"
                    )
            except Exception as e:
                error_count += 1
                logger.error(
                    f"Error moving application {application.pk} to review: {e}",
                    exc_info=True
                )
                self.message_user(
                    request,
                    f"Error reviewing {application.get_full_name()}: {str(e)}",
                    messages.ERROR
                )

        if success_count:
            self.message_user(
                request,
                f'{success_count} application(s) moved to under review.',
                messages.SUCCESS
            )
        if error_count:
            self.message_user(
                request,
                f'{error_count} application(s) could not be moved.',
                messages.WARNING
            )
    action_move_to_review.short_description = "Move to Under Review"

    def action_approve_applications(self, request, queryset):
        """Approve selected applications and create provider accounts"""
        success_count = 0
        error_count = 0

        for application in queryset:
            try:
                logger.info(
                    f"Attempting to approve application {application.pk} "
                    f"(status: {application.status})"
                )
                if application.can_approve():
                    provider = application.approve(request.user)
                    success_count += 1
                    logger.info(
                        f"Successfully approved application {application.pk}, "
                        f"created provider {provider.pk}"
                    )
                else:
                    error_count += 1
                    logger.warning(
                        f"Cannot approve application {application.pk} "
                        f"from {application.status}"
                    )
            except Exception as e:
                error_count += 1
                logger.error(
                    f"Error approving application {application.pk}: {e}",
                    exc_info=True
                )
                self.message_user(
                    request,
                    f"Error approving {application.get_full_name()}: {str(e)}",
                    messages.ERROR
                )

        if success_count:
            self.message_user(
                request,
                f'{success_count} application(s) approved! '
                'Provider accounts created.',
                messages.SUCCESS
            )
        if error_count:
            self.message_user(
                request,
                f'{error_count} application(s) could not be approved.',
                messages.WARNING
            )
    action_approve_applications.short_description = "Approve Applications"

    def action_reject_applications(self, request, queryset):
        """Reject selected applications"""
        success_count = 0
        error_count = 0

        for application in queryset:
            try:
                logger.info(
                    f"Attempting to reject application {application.pk} "
                    f"(status: {application.status})"
                )
                if application.can_reject():
                    reason = (
                        application.admin_notes or
                        "Application rejected by admin"
                    )
                    application.reject(request.user, reason)
                    success_count += 1
                    logger.info(
                        f"Successfully rejected application {application.pk}"
                    )
                else:
                    error_count += 1
                    logger.warning(
                        f"Cannot reject application {application.pk} "
                        f"from {application.status}"
                    )
            except Exception as e:
                error_count += 1
                logger.error(
                    f"Error rejecting application {application.pk}: {e}",
                    exc_info=True
                )
                self.message_user(
                    request,
                    f"Error rejecting {application.get_full_name()}: {str(e)}",
                    messages.ERROR
                )

        if success_count:
            self.message_user(
                request,
                f'{success_count} application(s) rejected. '
                'Ensure rejection reasons are documented.',
                messages.WARNING
            )
        if error_count:
            self.message_user(
                request,
                f'{error_count} application(s) could not be rejected.',
                messages.ERROR
            )
    action_reject_applications.short_description = "Reject Applications"

    def save_model(self, request, obj, form, change):
        """Handle FSM state transitions when manually changing status"""
        logger.info(
            f"save_model called: change={change}, "
            f"obj.pk={obj.pk}, obj.status={obj.status}"
        )

        # New object - just save
        if not change:
            logger.info(f"New application {obj.pk}, saving directly")
            super().save_model(request, obj, form, change)
            return

        # Get old object from database BEFORE any changes
        try:
            old_obj = ProviderOnboarding.objects.get(pk=obj.pk)
            old_status = old_obj.status
            logger.info(
                f"Loaded old object: old_status={old_status}, "
                f"new_status={obj.status}, "
                f"old_provider={'exists' if old_obj.provider else 'none'}"
            )
        except ProviderOnboarding.DoesNotExist:
            logger.error(f"Could not find old object with pk={obj.pk}")
            super().save_model(request, obj, form, change)
            return

        # Check for terminal state FIRST - prevent any changes
        if old_status in [OnboardingStatus.APPROVED, OnboardingStatus.REJECTED]:
            logger.warning(
                f"Attempt to change terminal state {old_status} "
                f"to {obj.status} for application {obj.pk}"
            )
            self.message_user(
                request,
                f'Cannot modify application in {old_obj.get_status_display()} state. '
                'Applications in APPROVED or REJECTED status cannot be changed.',
                messages.ERROR
            )
            # Restore ALL original values, not just status
            obj.status = old_status
            obj.reviewed_by = old_obj.reviewed_by
            obj.provider = old_obj.provider
            super().save_model(request, obj, form, change)
            return

        # No status change - allow other field updates
        if old_status == obj.status:
            logger.info("No status change, saving normally")
            super().save_model(request, obj, form, change)
            return

        logger.info(
            f"Processing state transition: {old_status} -> {obj.status}"
        )

        # Handle state transitions using the OLD status from database
        try:
            # Moving to under review
            if obj.status == OnboardingStatus.UNDER_REVIEW:
                if old_status not in [OnboardingStatus.PENDING, OnboardingStatus.CHANGES_REQUIRED]:
                    raise ValueError(
                        f"Cannot move to review from {old_obj.get_status_display()}"
                    )
                logger.info("Updating reviewed_by and reviewed_at")
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()

            # Approving
            elif obj.status == OnboardingStatus.APPROVED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot approve from {old_obj.get_status_display()}. "
                        "Application must be in UNDER_REVIEW status."
                    )
                if old_obj.provider:
                    logger.warning(
                        f"Provider already exists for application {obj.pk}, "
                        "skipping creation"
                    )
                    self.message_user(
                        request,
                        'Provider account already exists for this application.',
                        messages.WARNING
                    )
                else:
                    logger.info(
                        f"Calling approve() method for application {obj.pk}")
                    # Reset obj to old_obj and call approve on it to ensure clean state
                    old_obj.approve(request.user)
                    self.message_user(
                        request,
                        f'Provider account created for {old_obj.get_full_name()}!',
                        messages.SUCCESS
                    )
                    return

            # Rejecting
            elif obj.status == OnboardingStatus.REJECTED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot reject from {old_obj.get_status_display()}. "
                        "Application must be in UNDER_REVIEW status."
                    )
                logger.info("Setting rejection fields")
                obj.reviewed_by = request.user
                obj.rejected_at = timezone.now()
                if not obj.rejection_reason:
                    self.message_user(
                        request,
                        'Please add a rejection reason.',
                        messages.WARNING
                    )

            # Requesting changes
            elif obj.status == OnboardingStatus.CHANGES_REQUIRED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot request changes from {old_obj.get_status_display()}. "
                        "Application must be in UNDER_REVIEW status."
                    )
                logger.info("Setting change request fields")
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()
                if not obj.change_requests:
                    self.message_user(
                        request,
                        'Please specify what changes are required.',
                        messages.WARNING
                    )

            logger.info("Saving model after successful state transition")
            super().save_model(request, obj, form, change)

        except ValueError as e:
            logger.error(
                f"ValueError during state transition for {obj.pk}: {e}",
                exc_info=True
            )
            self.message_user(request, str(e), messages.ERROR)
            # Restore original status
            obj.status = old_status
            super().save_model(request, obj, form, change)
