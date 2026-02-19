import logging

from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .choices import OnboardingStatus, ProviderVerificationStatus
from .models import Provider, ProviderOnboarding

logger = logging.getLogger(__name__)


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    """Admin interface for Provider model."""

    list_display = (
        'email',
        'first_name',
        'last_name',
        'region',
        'verification_badge',
        'average_rating',
        'completion_rate_display',
        'is_available',
        'date_joined',
    )

    list_filter = (
        'verification_status',
        'is_available',
        'is_verified',
        'is_active',
        'region',
        'date_joined',
    )

    search_fields = ('email', 'first_name', 'last_name',
                     'business_name', 'phone')

    readonly_fields = (
        'date_joined',
        'last_login',
        'updated_at',
        'total_earnings',
        'total_jobs',
        'completed_jobs',
        'average_rating',
        'total_reviews',
        'completion_rate_display',
    )

    filter_horizontal = ('categories',)

    fieldsets = (
        ('User Information', {
            'fields': ('email', 'first_name', 'last_name', 'phone', 'profile_picture'),
        }),
        ('Service Information', {
            'fields': ('categories', 'region'),
        }),
        ('Business Information', {
            'fields': ('business_name', 'bio', 'years_of_experience', 'hourly_rate'),
        }),
        ('Verification', {
            'fields': ('verification_status', 'id_document', 'certification'),
        }),
        ('Financial', {
            'fields': ('total_earnings', 'available_balance'),
        }),
        ('Availability', {
            'fields': ('is_available', 'service_radius'),
        }),
        ('Location', {
            'fields': ('address', 'latitude', 'longitude'),
        }),
        ('Statistics', {
            'fields': (
                'total_jobs', 'completed_jobs', 'completion_rate_display',
                'average_rating', 'total_reviews',
            ),
        }),
        ('Status', {
            'fields': ('is_active', 'is_verified'),
        }),
        ('Timestamps', {
            'fields': ('date_joined', 'last_login', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    actions = ['verify_providers', 'reject_providers',
               'make_available', 'make_unavailable']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('region').prefetch_related('categories')

    @admin.display(description='Verification')
    def verification_badge(self, obj):
        colors = {
            ProviderVerificationStatus.PENDING: 'orange',
            ProviderVerificationStatus.VERIFIED: 'green',
            ProviderVerificationStatus.REJECTED: 'red',
        }
        color = colors.get(obj.verification_status, 'gray')
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            color,
            obj.get_verification_status_display(),
        )

    @admin.display(description='Completion Rate')
    def completion_rate_display(self, obj):
        return f"{obj.get_completion_rate()}%"

    @admin.action(description="Verify selected providers")
    def verify_providers(self, request, queryset):
        updated = queryset.update(
            verification_status=ProviderVerificationStatus.VERIFIED,
            is_verified=True,
        )
        logger.info("Admin %s verified %d provider(s)", request.user, updated)
        self.message_user(
            request, f"{updated} provider(s) verified.", messages.SUCCESS)

    @admin.action(description="Reject selected providers")
    def reject_providers(self, request, queryset):
        updated = queryset.update(
            verification_status=ProviderVerificationStatus.REJECTED,
            is_verified=False,
        )
        logger.info("Admin %s rejected %d provider(s)", request.user, updated)
        self.message_user(
            request, f"{updated} provider(s) rejected.", messages.WARNING)

    @admin.action(description="Mark as available")
    def make_available(self, request, queryset):
        updated = queryset.update(is_available=True)
        self.message_user(
            request, f"{updated} provider(s) marked as available.", messages.SUCCESS)

    @admin.action(description="Mark as unavailable")
    def make_unavailable(self, request, queryset):
        updated = queryset.update(is_available=False)
        self.message_user(
            request, f"{updated} provider(s) marked as unavailable.", messages.WARNING)


class ProviderOnboardingAdminForm(forms.ModelForm):
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
    """Admin interface for Provider Onboarding with FSM workflow."""

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

    list_filter = ('status', 'category', 'region',
                   'submitted_at', 'reviewed_at')

    search_fields = ('first_name', 'last_name', 'email', 'phone')

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
                'first_name', 'last_name', 'email', 'phone',
                'date_of_birth', 'age', 'profile_photo',
            ),
        }),
        ('Location & Service', {
            'fields': ('address', 'region', 'category'),
        }),
        ('Professional Details', {
            'fields': ('hourly_rate', 'years_of_experience', 'bio'),
        }),
        ('Documents', {
            'fields': (
                'document_preview',
                'nid_front', 'nid_back',
                'police_clearance_certificate', 'professional_certificate',
            ),
            'classes': ('wide',),
        }),
        ('Admin Review', {
            'fields': ('reviewed_by', 'admin_notes', 'rejection_reason', 'change_requests'),
            'classes': ('wide',),
        }),
        ('Timestamps', {
            'fields': (
                'id', 'submitted_at', 'reviewed_at',
                'approved_at', 'rejected_at', 'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'action_move_to_review',
        'action_approve_applications',
        'action_reject_applications',
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'region', 'category', 'reviewed_by', 'provider'
        )

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            OnboardingStatus.PENDING: '#FFA500',
            OnboardingStatus.UNDER_REVIEW: '#2196F3',
            OnboardingStatus.CHANGES_REQUIRED: '#FF9800',
            OnboardingStatus.APPROVED: '#4CAF50',
            OnboardingStatus.REJECTED: '#F44336',
        }
        color = colors.get(obj.status, '#757575')
        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;'
            'border-radius:10px;font-weight:bold;font-size:10px;'
            'text-transform:uppercase;letter-spacing:0.5px">{}</span>',
            color,
            obj.get_status_display(),
        )

    @admin.display(description='Provider Account')
    def provider_link(self, obj):
        if not obj.pk:
            return '—'
        if obj.provider_id:
            url = reverse('admin:provider_provider_change',
                          args=[obj.provider_id])
            return format_html(
                '<a href="{}" style="color:#4CAF50;font-weight:bold;'
                'text-decoration:none;padding:6px 12px;background:#E8F5E9;'
                'border-radius:4px;display:inline-block">View Provider Account</a>',
                url,
            )
        return mark_safe('<span style="color:#999;font-style:italic">Not created yet</span>')

    @admin.display(description='Document Preview')
    def document_preview(self, obj):
        parts = [
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;padding:10px">']

        def _img_card(label, file_field):
            return (
                f'<div style="border:2px solid #e0e0e0;padding:10px;border-radius:8px">'
                f'<strong style="color:#666">{label}:</strong><br><br>'
                f'<img src="{file_field.url}" alt="{label}" '
                f'style="max-width:100%;max-height:200px;border-radius:4px;'
                f'box-shadow:0 2px 4px rgba(0,0,0,.1)"></div>'
            )

        def _link_card(label, file_field):
            return (
                f'<div style="border:2px solid #e0e0e0;padding:15px;border-radius:8px">'
                f'<strong style="color:#666">{label}:</strong><br><br>'
                f'<a href="{file_field.url}" target="_blank" rel="noopener noreferrer" '
                f'style="color:#2196F3;text-decoration:none;font-size:14px">View Document</a></div>'
            )

        if obj.nid_front:
            parts.append(_img_card('NID Front', obj.nid_front))
        if obj.nid_back:
            parts.append(_img_card('NID Back', obj.nid_back))
        if obj.police_clearance_certificate:
            parts.append(_link_card('Police Clearance',
                         obj.police_clearance_certificate))
        if obj.professional_certificate:
            parts.append(_link_card('Professional Certificate',
                         obj.professional_certificate))

        parts.append('</div>')
        return mark_safe(''.join(parts))

    # Admin actions

    @admin.action(description="Move to Under Review")
    def action_move_to_review(self, request, queryset):
        success_count = skip_count = 0
        for application in queryset:
            if not application.can_review():
                skip_count += 1
                continue
            try:
                application.move_to_review(request.user)
                success_count += 1
            except Exception as exc:
                logger.error("Error moving application %s to review: %s",
                             application.pk, exc, exc_info=True)
                self.message_user(
                    request,
                    f"Error reviewing {application.get_full_name()}: {exc}",
                    messages.ERROR,
                )

        if success_count:
            self.message_user(
                request, f"{success_count} application(s) moved to under review.", messages.SUCCESS)
        if skip_count:
            self.message_user(
                request, f"{skip_count} application(s) skipped (wrong status).", messages.WARNING)

    @admin.action(description="Approve Applications")
    def action_approve_applications(self, request, queryset):
        success_count = skip_count = 0
        for application in queryset:
            if not application.can_approve():
                skip_count += 1
                continue
            try:
                application.approve(request.user)
                success_count += 1
            except Exception as exc:
                logger.error("Error approving application %s: %s",
                             application.pk, exc, exc_info=True)
                self.message_user(
                    request,
                    f"Error approving {application.get_full_name()}: {exc}",
                    messages.ERROR,
                )

        if success_count:
            self.message_user(
                request,
                f"{success_count} application(s) approved. Provider accounts created.",
                messages.SUCCESS,
            )
        if skip_count:
            self.message_user(
                request, f"{skip_count} application(s) skipped (wrong status).", messages.WARNING)

    @admin.action(description="Reject Applications")
    def action_reject_applications(self, request, queryset):
        success_count = skip_count = 0
        for application in queryset:
            if not application.can_reject():
                skip_count += 1
                continue
            try:
                reason = application.admin_notes or "Application rejected by admin"
                application.reject(request.user, reason)
                success_count += 1
            except Exception as exc:
                logger.error("Error rejecting application %s: %s",
                             application.pk, exc, exc_info=True)
                self.message_user(
                    request,
                    f"Error rejecting {application.get_full_name()}: {exc}",
                    messages.ERROR,
                )

        if success_count:
            self.message_user(
                request,
                f"{success_count} application(s) rejected. Ensure rejection reasons are documented.",
                messages.WARNING,
            )
        if skip_count:
            self.message_user(
                request, f"{skip_count} application(s) skipped (wrong status).", messages.WARNING)

    # Save model — FSM-aware status transitions

    def save_model(self, request, obj, form, change):
        """
        Intercepts manual status changes in the admin form and enforces
        FSM rules. All state-specific side effects are handled here.
        """
        if not change:
            super().save_model(request, obj, form, change)
            return

        try:
            old = ProviderOnboarding.objects.get(pk=obj.pk)
        except ProviderOnboarding.DoesNotExist:
            super().save_model(request, obj, form, change)
            return

        old_status = old.status

        # Block edits on terminal states
        if old_status in (OnboardingStatus.APPROVED, OnboardingStatus.REJECTED):
            self.message_user(
                request,
                f"Cannot modify an application in {old.get_status_display()} state.",
                messages.ERROR,
            )
            obj.status = old_status
            obj.reviewed_by = old.reviewed_by
            obj.provider = old.provider
            super().save_model(request, obj, form, change)
            return

        # No status change — allow field-only updates
        if old_status == obj.status:
            super().save_model(request, obj, form, change)
            return

        # Validate and enrich transitions
        try:
            if obj.status == OnboardingStatus.UNDER_REVIEW:
                if old_status not in (OnboardingStatus.PENDING, OnboardingStatus.CHANGES_REQUIRED):
                    raise ValueError(
                        f"Cannot move to Under Review from {old.get_status_display()}."
                    )
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()

            elif obj.status == OnboardingStatus.APPROVED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot approve from {old.get_status_display()}. "
                        "Application must be Under Review first."
                    )
                if old.provider:
                    self.message_user(
                        request, "Provider account already exists.", messages.WARNING
                    )
                else:
                    old.approve(request.user)
                    self.message_user(
                        request,
                        f"Provider account created for {old.get_full_name()}.",
                        messages.SUCCESS,
                    )
                    return  # approve() handles the save

            elif obj.status == OnboardingStatus.REJECTED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot reject from {old.get_status_display()}. "
                        "Application must be Under Review first."
                    )
                obj.reviewed_by = request.user
                obj.rejected_at = timezone.now()
                if not obj.rejection_reason:
                    self.message_user(
                        request, "Please add a rejection reason.", messages.WARNING
                    )

            elif obj.status == OnboardingStatus.CHANGES_REQUIRED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot request changes from {old.get_status_display()}. "
                        "Application must be Under Review first."
                    )
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()
                if not obj.change_requests:
                    self.message_user(
                        request, "Please specify the required changes.", messages.WARNING
                    )

            super().save_model(request, obj, form, change)

        except ValueError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            obj.status = old_status
            super().save_model(request, obj, form, change)
