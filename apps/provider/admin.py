from django.contrib import admin
from django.utils.html import format_html

from .models import Provider


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = (
        'email',
        'first_name',
        'last_name',
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

    fieldsets = (
        ('User Information', {
            'fields': ('email', 'first_name', 'last_name', 'phone', 'profile_picture')
        }),
        ('Business Information', {
            'fields': ('business_name', 'bio', 'years_of_experience', 'hourly_rate')
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

    actions = ['verify_providers', 'reject_providers',
               'make_available', 'make_unavailable']

    def verification_badge(self, obj):
        """Display colored verification status badge"""
        colors = {
            'pending': 'orange',
            'verified': 'green',
            'rejected': 'red'
        }
        color = colors.get(obj.verification_status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_verification_status_display()
        )
    verification_badge.short_description = 'Verification Status'

    def completion_rate(self, obj):
        """Display completion rate percentage"""
        rate = obj.get_completion_rate()
        return f"{rate}%"
    completion_rate.short_description = 'Completion Rate'

    def completion_rate_display(self, obj):
        """Display completion rate in readonly field"""
        return f"{obj.get_completion_rate()}%"
    completion_rate_display.short_description = 'Completion Rate'

    def verify_providers(self, request, queryset):
        """Verify selected providers"""
        updated = queryset.update(
            verification_status='verified', is_verified=True)
        self.message_user(
            request, f'{updated} provider(s) verified successfully.')
    verify_providers.short_description = "Verify selected providers"

    def reject_providers(self, request, queryset):
        """Reject selected providers"""
        updated = queryset.update(
            verification_status='rejected', is_verified=False)
        self.message_user(request, f'{updated} provider(s) rejected.')
    reject_providers.short_description = "Reject selected providers"

    def make_available(self, request, queryset):
        """Mark providers as available"""
        updated = queryset.update(is_available=True)
        self.message_user(
            request, f'{updated} provider(s) marked as available.')
    make_available.short_description = "Mark as available"

    def make_unavailable(self, request, queryset):
        """Mark providers as unavailable"""
        updated = queryset.update(is_available=False)
        self.message_user(
            request, f'{updated} provider(s) marked as unavailable.')
    make_unavailable.short_description = "Mark as unavailable"
