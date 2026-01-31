from django.db import models
from .user import User


class Admin(User):
    """Admin class inheriting from User"""
    
    # Permissions
    can_manage_users = models.BooleanField(
        default=True,
        help_text="Can manage (create, update, delete) users"
    )
    can_manage_services = models.BooleanField(
        default=True,
        help_text="Can manage service categories and listings"
    )
    can_manage_payments = models.BooleanField(
        default=True,
        help_text="Can view and manage payment transactions"
    )
    can_view_analytics = models.BooleanField(
        default=True,
        help_text="Can view platform analytics and reports"
    )
    
    class Meta:
        db_table = 'admins'
        verbose_name = 'Admin'
        verbose_name_plural = 'Admins'
    
    def __str__(self):
        return f"Admin: {self.get_full_name()}"
    
    def has_permission(self, permission_type):
        """Check if admin has specific permission"""
        permission_map = {
            'users': self.can_manage_users,
            'services': self.can_manage_services,
            'payments': self.can_manage_payments,
            'analytics': self.can_view_analytics,
        }
        return permission_map.get(permission_type, False)