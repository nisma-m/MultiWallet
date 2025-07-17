from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Currency, Wallet, Transaction, Ledger, FraudLog, LoginHistory

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ['username', 'email', 'role', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        ("Extra Info", {'fields': ('role', 'phone_number', 'address')}),
    )

admin.site.register(Currency)
admin.site.register(Wallet)
admin.site.register(Transaction)
admin.site.register(Ledger)
admin.site.register(FraudLog)


@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'ip_address', 'timestamp')
    search_fields = ('user__username', 'ip_address')
    list_filter = ('login_time', 'logout_time', 'user')
