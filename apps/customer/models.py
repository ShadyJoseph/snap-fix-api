from django.db import models

from apps.user.models import User


class Customer(User):
    """Customer model for users who book services"""

    # Wallet
    wallet_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Current wallet balance"
    )
    total_cashback = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Total cashback earned"
    )

    # Favorites (forward reference to Provider)
    favorite_providers = models.ManyToManyField(
        'provider.Provider',
        blank=True,
        related_name='favorited_by'
    )

    # Stats
    total_bookings = models.IntegerField(
        default=0,
        help_text="Total number of bookings made"
    )

    class Meta:
        db_table = 'customers'
        verbose_name = 'Customer'
        verbose_name_plural = 'Customers'

    def __str__(self):
        return f"Customer: {self.get_full_name()}"

    def add_to_wallet(self, amount):
        """Add money to wallet"""
        if amount > 0:
            self.wallet_balance += amount
            self.save(update_fields=['wallet_balance'])

    def deduct_from_wallet(self, amount):
        """Deduct money from wallet if sufficient balance"""
        if amount > 0 and self.wallet_balance >= amount:
            self.wallet_balance -= amount
            self.save(update_fields=['wallet_balance'])
            return True
        return False

    def add_cashback(self, amount):
        """Add cashback to wallet and total cashback"""
        if amount > 0:
            self.wallet_balance += amount
            self.total_cashback += amount
            self.save(update_fields=['wallet_balance', 'total_cashback'])

    def increment_bookings(self):
        """Increment total bookings counter"""
        self.total_bookings += 1
        self.save(update_fields=['total_bookings'])
