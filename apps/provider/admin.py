from __future__ import annotations

import logging

from django import forms
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, mark_safe

from apps.staff.models import Staff
from apps.user.models import User

from .choices import OnboardingStatus, ProviderVerificationStatus
from .models import Provider, ProviderOnboarding

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = (OnboardingStatus.APPROVED, OnboardingStatus.REJECTED)


# ── Helpers ───────────────────────────────────────────────────────────────────


def get_reviewer(request_user: User) -> Staff | None:
    """
    Return a Staff instance when the acting user is Staff.
    Superusers who are not Staff return None — the FK field is nullable.
    """
    if isinstance(request_user, Staff):
        return request_user
    return None


def stamp_reviewer(obj: ProviderOnboarding, request_user: User) -> Staff | None:
    """
    Preserve the audit trail for superusers who are not Staff.

    - Staff actor   → sets reviewed_by normally.
    - Superuser     → reviewed_by stays NULL (field is Staff-typed), but the
                      actor's email is appended to admin_notes so the action
                      is never lost.
    """
    reviewer = get_reviewer(request_user)
    obj.reviewed_by = reviewer

    if reviewer is None:
        note = f"[Action by superuser: {request_user.email}]"
        obj.admin_notes = (
            f"{obj.admin_notes}\n{note}".strip() if obj.admin_notes else note
        )

    return reviewer


# ─────────────────────────────────────────────────────────────────────────────
# Provider Admin
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "first_name",
        "last_name",
        "region",
        "verification_badge",
        "average_rating",
        "completion_rate_display",
        "is_available",
        "date_joined",
    )
    list_filter = ("verification_status", "is_available", "is_active", "region")
    search_fields = ("email", "first_name", "last_name", "business_name", "phone")
    readonly_fields = (
        "date_joined",
        "last_login",
        "updated_at",
        "total_earnings",
        "total_jobs",
        "completed_jobs",
        "average_rating",
        "total_reviews",
        "completion_rate_display",
        "verification_status",
        "is_verified",
    )
    filter_horizontal = ("categories",)
    actions = ["make_available", "make_unavailable"]

    fieldsets = (
        (
            "User Information",
            {
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "phone",
                    "profile_picture",
                ),
            },
        ),
        (
            "Service",
            {
                "fields": (
                    "categories",
                    "region",
                    "hourly_rate",
                    "years_of_experience",
                    "service_radius",
                ),
            },
        ),
        ("Business", {"fields": ("business_name", "bio")}),
        ("Financial", {"fields": ("total_earnings", "available_balance")}),
        ("Availability", {"fields": ("is_available",)}),
        ("Location", {"fields": ("address", "latitude", "longitude")}),
        (
            "Statistics",
            {
                "fields": (
                    "total_jobs",
                    "completed_jobs",
                    "completion_rate_display",
                    "average_rating",
                    "total_reviews",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": ("is_active", "is_verified", "verification_status"),
                "description": "Verification status is managed automatically via onboarding.",
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("date_joined", "last_login", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def has_add_permission(self, request) -> bool:
        return False

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("region")
            .prefetch_related("categories")
        )

    @admin.display(description="Verification")
    def verification_badge(self, obj: Provider) -> str:
        colors = {
            ProviderVerificationStatus.PENDING: "orange",
            ProviderVerificationStatus.VERIFIED: "green",
            ProviderVerificationStatus.REJECTED: "red",
        }
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            colors.get(obj.verification_status, "gray"),
            obj.get_verification_status_display(),
        )

    @admin.display(description="Completion Rate")
    def completion_rate_display(self, obj: Provider) -> str:
        return f"{obj.get_completion_rate()}%"

    @admin.action(description="Mark as available")
    def make_available(self, request, queryset) -> None:
        updated = queryset.update(is_available=True)
        self.message_user(
            request, f"{updated} provider(s) marked as available.", messages.SUCCESS
        )

    @admin.action(description="Mark as unavailable")
    def make_unavailable(self, request, queryset) -> None:
        updated = queryset.update(is_available=False)
        self.message_user(
            request, f"{updated} provider(s) marked as unavailable.", messages.WARNING
        )


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding Form
# ─────────────────────────────────────────────────────────────────────────────


class ProviderOnboardingAdminForm(forms.ModelForm):
    """
    Admin form for onboarding applications.

    No password fields — the provider set their password during app registration
    and it is never visible or editable by staff.
    """

    class Meta:
        model = ProviderOnboarding
        fields = [
            "applicant",
            "status",
            "first_name",
            "last_name",
            "email",
            "phone",
            "date_of_birth",
            "profile_photo",
            "address",
            "region",
            "category",
            "hourly_rate",
            "years_of_experience",
            "bio",
            "nid_front",
            "nid_back",
            "police_clearance_certificate",
            "professional_certificate",
            "reviewed_by",
            "admin_notes",
            "rejection_reason",
            "change_requests",
        ]
        widgets = {
            "admin_notes": forms.Textarea(attrs={"rows": 3}),
            "rejection_reason": forms.Textarea(attrs={"rows": 3}),
            "change_requests": forms.Textarea(attrs={"rows": 3}),
            "bio": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.fields["reviewed_by"].queryset = Staff.objects.filter(is_active=True)
        self.fields["reviewed_by"].required = False
        self.fields["reviewed_by"].widget.can_add_related = False
        self.fields["reviewed_by"].widget.can_change_related = False
        self.fields["reviewed_by"].widget.can_delete_related = False

        self.fields["applicant"].queryset = Provider.objects.filter(
            is_active=False,
            verification_status=ProviderVerificationStatus.PENDING,
        )
        self.fields["applicant"].required = False
        self.fields["applicant"].widget.can_add_related = False
        self.fields["applicant"].widget.can_change_related = False

        # Prefill personal fields from the linked applicant
        instance = kwargs.get("instance")
        if instance and instance.applicant_id:
            applicant = instance.applicant
            for field, value in {
                "first_name": applicant.first_name,
                "last_name": applicant.last_name,
                "email": applicant.email,
                "phone": applicant.phone or "",
            }.items():
                if not self.initial.get(field):
                    self.initial[field] = value


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding Admin — shared fieldset constants
# ─────────────────────────────────────────────────────────────────────────────

_FIELDSET_PRE_REGISTERED = (
    "Pre-Registered Provider",
    {
        "fields": ("applicant",),
        "description": (
            "Link the provider who pre-registered via the mobile app. "
            "Their basic info will be prefilled below and can be edited before saving."
        ),
    },
)
_FIELDSET_LOCATION = (
    "Location & Service",
    {"fields": ("address", "region", "category")},
)
_FIELDSET_PROFESSIONAL = (
    "Professional Details",
    {"fields": ("hourly_rate", "years_of_experience", "bio")},
)
_FIELDSET_REVIEW = (
    "Admin Review",
    {"fields": ("reviewed_by", "admin_notes", "rejection_reason", "change_requests")},
)


# ─────────────────────────────────────────────────────────────────────────────
# Onboarding Admin
# ─────────────────────────────────────────────────────────────────────────────


@admin.register(ProviderOnboarding)
class ProviderOnboardingAdmin(admin.ModelAdmin):
    form = ProviderOnboardingAdminForm

    list_display = (
        "get_full_name",
        "email",
        "applicant_link",
        "category",
        "region",
        "status_badge",
        "age",
        "hourly_rate",
        "submitted_at",
    )
    list_filter = ("status", "category", "region", "submitted_at")
    search_fields = ("first_name", "last_name", "email", "phone")
    actions = ["action_move_to_review", "action_approve", "action_reject"]

    def get_readonly_fields(self, request, obj=None):
        readonly = [
            "id",
            "submitted_at",
            "reviewed_at",
            "approved_at",
            "rejected_at",
            "updated_at",
        ]
        if obj is not None:
            readonly += ["age", "provider_link", "document_preview"]
        return readonly

    def get_fieldsets(self, request, obj=None):
        personal = (
            "Personal Information",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                    "phone",
                    "date_of_birth",
                    "profile_photo",
                ),
            },
        )
        personal_with_age = (
            "Personal Information",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "email",
                    "phone",
                    "date_of_birth",
                    "age",
                    "profile_photo",
                ),
            },
        )
        documents = (
            "Documents",
            {
                "fields": (
                    "nid_front",
                    "nid_back",
                    "police_clearance_certificate",
                    "professional_certificate",
                ),
            },
        )
        documents_with_preview = (
            "Documents",
            {
                "fields": (
                    "document_preview",
                    "nid_front",
                    "nid_back",
                    "police_clearance_certificate",
                    "professional_certificate",
                ),
            },
        )

        if obj is None:
            return (
                ("Application Status", {"fields": ("status",)}),
                _FIELDSET_PRE_REGISTERED,
                personal,
                _FIELDSET_LOCATION,
                _FIELDSET_PROFESSIONAL,
                documents,
                _FIELDSET_REVIEW,
            )

        return (
            ("Application Status", {"fields": ("status", "provider_link")}),
            _FIELDSET_PRE_REGISTERED,
            personal_with_age,
            _FIELDSET_LOCATION,
            _FIELDSET_PROFESSIONAL,
            documents_with_preview,
            _FIELDSET_REVIEW,
            (
                "Timestamps",
                {
                    "fields": (
                        "id",
                        "submitted_at",
                        "reviewed_at",
                        "approved_at",
                        "rejected_at",
                        "updated_at",
                    ),
                    "classes": ("collapse",),
                },
            ),
        )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "region", "category", "reviewed_by", "provider", "applicant"
            )
        )

    # ── Display helpers ───────────────────────────────────────────────────────

    @admin.display(description="Applicant")
    def applicant_link(self, obj: ProviderOnboarding) -> str:
        if not obj.applicant_id:
            return mark_safe(  # noqa: S308
                '<span style="color:#999;font-style:italic">Not linked</span>'
            )
        url = reverse("admin:provider_provider_change", args=[obj.applicant_id])
        return format_html('<a href="{}">{}</a>', url, obj.applicant.get_full_name())

    @admin.display(description="Status")
    def status_badge(self, obj: ProviderOnboarding) -> str:
        colors = {
            OnboardingStatus.PENDING: "#FFA500",
            OnboardingStatus.UNDER_REVIEW: "#2196F3",
            OnboardingStatus.CHANGES_REQUIRED: "#FF9800",
            OnboardingStatus.APPROVED: "#4CAF50",
            OnboardingStatus.REJECTED: "#F44336",
        }
        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;'
            "border-radius:10px;font-weight:bold;font-size:10px;"
            'text-transform:uppercase">{}</span>',
            colors.get(obj.status, "#757575"),
            obj.get_status_display(),
        )

    @admin.display(description="Provider Account")
    def provider_link(self, obj: ProviderOnboarding) -> str:
        if obj.provider_id:
            url = reverse("admin:provider_provider_change", args=[obj.provider_id])
            return mark_safe(  # noqa: S308
                f'<a href="{url}" style="color:#4CAF50;font-weight:bold;padding:6px 12px;'
                f'background:#E8F5E9;border-radius:4px;text-decoration:none">'
                f"View Provider Account</a>"
            )
        return mark_safe(  # noqa: S308
            '<span style="color:#999;font-style:italic">Not created yet</span>'
        )

    @admin.display(description="Documents")
    def document_preview(self, obj: ProviderOnboarding) -> str:
        parts = []

        def img_card(label: str, f) -> str:
            return (
                f'<div style="border:2px solid #e0e0e0;padding:10px;border-radius:8px">'
                f'<strong style="color:#666">{label}</strong><br><br>'
                f'<img src="{f.url}" style="max-width:100%;max-height:200px;border-radius:4px">'
                f"</div>"
            )

        def link_card(label: str, f) -> str:
            return (
                f'<div style="border:2px solid #e0e0e0;padding:15px;border-radius:8px">'
                f'<strong style="color:#666">{label}</strong><br><br>'
                f'<a href="{f.url}" target="_blank" style="color:#2196F3">View Document</a>'
                f"</div>"
            )

        if obj.nid_front:
            parts.append(img_card("NID Front", obj.nid_front))
        if obj.nid_back:
            parts.append(img_card("NID Back", obj.nid_back))
        if obj.police_clearance_certificate:
            parts.append(
                link_card("Police Clearance", obj.police_clearance_certificate)
            )
        if obj.professional_certificate:
            parts.append(
                link_card("Professional Certificate", obj.professional_certificate)
            )

        if not parts:
            return mark_safe(  # noqa: S308
                '<span style="color:#999">No documents uploaded yet.</span>'
            )

        return mark_safe(  # noqa: S308
            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;padding:10px">'
            + "".join(parts)
            + "</div>"
        )

    # ── Save with FSM enforcement ─────────────────────────────────────────────

    def save_model(self, request, obj, form, change):
        # New application — save as-is.
        if not change:
            super().save_model(request, obj, form, change)
            return

        try:
            old = ProviderOnboarding.objects.get(pk=obj.pk)
        except ProviderOnboarding.DoesNotExist:
            super().save_model(request, obj, form, change)
            return

        old_status = old.status
        new_status = obj.status

        # Block any edits once the application has reached a terminal state.
        if old_status in TERMINAL_STATUSES:
            self.message_user(
                request,
                f"Cannot modify a '{old.get_status_display()}' application.",
                messages.ERROR,
            )
            obj.status = old_status
            super().save_model(request, obj, form, change)
            return

        # No status change — field-only update, save freely.
        if old_status == new_status:
            super().save_model(request, obj, form, change)
            return

        # Status transition — enforce FSM rules.
        try:
            if new_status == OnboardingStatus.UNDER_REVIEW:
                if old_status not in (
                    OnboardingStatus.PENDING,
                    OnboardingStatus.CHANGES_REQUIRED,
                ):
                    raise ValueError(
                        f"Cannot move to Under Review from '{old.get_status_display()}'."
                    )
                stamp_reviewer(obj, request.user)
                obj.reviewed_at = timezone.now()
                super().save_model(request, obj, form, change)

            elif new_status == OnboardingStatus.APPROVED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot approve from '{old.get_status_display()}'. "
                        "Application must be Under Review first."
                    )
                if old.provider_id:
                    self.message_user(
                        request, "Provider account already exists.", messages.WARNING
                    )
                    super().save_model(request, obj, form, change)
                    return

                # Step 1: persist form data (personal info, docs) while keeping
                # the current FSM status so approve() sees a clean transition.
                obj.status = OnboardingStatus.UNDER_REVIEW
                super().save_model(request, obj, form, change)
                obj.refresh_from_db()

                # Step 2: stamp reviewer — may mutate admin_notes for superusers.
                reviewer = stamp_reviewer(obj, request.user)
                if reviewer is None:
                    obj.save(update_fields=["admin_notes"])

                # Step 3: activate the provider account.
                obj.approve(reviewer)

                self.message_user(
                    request,
                    f"Provider account for {obj.get_full_name()} has been activated. "
                    "They can now log in using the password they set during registration.",
                    messages.SUCCESS,
                )
                return redirect(
                    reverse("admin:provider_provider_change", args=[obj.provider_id])
                )

            elif new_status == OnboardingStatus.REJECTED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot reject from '{old.get_status_display()}'. "
                        "Application must be Under Review first."
                    )
                stamp_reviewer(obj, request.user)
                obj.rejected_at = timezone.now()
                if not obj.rejection_reason:
                    self.message_user(
                        request,
                        "Saved, but please add a rejection reason for record keeping.",
                        messages.WARNING,
                    )
                super().save_model(request, obj, form, change)

            elif new_status == OnboardingStatus.CHANGES_REQUIRED:
                if old_status != OnboardingStatus.UNDER_REVIEW:
                    raise ValueError(
                        f"Cannot request changes from '{old.get_status_display()}'. "
                        "Application must be Under Review first."
                    )
                stamp_reviewer(obj, request.user)
                obj.reviewed_at = timezone.now()
                if not obj.change_requests:
                    self.message_user(
                        request,
                        "Saved, but please fill in the required changes field.",
                        messages.WARNING,
                    )
                super().save_model(request, obj, form, change)

            else:
                super().save_model(request, obj, form, change)

        except ValueError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            obj.status = old_status
            super().save_model(request, obj, form, change)

    # ── Bulk Actions ──────────────────────────────────────────────────────────

    @admin.action(description="Move to Under Review")
    def action_move_to_review(self, request, queryset) -> None:
        reviewer = get_reviewer(request.user)
        success = skip = 0
        for app in queryset:
            if not app.can_review():
                skip += 1
                continue
            try:
                app.move_to_review(reviewer)
                success += 1
            except Exception as exc:
                logger.exception("Error moving %s to review", app.pk)
                self.message_user(request, f"Error: {exc}", messages.ERROR)
        if success:
            self.message_user(
                request,
                f"{success} application(s) moved to Under Review.",
                messages.SUCCESS,
            )
        if skip:
            self.message_user(
                request, f"{skip} skipped (wrong status).", messages.WARNING
            )

    @admin.action(description="✅ Approve — opens detail page to confirm")
    def action_approve(self, request, queryset):
        eligible = [app for app in queryset if app.can_approve()]
        if not eligible:
            self.message_user(
                request,
                "No selected applications are Under Review. Move them to Under Review first.",
                messages.WARNING,
            )
            return
        if len(eligible) == 1:
            url = reverse(
                "admin:provider_provideronboarding_change", args=[eligible[0].pk]
            )
            return redirect(url)
        self.message_user(
            request,
            f"{len(eligible)} application(s) ready. Open each individually to approve.",
            messages.INFO,
        )

    @admin.action(description="Reject selected applications")
    def action_reject(self, request, queryset) -> None:
        reviewer = get_reviewer(request.user)
        success = skip = 0
        for app in queryset:
            if not app.can_reject():
                skip += 1
                continue
            try:
                app.reject(
                    reviewer,
                    reason=app.rejection_reason or "Rejected via bulk action.",
                )
                success += 1
            except Exception as exc:
                logger.exception("Error rejecting %s", app.pk)
                self.message_user(request, f"Error: {exc}", messages.ERROR)
        if success:
            self.message_user(
                request, f"{success} application(s) rejected.", messages.WARNING
            )
        if skip:
            self.message_user(
                request, f"{skip} skipped (wrong status).", messages.WARNING
            )
