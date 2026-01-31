from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Customer, Provider, Admin


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'get_user_type', 'is_active', 'date_joined')
    list_filter = ('is_active', 'is_verified', 'is_staff')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone', 'profile_picture', 'address')}),
        ('Location', {'fields': ('latitude', 'longitude')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_verified')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'first_name', 'last_name'),
        }),
    )
    
    def get_user_type(self, obj):
        return obj.get_user_type()
    get_user_type.short_description = 'User Type'


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'wallet_balance', 'total_bookings', 'date_joined')
    search_fields = ('email', 'first_name', 'last_name', 'phone')
    list_filter = ('is_active', 'is_verified')
    readonly_fields = ('date_joined', 'last_login', 'updated_at')
    
    fieldsets = (
        ('User Info', {'fields': ('email', 'first_name', 'last_name', 'phone', 'profile_picture')}),
        ('Location', {'fields': ('address', 'latitude', 'longitude')}),
        ('Wallet', {'fields': ('wallet_balance', 'total_cashback')}),
        ('Stats', {'fields': ('total_bookings',)}),
        ('Status', {'fields': ('is_active', 'is_verified')}),
        ('Timestamps', {'fields': ('date_joined', 'last_login', 'updated_at')}),
    )


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'verification_status', 'average_rating', 
                    'total_jobs', 'is_available', 'date_joined')
    list_filter = ('verification_status', 'is_available', 'is_verified')
    search_fields = ('email', 'first_name', 'last_name', 'business_name', 'phone')
    readonly_fields = ('date_joined', 'last_login', 'updated_at', 'total_earnings', 
                       'total_jobs', 'completed_jobs', 'average_rating', 'total_reviews')
    
    fieldsets = (
        ('User Info', {'fields': ('email', 'first_name', 'last_name', 'phone', 'profile_picture')}),
        ('Business Info', {'fields': ('business_name', 'bio', 'years_of_experience')}),
        ('Verification', {'fields': ('verification_status', 'id_document', 'certification')}),
        ('Financial', {'fields': ('hourly_rate', 'total_earnings', 'available_balance')}),
        ('Availability', {'fields': ('is_available', 'service_radius')}),
        ('Location', {'fields': ('address', 'latitude', 'longitude')}),
        ('Stats', {'fields': ('total_jobs', 'completed_jobs', 'average_rating', 'total_reviews')}),
        ('Status', {'fields': ('is_active', 'is_verified')}),
        ('Timestamps', {'fields': ('date_joined', 'last_login', 'updated_at')}),
    )
    
    actions = ['verify_providers', 'reject_providers']
    
    def verify_providers(self, request, queryset):
        queryset.update(verification_status='verified', is_verified=True)
    verify_providers.short_description = "Verify selected providers"
    
    def reject_providers(self, request, queryset):
        queryset.update(verification_status='rejected')
    reject_providers.short_description = "Reject selected providers"


@admin.register(Admin)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'last_name', 'can_manage_users', 
                    'can_manage_services', 'date_joined')
    list_filter = ('can_manage_users', 'can_manage_services', 'can_manage_payments')
    search_fields = ('email', 'first_name', 'last_name')
    readonly_fields = ('date_joined', 'last_login', 'updated_at')
    
    fieldsets = (
        ('User Info', {'fields': ('email', 'first_name', 'last_name', 'phone', 'profile_picture')}),
        ('Permissions', {'fields': ('can_manage_users', 'can_manage_services', 
                                    'can_manage_payments', 'can_view_analytics')}),
        ('Status', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        ('Timestamps', {'fields': ('date_joined', 'last_login', 'updated_at')}),
    )
    