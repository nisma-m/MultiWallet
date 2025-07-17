from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils.timezone import now, timedelta
from decimal import Decimal
from .forms import DepositForm, WithdrawForm, TransferForm, UserRegisterForm, CustomLoginForm, OTPForm
from .models import Wallet, Transaction, Ledger, FraudLog, CustomUser, LoginHistory
from .utils import get_conversion_rate
from django.core.mail import send_mail
from django.contrib.auth import login, authenticate
from django.db import transaction as db_transaction
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Q, Sum
import pyotp
import qrcode
import io
import base64
from django.conf import settings
from django_ratelimit.decorators import ratelimit


TRANSACTION_THRESHOLD = 100000

@ratelimit(key='user', rate='10/m', block=True)
@login_required
def dashboard_view(request):
    wallets = Wallet.objects.filter(user=request.user)
    transactions = Transaction.objects.filter(wallet__user=request.user).order_by('-created_at')[:10]
    fraud_logs = FraudLog.objects.filter(user=request.user).order_by('-flagged_at')  # 👈 Add this

    return render(request, 'dashboard.html', {
        'wallets': wallets,
        'transactions': transactions,
        'fraud_logs': fraud_logs,  
    })

@ratelimit(key='user', rate='10/m', block=True)
@login_required
def deposit_view(request):
    if request.method == "POST":
        form = DepositForm(request.POST, user=request.user)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.tx_type = "DEPOSIT"
            tx.wallet = form.cleaned_data['wallet']
            tx.amount = form.cleaned_data['amount']
            tx.note = form.cleaned_data.get('note', '')

            try:
                with db_transaction.atomic():
                    if tx.amount > TRANSACTION_THRESHOLD:
                        tx.status = "PENDING"
                        tx.wallet.freeze(tx.amount)
                        tx.save()
                        messages.info(request, "Deposit submitted for approval.")
                    else:
                        tx.status = "APPROVED"
                        tx.processed_at = now()
                        tx.save()
                        messages.success(request, "Deposit successful.")
            except Exception as e:
                messages.error(request, f"Deposit failed: {str(e)}")
                return redirect("deposit_view")

            return redirect("dashboard_view")
    else:
        form = DepositForm(user=request.user)
    return render(request, 'deposit.html', {'form': form})

@ratelimit(key='user', rate='10/m', block=True)
def check_large_withdrawals(wallet):
    last_24_hours = now() - timedelta(hours=24)
    total_withdrawn = Transaction.objects.filter(
        wallet=wallet,
        tx_type="WITHDRAW",
        status="APPROVED",
        processed_at__gte=last_24_hours
    ).aggregate(total=Sum('amount'))['total'] or 0

    if total_withdrawn > 500000:
        FraudLog.objects.create(
            user=wallet.user,
            reason="Withdrawals exceeded ₹5L in 24 hours"
        )

@ratelimit(key='user', rate='10/m', block=True)
@login_required
def withdraw_view(request):
    if request.method == 'POST':
        form = WithdrawForm(request.POST, user=request.user)
        if form.is_valid():
            tx = form.save(commit=False)
            tx.tx_type = "WITHDRAW"

            if tx.wallet.balance < tx.amount:
                messages.error(request, "Insufficient balance for withdrawal.")
                return redirect('withdraw_view')

            try:
                with db_transaction.atomic():
                    if tx.amount > TRANSACTION_THRESHOLD:
                        tx.status = "PENDING"
                        tx.wallet.freeze(tx.amount)
                        tx.save()
                        messages.info(request, "Withdrawal submitted for approval.")
                    else:
                        tx.status = "APPROVED"
                        tx.processed_at = now()
                        tx.save()
                        messages.success(request, "Withdrawal successful.")
            except Exception as e:
                messages.error(request, f"Withdrawal failed: {str(e)}")
                return redirect("withdraw_view")

            return redirect('dashboard_view')
    else:
        form = WithdrawForm(user=request.user)

    return render(request, 'withdraw.html', {'form': form})



@ratelimit(key='user', rate='10/m', block=True)
@login_required
def transfer_view(request):
    if request.method == 'POST':
        form = TransferForm(request.POST, user=request.user)
        if form.is_valid():
            tx = form.save(commit=False)
            amount = tx.amount

            if tx.wallet.balance < amount:
                messages.error(request, "Insufficient balance for transfer.")
                return redirect('transfer_view')

            # Currency conversion logic
            if tx.wallet.currency != tx.target_wallet.currency:
                try:
                    rate = Decimal(get_conversion_rate(
                        tx.wallet.currency.code,
                        tx.target_wallet.currency.code
                    ))
                    tx.converted_amount = round(amount * rate, 2)
                except Exception as e:
                    messages.error(request, f"Currency conversion failed: {str(e)}")
                    return redirect('transfer_view')
            else:
                tx.converted_amount = amount

            tx.tx_type = "TRANSFER"

            try:
                with db_transaction.atomic():
                    if tx.amount > TRANSACTION_THRESHOLD:
                        # Needs approval → freeze balances
                        tx.status = "PENDING"
                        tx.wallet.freeze(tx.amount)
                        tx.target_wallet.freeze(tx.converted_amount)
                        tx.save()
                        messages.info(request, "Transfer submitted for approval.")
                    else:
                        # Approved directly → update balances immediately
                        tx.status = "APPROVED"
                        tx.processed_at = now()
                        tx.save()

                        # 💸 Update balances
                        tx.wallet.balance -= tx.amount
                        tx.wallet.save()

                        tx.target_wallet.balance += tx.converted_amount
                        tx.target_wallet.save()

                        messages.success(request, "Transfer successful.")
            except Exception as e:
                messages.error(request, f"Transfer failed: {str(e)}")
                return redirect('transfer_view')

            return redirect('dashboard_view')
    else:
        form = TransferForm(user=request.user)

    return render(request, 'transfer.html', {'form': form})

    
@ratelimit(key='user', rate='10/m', block=True)
@login_required
def ledger_view(request):
    wallets = Wallet.objects.filter(user=request.user)
    selected_wallet_id = request.GET.get('wallet')
    selected_wallet = None
    ledger_entries = []

    if selected_wallet_id:
        selected_wallet = get_object_or_404(Wallet, id=selected_wallet_id, user=request.user)
        ledger_entries = Ledger.objects.filter(wallet=selected_wallet).order_by('-timestamp')

    return render(request, 'ledger.html', {
        'wallets': wallets,
        'selected_wallet': selected_wallet,
        'ledger_entries': ledger_entries,
    })

# --- Manager Views ---

def is_manager(user):
    return user.is_authenticated and user.role == 'manager'

@login_required
@user_passes_test(is_manager)
def pending_transactions(request):
    txs = Transaction.objects.filter(status='PENDING').order_by('-created_at')
    return render(request, 'manager/pending_transactions.html', {'transactions': txs})

def send_transaction_email(tx, wallet, approved=True):
    status_text = "Approved" if approved else "Rejected"
    emoji = "✅" if approved else "❌"

    subject = f"{emoji} Transaction {status_text}"
    message = (
        f"Dear {wallet.user.username},\n\n"
        f"Your {tx.tx_type.lower()} transaction has been {status_text.lower()}.\n\n"
        f"📌 Transaction ID: {tx.id}\n"
        f"💰 Amount: ₹{tx.amount}\n"
        f"💳 Wallet: {wallet.account_number}\n"
        f"📅 {status_text} At: {tx.processed_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"🔐 Status: {tx.status}\n\n"
        f"Thank you for using WalletApp.\n\n"
        f"- WalletApp Team"
    )

    send_mail(
        subject=subject,
        message=message,
        from_email='noreply@walletapp.com',
        recipient_list=[wallet.user.email],
        fail_silently=True
    )


@login_required
@user_passes_test(is_manager)
@db_transaction.atomic
def approve_transaction(request, tx_id):
    tx = get_object_or_404(Transaction, id=tx_id, status='PENDING')

    with db_transaction.atomic():
        tx.status = 'APPROVED'
        tx.approved_by = request.user
        tx.processed_at = now()

        wallet = Wallet.objects.select_for_update().get(pk=tx.wallet.pk)

        if tx.tx_type == 'DEPOSIT':
            wallet.balance += tx.amount
            wallet.unfreeze()
            wallet.save()
            Ledger.objects.create(
                transaction=tx,
                wallet=wallet,
                entry_type='credit',
                amount=tx.amount,
                balance_after=wallet.balance
            )

        elif tx.tx_type == 'WITHDRAW':
            wallet.balance -= tx.amount
            wallet.unfreeze(tx.amount)
            wallet.save()
            Ledger.objects.create(
                transaction=tx,
                wallet=wallet,
                entry_type='debit',
                amount=tx.amount,
                balance_after=wallet.balance
            )

            if tx.amount > 500000:
                FraudLog.objects.create(
                    user=wallet.user,
                    transaction=tx,
                    reason="Withdraw above ₹5L"
                )

        elif tx.tx_type == 'TRANSFER':
            target_wallet = Wallet.objects.select_for_update().get(pk=tx.target_wallet.pk)

            wallet.balance -= tx.amount
            wallet.unfreeze()
            wallet.save()

            target_wallet.balance += tx.converted_amount
            target_wallet.unfreeze()
            target_wallet.save()

            Ledger.objects.create(
                transaction=tx,
                wallet=wallet,
                entry_type='debit',
                amount=tx.amount,
                balance_after=wallet.balance
            )
            Ledger.objects.create(
                transaction=tx,
                wallet=target_wallet,
                entry_type='credit',
                amount=tx.converted_amount,
                balance_after=target_wallet.balance
            )

        tx.save()

    send_transaction_email(tx, wallet, approved=True)
    messages.success(request, "Transaction approved.")
    return redirect('pending_transactions')

@login_required
@user_passes_test(is_manager)
@db_transaction.atomic
def reject_transaction(request, tx_id):
    tx = get_object_or_404(Transaction, id=tx_id, status='PENDING')
    tx.status = 'REJECTED'
    tx.approved_by = request.user
    tx.processed_at = now()

    # Unfreeze only the frozen amount
    tx.wallet.unfreeze(tx.amount)

    if tx.tx_type == 'TRANSFER' and tx.target_wallet:
        tx.target_wallet.unfreeze(tx.converted_amount)

    tx.wallet.save()
    tx.save()

    send_transaction_email(tx, tx.wallet, approved=False)
    messages.info(request, "Transaction rejected.")
    return redirect('pending_transactions')



@login_required
@user_passes_test(is_manager)
def manager_dashboard(request):
    customers = CustomUser.objects.filter(role='user')
    wallets = Wallet.objects.all()
    pending_txs = Transaction.objects.filter(status='PENDING')
    fraud_logs = FraudLog.objects.all().order_by('-flagged_at')

    return render(request, 'manager/dashboard.html', {
        'customers': customers,
        'wallets': wallets,
        'pending_txs': pending_txs,
        'fraud_logs': fraud_logs,
    })




@staff_member_required  
def manager_transaction_history(request):
    wallets = Wallet.objects.all()
    selected_wallet_id = request.GET.get('wallet')
    transactions = Transaction.objects.all().select_related('wallet', 'target_wallet')

    if selected_wallet_id:
        transactions = transactions.filter(Q(wallet_id=selected_wallet_id) | Q(target_wallet_id=selected_wallet_id))

    return render(request, 'manager/transaction_history.html', {
        'transactions': transactions.order_by('-created_at'),
        'wallets': wallets,
        'selected_wallet_id': selected_wallet_id
    })




# Registration and Login with OTP
@ratelimit(key='ip', rate='5/m', block=True)
def register_view(request):
    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.generate_totp_secret()
            user.save()
            request.session['otp_user_id'] = user.id
            return redirect('verify_otp')
    else:
        form = UserRegisterForm()
    return render(request, 'register/register.html', {'form': form})

def verify_otp(request):
    user_id = request.session.get('otp_user_id')
    if not user_id:
        return redirect('register')
    user = get_object_or_404(CustomUser, id=user_id)
    if request.method == 'POST':
        form = OTPForm(request.POST)
        if form.is_valid():
            if user.verify_otp(form.cleaned_data['otp']):
                del request.session['otp_user_id']
                messages.success(request, "Account registered successfully.")
                return redirect('login')
            else:
                messages.error(request, "Invalid OTP.")
    else:
        form = OTPForm()
    uri = user.get_totp_uri()
    img = qrcode.make(uri)
    buffer = io.BytesIO()
    img.save(buffer, 'PNG')
    qr_data = base64.b64encode(buffer.getvalue()).decode()
    return render(request, 'register/verify_otp.html', {'form': form, 'qr_data': qr_data})

@ratelimit(key='ip', rate='5/m', block=True)
def custom_login_view(request):
    if request.method == 'POST':
        form = CustomLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('manager_dashboard' if user.role == 'manager' else 'dashboard_view')
        else:
            messages.error(request, "Invalid username or password.")
    else:
        form = CustomLoginForm()
    return render(request, 'register/login.html', {'form': form})




from django.contrib.auth.decorators import login_required, user_passes_test
from .models import LoginHistory

@login_required
def manager_login_history(request):
    logins = LoginHistory.objects.select_related('user').order_by('-login_time')
    return render(request, 'manager/login_history.html', {'logins': logins})