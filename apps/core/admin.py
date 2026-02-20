from django.contrib import admin
from django.utils.html import format_html

from .models import Category, Region


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'slug',
        'icon_display',
        'is_active',
        'order',
        'created_at'
    )
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('order', 'name')

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'description', 'icon')
        }),
        ('Settings', {
            'fields': ('is_active', 'order')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('created_at', 'updated_at')

    def icon_display(self, obj):
        """Display icon if available"""
        if obj.icon:
            return format_html(
                '<span style="font-size: 16px;">{}</span>',
                obj.icon
            )
        return '-'
    icon_display.short_description = 'Icon'


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'country', 'is_active', 'created_at')
    list_filter = ('is_active', 'country', 'created_at')
    search_fields = ('name', 'code', 'country')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('country', 'name')

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'slug', 'code', 'country')
        }),
        ('Geographic Data', {
            'fields': ('latitude', 'longitude')
        }),
        ('Settings', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ('created_at', 'updated_at')
