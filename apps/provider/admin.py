import logging

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from apps.staff.models import Staff
from apps.user.models import User

from .choices import OnboardingStatus, ProviderVerificationStatus
from .models import Provider, ProviderOnboarding

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = (OnboardingStatus.APPROVED, OnboardingStatus.REJECTED)


# ─────────────────────────────────────────────────────────────
# Provider Admin — view / edit / delete only (no add)
# ─────────────────────────────────────────────────────────────

@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):

    list_display = (
        'email', 'first_name', 'last_name', 'region',
        'verification_badge', 'average_rating',
        'completion_rate_display', 'is_available', 'date_joined',
    )
    list_filter = ('verification_status',
                   'is_available', 'is_active', 'region')
    search_fields = ('email', 'first_name', 'last_name',
                     'business_name', 'phone')
    readonly_fields = (
        'date_joined', 'last_login', 'updated_at',
        'total_earnings', 'total_jobs', 'completed_jobs',
        'average_rating', 'total_reviews', 'completion_rate_display',
    )
    filter_horizontal = ('categories',)
    actions = ['verify_providers', 'reject_providers',
               'make_available', 'make_unavailable']

    fieldsets = (
        ('User Information', {
            'fields': ('email', 'first_name', 'last_name', 'phone', 'profile_picture'),
        }),
        ('Service', {
            'fields': ('categories', 'region', 'hourly_rate', 'years_of_experience', 'service_radius'),
        }),
        ('Business', {
            'fields': ('business_name', 'bio'),
        }),
        ('Verification', {
            'fields': ('verification_status', 'id_document', 'certification'),
        }),
        ('Financial', {
            'fields': ('total_earnings', 'available_balance'),
        }),
        ('Availability', {
            'fields': ('is_available',),
        }),
        ('Location', {
            'fields': ('address', 'latitude', 'longitude'),
        }),
        ('Statistics', {
            'fields': (
                'total_jobs', 'completed_jobs',
                'completion_rate_display', 'average_rating', 'total_reviews',
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

    def has_add_permission(self, request):
        return False  # only created via onboarding approval

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('region').prefetch_related('categories')

    @admin.display(description='Verification')
    def verification_badge(self, obj):
        colors = {
            ProviderVerificationStatus.PENDING:  'orange',
            ProviderVerificationStatus.VERIFIED: 'green',
            ProviderVerificationStatus.REJECTED: 'red',
        }
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            colors.get(obj.verification_status, 'gray'),
            obj.get_verification_status_display(),
        )

    @admin.display(description='Completion Rate')
    def completion_rate_display(self, obj):
        return f"{obj.get_completion_rate()}%"

    @admin.action(description="Verify selected providers")
    def verify_providers(self, request, queryset):
        updated = queryset.update(
            verification_status=ProviderVerificationStatus.VERIFIED, is_verified=True)
        self.message_user(
            request, f"{updated} provider(s) verified.", messages.SUCCESS)

    @admin.action(description="Reject selected providers")
    def reject_providers(self, request, queryset):
        updated = queryset.update(
            verification_status=ProviderVerificationStatus.REJECTED, is_verified=False)
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


# ─────────────────────────────────────────────────────────────
# Onboarding Form
# ─────────────────────────────────────────────────────────────

class ProviderOnboardingAdminForm(forms.ModelForm):
    set_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        label="Provider Password",
        help_text="Required when approving. Min 8 characters.",
    )
    confirm_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        label="Confirm Password",
    )

    class Meta:
        model = ProviderOnboarding
        fields = '__all__'
        widgets = {
            'admin_notes':      forms.Textarea(attrs={'rows': 3}),
            'rejection_reason': forms.Textarea(attrs={'rows': 3}),
            'change_requests':  forms.Textarea(attrs={'rows': 3}),
            'bio':              forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit reviewer dropdown to active staff only
        self.fields['reviewed_by'].queryset = Staff.objects.filter(
            is_active=True)

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get('status')
        password = cleaned.get('set_password')
        confirm = cleaned.get('confirm_password')

        # Only enforce password rules when approving a not-yet-approved application
        already_approved = bool(self.instance and self.instance.provider_id)

        if status == OnboardingStatus.APPROVED and not already_approved:
            # Catch duplicate email early so the form shows a clean error
            if User.objects.filter(email=self.instance.email).exists():
                raise forms.ValidationError(
                    f"Cannot approve: '{self.instance.email}' is already registered. "
                    "This person may have an existing customer or staff account."
                )
            if not password:
                raise forms.ValidationError(
                    "A password is required when approving.")
            if len(password) < 8:
                raise forms.ValidationError(
                    "Password must be at least 8 characters.")
            if password != confirm:
                raise forms.ValidationError("Passwords do not match.")

        return cleaned


# ─────────────────────────────────────────────────────────────
# Onboarding Admin
# ─────────────────────────────────────────────────────────────

@admin.register(ProviderOnboarding)
class ProviderOnboardingAdmin(admin.ModelAdmin):

    form = ProviderOnboardingAdminForm

    list_display = (
        'get_full_name', 'email', 'category', 'region',
        'status_badge', 'age', 'hourly_rate', 'submitted_at',
    )
    list_filter = ('status', 'category', 'region', 'submitted_at')
    search_fields = ('first_name', 'last_name', 'email', 'phone')
    readonly_fields = (
        'id', 'age', 'provider_link', 'document_preview',
        'submitted_at', 'reviewed_at', 'approved_at', 'rejected_at', 'updated_at',
    )
    actions = ['action_move_to_review', 'action_approve', 'action_reject']

    fieldsets = (
        ('Application Status', {
            'fields': ('status', 'provider_link'),
        }),
        ('Set Password — required when approving', {
            'fields': ('set_password', 'confirm_password'),
            'description': 'Fill only when changing status to Approved.',
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
        }),
        ('Admin Review', {
            'fields': ('reviewed_by', 'admin_notes', 'rejection_reason', 'change_requests'),
        }),
        ('Timestamps', {
            'fields': (
                'id', 'submitted_at', 'reviewed_at',
                'approved_at', 'rejected_at', 'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'region', 'category', 'reviewed_by', 'provider',
        )

    # ── Display ──────────────────────────────────────────────

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            OnboardingStatus.PENDING:          '#FFA500',
            OnboardingStatus.UNDER_REVIEW:     '#2196F3',
            OnboardingStatus.CHANGES_REQUIRED: '#FF9800',
            OnboardingStatus.APPROVED:         '#4CAF50',
            OnboardingStatus.REJECTED:         '#F44336',
        }
        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;'
            'border-radius:10px;font-weight:bold;font-size:10px;'
            'text-transform:uppercase">{}</span>',
            colors.get(obj.status, '#757575'),
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
                '<a href="{}" style="color:#4CAF50;font-weight:bold;padding:6px 12px;'
                'background:#E8F5E9;border-radius:4px;text-decoration:none">'
                'View Provider Account</a>',
                url,
            )
        return mark_safe('<span style="color:#999;font-style:italic">Not created yet</span>')

    @admin.display(description='Documents')
    def document_preview(self, obj):
        parts = [
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;padding:10px">']

        def img_card(label, f):
            return (
                f'<div style="border:2px solid #e0e0e0;padding:10px;border-radius:8px">'
                f'<strong style="color:#666">{label}</strong><br><br>'
                f'<img src="{f.url}" style="max-width:100%;max-height:200px;border-radius:4px">'
                f'</div>'
            )

        def link_card(label, f):
            return (
                f'<div style="border:2px solid #e0e0e0;padding:15px;border-radius:8px">'
                f'<strong style="color:#666">{label}</strong><br><br>'
                f'<a href="{f.url}" target="_blank" style="color:#2196F3">View Document</a>'
                f'</div>'
            )

        if obj.nid_front:
            parts.append(img_card('NID Front', obj.nid_front))
        if obj.nid_back:
            parts.append(img_card('NID Back', obj.nid_back))
        if obj.police_clearance_certificate:
            parts.append(link_card('Police Clearance',
                         obj.police_clearance_certificate))
        if obj.professional_certificate:
            parts.append(link_card('Professional Certificate',
                         obj.professional_certificate))

        parts.append('</div>')
        return mark_safe(''.join(parts))

    # ── Save with FSM enforcement ────────────────────────────

    def save_model(self, request, obj, form, change):
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
        if old_status in TERMINAL_STATUSES:
            self.message_user(
                request,
                f"Cannot modify a '{old.get_status_display()}' application.",
                messages.ERROR,
            )
            obj.status = old_status
            super().save_model(request, obj, form, change)
            return

        # No status change — allow field-only updates freely
        if old_status == obj.status:
            super().save_model(request, obj, form, change)
            return

        # FSM transition handlers
        try:
            if obj.status == OnboardingStatus.UNDER_REVIEW:
                if old_status not in (OnboardingStatus.PENDING, OnboardingStatus.CHANGES_REQUIRED):
                    raise ValueError(
                        f"Cannot move to Under Review from '{old.get_status_display()}'.")
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()
                super().save_model(request, obj, form, change)

            elif obj.status == OnboardingStatus.APPROVED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        "Application must be Under Review before approval.")
                if old.provider:
                    self.message_user(
                        request, "Provider account already exists.", messages.WARNING)
                    super().save_model(request, obj, form, change)
                else:
                    password = form.cleaned_data['set_password']
                    old.approve(request.user, password=password)
                    return self._show_password_page(request, old, password)

            elif obj.status == OnboardingStatus.REJECTED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        "Application must be Under Review before rejection.")
                obj.reviewed_by = request.user
                obj.rejected_at = timezone.now()
                if not obj.rejection_reason:
                    self.message_user(
                        request,
                        "Saved, but please add a rejection reason for record keeping.",
                        messages.WARNING,
                    )
                super().save_model(request, obj, form, change)

            elif obj.status == OnboardingStatus.CHANGES_REQUIRED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        "Application must be Under Review to request changes.")
                obj.reviewed_by = request.user
                obj.reviewed_at = timezone.now()
                if not obj.change_requests:
                    self.message_user(
                        request,
                        "Saved, but please fill in the required changes field.",
                        messages.WARNING,
                    )
                super().save_model(request, obj, form, change)

        except ValueError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            obj.status = old_status
            super().save_model(request, obj, form, change)

    def _show_password_page(self, request, application, password):
        """One-time password display — shown once after approval, never stored in plaintext."""
        back_url = reverse('admin:provider_provideronboarding_changelist')
        provider_url = reverse('admin:provider_provider_change', args=[
                               application.provider_id])
        return HttpResponse(f"""
        <html><body style="font-family:sans-serif;padding:40px;max-width:620px;margin:auto">
            <div style="background:#E8F5E9;border:2px solid #4CAF50;border-radius:8px;padding:30px">
                <h2 style="color:#2E7D32;margin-top:0">✅ Provider Account Created</h2>
                <p>The account for <strong>{application.get_full_name()}</strong> is ready.</p>
                <div style="background:white;border-radius:6px;padding:20px;margin:20px 0">
                    <table style="width:100%;border-collapse:collapse">
                        <tr>
                            <td style="padding:10px;color:#666;width:35%">Name</td>
                            <td style="padding:10px;font-weight:bold">{application.get_full_name()}</td>
                        </tr>
                        <tr style="background:#f9f9f9">
                            <td style="padding:10px;color:#666">Email</td>
                            <td style="padding:10px;font-weight:bold">{application.email}</td>
                        </tr>
                        <tr>
                            <td style="padding:10px;color:#666">Password</td>
                            <td style="padding:10px;font-family:monospace;font-size:20px;
                                font-weight:bold;color:#1565C0;letter-spacing:2px">{password}</td>
                        </tr>
                    </table>
                </div>
                <p style="color:#c62828;font-weight:bold">
                    ⚠️ This password will NOT be shown again. Share it with the provider securely.
                </p>
                <div style="display:flex;gap:10px;margin-top:20px">
                    <a href="{provider_url}"
                       style="background:#4CAF50;color:white;padding:10px 20px;
                              text-decoration:none;border-radius:4px;font-weight:bold">
                        View Provider Account
                    </a>
                    <a href="{back_url}"
                       style="background:#417690;color:white;padding:10px 20px;
                              text-decoration:none;border-radius:4px">
                        ← Back to Applications
                    </a>
                </div>
            </div>
        </body></html>
        """)

    # ── Bulk Actions ─────────────────────────────────────────

    @admin.action(description="Move to Under Review")
    def action_move_to_review(self, request, queryset):
        success = skip = 0
        for app in queryset:
            if not app.can_review():
                skip += 1
                continue
            try:
                app.move_to_review(request.user)
                success += 1
            except Exception as exc:
                logger.error("Error moving %s to review: %s",
                             app.pk, exc, exc_info=True)
                self.message_user(request, f"Error: {exc}", messages.ERROR)

        if success:
            self.message_user(
                request, f"{success} application(s) moved to Under Review.", messages.SUCCESS)
        if skip:
            self.message_user(
                request, f"{skip} skipped (wrong status).", messages.WARNING)

    @admin.action(description="✅ Approve — opens detail page to set password")
    def action_approve(self, request, queryset):
        """Approval requires a password per provider — must be done from the detail page."""
        eligible = [app for app in queryset if app.can_approve()]

        if not eligible:
            self.message_user(
                request,
                "No selected applications are Under Review. Move them to Under Review first.",
                messages.WARNING,
            )
            return

        if len(eligible) == 1:
            url = reverse('admin:provider_provideronboarding_change', args=[
                          eligible[0].pk])
            return redirect(url)

        self.message_user(
            request,
            f"{len(eligible)} application(s) ready. Open each individually to set a password and approve.",
            messages.INFO,
        )

    @admin.action(description="Reject selected applications")
    def action_reject(self, request, queryset):
        success = skip = 0
        for app in queryset:
            if not app.can_reject():
                skip += 1
                continue
            try:
                app.reject(
                    request.user, reason=app.admin_notes or "Rejected by admin.")
                success += 1
            except Exception as exc:
                logger.error("Error rejecting %s: %s",
                             app.pk, exc, exc_info=True)
                self.message_user(request, f"Error: {exc}", messages.ERROR)

        if success:
            self.message_user(
                request, f"{success} application(s) rejected.", messages.WARNING)
        if skip:
            self.message_user(
                request, f"{skip} skipped (wrong status).", messages.WARNING)
