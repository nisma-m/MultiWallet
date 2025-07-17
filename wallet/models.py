# models.py
import uuid
import pyotp
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from decimal import Decimal

CURRENCY_CHOICES = [
    ('INR', 'Indian Rupee'),
    ('USD', 'US Dollar'),
    ('EUR', 'Euro'),
    ('BTC', 'Bitcoin'),
]

TRANSACTION_TYPE_CHOICES = [
    ('DEPOSIT', 'Deposit'),
    ('WITHDRAW', 'Withdraw'),
    ('TRANSFER', 'Transfer'),
]

TRANSACTION_STATUS_CHOICES = [
    ('PENDING', 'Pending'),
    ('APPROVED', 'Approved'),
    ('REJECTED', 'Rejected'),
]

ROLE_CHOICES = [
    ('user', 'User'),
    ('manager', 'Manager'),
    ('admin', 'Admin'),
]


# class CustomUser(AbstractUser):
#     role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='user')

#     @property
#     def is_manager(self):
#         return self.role == 'manager'



class CustomUser(AbstractUser):
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='user')
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    totp_secret = models.CharField(max_length=32, blank=True, null=True)

    def generate_totp_secret(self):
        self.totp_secret = pyotp.random_base32()
        self.save()

    def get_totp_uri(self):
        return pyotp.totp.TOTP(self.totp_secret).provisioning_uri(
            name=self.email,
            issuer_name="MultiWalletApp"
        )

    def verify_otp(self, otp):
        return pyotp.TOTP(self.totp_secret).verify(otp)


class Currency(models.Model):
    code = models.CharField(max_length=10, choices=CURRENCY_CHOICES, unique=True)
    name = models.CharField(max_length=50)

    def save(self, *args, **kwargs):
        if not self.name:
            self.name = dict(CURRENCY_CHOICES).get(self.code, self.code)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"




class Wallet(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    frozen_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # ✅ NEW
    is_frozen = models.BooleanField(default=False)
    account_number = models.CharField(max_length=20, unique=True, editable=False, null=False)

    def save(self, *args, **kwargs):
        if not self.account_number:
            import uuid
            self.account_number = str(uuid.uuid4().int)[0:16]
        super().save(*args, **kwargs)

    def freeze(self, amount):
        self.frozen_amount += amount
        self.is_frozen = True
        self.save()

    def unfreeze(self, amount):
        self.frozen_amount = max(Decimal('0.00'), self.frozen_amount - amount)
        if self.frozen_amount == 0:
            self.is_frozen = False
        self.save()

    @property
    def available_balance(self):
        return self.balance - self.frozen_amount  # ✅ For display purposes

    def __str__(self):
        return f"{self.user.username} - {self.currency.code}"



class Transaction(models.Model):
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE)
    target_wallet = models.ForeignKey(Wallet, on_delete=models.SET_NULL, null=True, blank=True, related_name='incoming_transfers')
    tx_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    converted_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=TRANSACTION_STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(CustomUser, null=True, blank=True, on_delete=models.SET_NULL, related_name='approved_tx')
    note = models.TextField(blank=True)

    def is_high_risk(self):
        return self.tx_type == 'WITHDRAW' and self.amount > 500000

    def __str__(self):
        return f"{self.wallet.user.username} - {self.tx_type} {self.amount} ({self.status})"

class Ledger(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE)
    entry_type = models.CharField(max_length=10, choices=[('credit', 'Credit'), ('debit', 'Debit')])
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.wallet} - {self.entry_type} - {self.amount}"

class FraudLog(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    reason = models.TextField()
    flagged_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} flagged for {self.reason}"

class LoginHistory(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    session_key = models.CharField(max_length=40)
    login_time = models.DateTimeField(default=timezone.now)
    logout_time = models.DateTimeField(null=True, blank=True)
    @property
    def timestamp(self):
         return self.logout_time or self.login_time
