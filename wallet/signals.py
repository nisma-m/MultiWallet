from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.core.mail import send_mail
from decimal import Decimal
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from .models import Transaction, Ledger, FraudLog, Wallet, LoginHistory

# Constants
FRAUD_AMOUNT_LIMIT = Decimal('500000')  # ₹5,00,000
FRAUD_TXN_COUNT = 3
FRAUD_TIME_WINDOW_MINUTES = 10
ADMIN_EMAIL = "admin@walletapp.com"


@receiver(post_save, sender=Transaction)
def handle_transaction_save(sender, instance, created, **kwargs):
    if created and instance.status == 'PENDING':
        return

    # ✅ Process approved transactions and update balances
    if instance.status == 'APPROVED' and not Ledger.objects.filter(transaction=instance).exists():
        if instance.tx_type == 'DEPOSIT':
            instance.wallet.balance += instance.amount
            instance.wallet.save()

            Ledger.objects.create(
                transaction=instance,
                wallet=instance.wallet,
                entry_type='credit',
                amount=instance.amount,
                balance_after=instance.wallet.balance
            )

        elif instance.tx_type == 'WITHDRAW':
            instance.wallet.balance -= instance.amount
            instance.wallet.save()

            Ledger.objects.create(
                transaction=instance,
                wallet=instance.wallet,
                entry_type='debit',
                amount=instance.amount,
                balance_after=instance.wallet.balance
            )

        elif instance.tx_type == 'TRANSFER':
            instance.wallet.balance -= instance.amount
            instance.wallet.save()

            Ledger.objects.create(
                transaction=instance,
                wallet=instance.wallet,
                entry_type='debit',
                amount=instance.amount,
                balance_after=instance.wallet.balance
            )

            if instance.target_wallet:
                instance.target_wallet.balance += instance.converted_amount or instance.amount
                instance.target_wallet.save()

                Ledger.objects.create(
                    transaction=instance,
                    wallet=instance.target_wallet,
                    entry_type='credit',
                    amount=instance.converted_amount or instance.amount,
                    balance_after=instance.target_wallet.balance
                )

        # ✅ Send approval email
        subject = f"{instance.tx_type.capitalize()} Approved"
        message = (
            f"✅ Your {instance.tx_type.lower()} request has been approved.\n\n"
            f"Transaction ID: {instance.id}\n"
            f"Amount: ₹{instance.amount}\n"
            f"Status: {instance.status}\n"
            f"Wallet: {instance.wallet.account_number}\n"
            f"Date: {instance.processed_at.strftime('%Y-%m-%d %H:%M:%S') if instance.processed_at else 'N/A'}\n"
        )
        send_email_notification(instance.wallet.user.email, subject, message)

        # ✅ Notify recipient (transfer)
        if instance.tx_type == 'TRANSFER' and instance.target_wallet:
            subject2 = "💰 You've Received Funds"
            message2 = (
                f"Hi {instance.target_wallet.user.first_name},\n\n"
                f"You received ₹{instance.converted_amount or instance.amount} "
                f"in your {instance.target_wallet.currency.code} wallet from "
                f"{instance.wallet.user.username}.\n\n"
                f"Transaction ID: {instance.id}\n"
                f"Date: {instance.processed_at.strftime('%Y-%m-%d %H:%M:%S') if instance.processed_at else 'N/A'}"
            )
            send_email_notification(instance.target_wallet.user.email, subject2, message2)

    # ✅ Handle rejected transactions
    if instance.status == 'REJECTED':
        instance.wallet.balance += instance.amount
        instance.wallet.save()

        subject = f"{instance.tx_type.capitalize()} Rejected"
        message = (
            f"⚠️ Your {instance.tx_type.lower()} request has been rejected.\n\n"
            f"Transaction ID: {instance.id}\n"
            f"Amount: ₹{instance.amount}\n"
            f"Status: {instance.status}\n"
            f"Wallet: {instance.wallet.account_number}\n"
            f"Date: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        send_email_notification(instance.wallet.user.email, subject, message)

    # ✅ Fraud checks — high-value
    if instance.amount >= FRAUD_AMOUNT_LIMIT:
        log, created = FraudLog.objects.get_or_create(
            user=instance.wallet.user,
            transaction=instance,
            reason=f"⚠️ High-value transaction over ₹{FRAUD_AMOUNT_LIMIT}"
        )
        if created:
            subject = "⚠️ Fraud Alert: High-Value Transaction"
            message = (
                f"A suspicious transaction was flagged on your wallet.\n\n"
                f"Transaction ID: {instance.id}\n"
                f"Amount: ₹{instance.amount}\n"
                f"Date: {instance.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Reason: {log.reason}\n\n"
                f"If this wasn't you, please contact support."
            )
            send_email_notification(instance.wallet.user.email, subject, message)
            send_email_notification(ADMIN_EMAIL, subject, message)

    # ✅ Fraud checks — rapid multiple transactions
    time_window = timezone.now() - timedelta(minutes=FRAUD_TIME_WINDOW_MINUTES)
    tx_count = Transaction.objects.filter(
        wallet=instance.wallet,
        created_at__gte=time_window
    ).count()

    if tx_count >= FRAUD_TXN_COUNT:
        log, created = FraudLog.objects.get_or_create(
            user=instance.wallet.user,
            transaction=instance,
            reason=f"⚠️ {tx_count} transactions within {FRAUD_TIME_WINDOW_MINUTES} minutes"
        )
        if created:
            subject = "⚠️ Fraud Alert: Suspicious Transaction Pattern"
            message = (
                f"Multiple transactions were detected in a short time window.\n\n"
                f"User: {instance.wallet.user.username}\n"
                f"Count: {tx_count} transactions\n"
                f"Time Frame: {FRAUD_TIME_WINDOW_MINUTES} minutes\n"
                f"Latest Tx ID: {instance.id}\n\n"
                f"If this activity seems suspicious, please review immediately."
            )
            send_email_notification(instance.wallet.user.email, subject, message)
            send_email_notification(ADMIN_EMAIL, subject, message)


def send_email_notification(to_email, subject, message):
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL or 'noreply@walletapp.com',
            recipient_list=[to_email],
            fail_silently=True
        )
    except Exception as e:
        print(f"[Email Error] {e}")


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    if not request.session.session_key:
        request.session.save()
    session_key = request.session.session_key or "N/A"

    LoginHistory.objects.create(
        user=user,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        session_key=session_key,
    )


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    session_key = request.session.session_key
    if session_key:
        LoginHistory.objects.filter(
            user=user,
            session_key=session_key,
            logout_time__isnull=True
        ).update(logout_time=timezone.now())


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')
