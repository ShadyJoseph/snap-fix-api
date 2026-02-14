from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .choices import OnboardingStatus, ProviderVerificationStatus
from .models import Provider, ProviderOnboarding


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = (
        'email',
        'first_name',
        'last_name',
        'region',
        'verification_badge',
        'average_rating',
        'completion_rate',
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

    def verification_badge(self, obj):
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
    verification_badge.short_description = 'Verification Status'

    def completion_rate(self, obj):
        return f"{obj.get_completion_rate()}%"
    completion_rate.short_description = 'Completion Rate'

    def completion_rate_display(self, obj):
        return f"{obj.get_completion_rate()}%"
    completion_rate_display.short_description = 'Completion Rate'

    def verify_providers(self, request, queryset):
        updated = queryset.update(
            verification_status=ProviderVerificationStatus.VERIFIED,
            is_verified=True
        )
        self.message_user(
            request,
            f'{updated} provider(s) verified successfully.'
        )
    verify_providers.short_description = "Verify selected providers"

    def reject_providers(self, request, queryset):
        updated = queryset.update(
            verification_status=ProviderVerificationStatus.REJECTED,
            is_verified=False
        )
        self.message_user(request, f'{updated} provider(s) rejected.')
    reject_providers.short_description = "Reject selected providers"

    def make_available(self, request, queryset):
        updated = queryset.update(is_available=True)
        self.message_user(
            request,
            f'{updated} provider(s) marked as available.'
        )
    make_available.short_description = "Mark as available"

    def make_unavailable(self, request, queryset):
        updated = queryset.update(is_available=False)
        self.message_user(
            request,
            f'{updated} provider(s) marked as unavailable.'
        )
    make_unavailable.short_description = "Mark as unavailable"


class ProviderOnboardingAdminForm(forms.ModelForm):
    """Custom form for onboarding admin"""

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
            'classes': ('collapse',),
        }),
    )

    actions = [
        'action_move_to_review',
        'action_approve_applications',
        'action_reject_applications',
    ]

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
            '<span style="background-color: {}; color: white; padding: 4px 12px; '
            'border-radius: 12px; font-weight: bold; font-size: 10px; '
            'text-transform: uppercase; letter-spacing: 0.5px;">{}</span>',
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
            '<span style="color: #999; font-style: italic;">'
            'Not created yet</span>'
        )
    provider_link.short_description = 'Provider Account'

    def document_preview(self, obj):
        """Preview uploaded documents"""
        html_parts = [
            '<div style="display: grid; grid-template-columns: 1fr 1fr; '
            'gap: 15px; padding: 10px;">'
        ]

        if obj.nid_front:
            html_parts.append(
                '<div style="border: 2px solid #e0e0e0; padding: 10px; '
                'border-radius: 8px;">'
                '<strong style="color: #666;">NID Front:</strong><br><br>'
                f'<img src="{obj.nid_front.url}" '
                'style="max-width: 100%; max-height: 200px; '
                'border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">'
                '</div>'
            )

        if obj.nid_back:
            html_parts.append(
                '<div style="border: 2px solid #e0e0e0; padding: 10px; '
                'border-radius: 8px;">'
                '<strong style="color: #666;">NID Back:</strong><br><br>'
                f'<img src="{obj.nid_back.url}" '
                'style="max-width: 100%; max-height: 200px; '
                'border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">'
                '</div>'
            )

        if obj.police_clearance_certificate:
            html_parts.append(
                '<div style="border: 2px solid #e0e0e0; padding: 15px; '
                'border-radius: 8px;">'
                '<strong style="color: #666;">Police Clearance:</strong><br><br>'
                f'<a href="{obj.police_clearance_certificate.url}" '
                'target="_blank" '
                'style="color: #2196F3; text-decoration: none; '
                'font-size: 14px;">'
                'View Document'
                '</a>'
                '</div>'
            )

        if obj.professional_certificate:
            html_parts.append(
                '<div style="border: 2px solid #e0e0e0; padding: 15px; '
                'border-radius: 8px;">'
                '<strong style="color: #666;">'
                'Professional Certificate:</strong><br><br>'
                f'<a href="{obj.professional_certificate.url}" '
                'target="_blank" '
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
                if application.can_review():
                    application.move_to_review(request.user)
                    success_count += 1
                else:
                    error_count += 1
            except Exception:
                error_count += 1

        if success_count:
            self.message_user(
                request,
                f'{success_count} application(s) moved to under review.',
                level=messages.SUCCESS
            )
        if error_count:
            self.message_user(
                request,
                f'{error_count} application(s) could not be reviewed.',
                level=messages.WARNING
            )
    action_move_to_review.short_description = "Move to Under Review"

    def action_approve_applications(self, request, queryset):
        """Approve selected applications"""
        success_count = 0
        error_count = 0

        for application in queryset:
            try:
                if application.can_approve():
                    application.approve(request.user)
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                error_count += 1
                self.message_user(
                    request,
                    f"Error approving {application.get_full_name()}: {str(e)}",
                    level=messages.ERROR
                )

        if success_count:
            self.message_user(
                request,
                f'{success_count} application(s) approved! '
                'Provider accounts created.',
                level=messages.SUCCESS
            )
        if error_count:
            self.message_user(
                request,
                f'{error_count} application(s) could not be approved.',
                level=messages.WARNING
            )
    action_approve_applications.short_description = "Approve Applications"

    def action_reject_applications(self, request, queryset):
        """Reject selected applications"""
        count = 0
        for application in queryset:
            try:
                if application.can_reject():
                    reason = application.admin_notes or "Application rejected"
                    application.reject(request.user, reason)
                    count += 1
            except Exception:
                pass

        self.message_user(
            request,
            f'{count} application(s) rejected. '
            'Please ensure rejection reasons are added.',
            level=messages.WARNING
        )
    action_reject_applications.short_description = "Reject Applications"

    def save_model(self, request, obj, form, change):
        """Handle FSM state transitions on save"""
        if change:
            old_obj = ProviderOnboarding.objects.get(pk=obj.pk)

            if old_obj.status != obj.status:
                try:
                    if (obj.status == OnboardingStatus.UNDER_REVIEW
                            and old_obj.can_review()):
                        obj.reviewed_by = request.user
                        obj.reviewed_at = timezone.now()

                    elif (obj.status == OnboardingStatus.APPROVED
                            and old_obj.status == OnboardingStatus.UNDER_REVIEW):
                        if not obj.provider:
                            obj.approve(request.user)
                            self.message_user(
                                request,
                                f'Provider account created for '
                                f'{obj.get_full_name()}!',
                                level=messages.SUCCESS
                            )
                            return

                    elif (obj.status == OnboardingStatus.REJECTED
                            and old_obj.status == OnboardingStatus.UNDER_REVIEW):
                        obj.reviewed_by = request.user
                        obj.rejected_at = timezone.now()

                    elif (obj.status == OnboardingStatus.CHANGES_REQUIRED
                            and old_obj.status == OnboardingStatus.UNDER_REVIEW):
                        obj.reviewed_by = request.user
                        obj.reviewed_at = timezone.now()

                except ValueError as e:
                    self.message_user(request, str(e), level=messages.ERROR)
                    return

        super().save_model(request, obj, form, change)
