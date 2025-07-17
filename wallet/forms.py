from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser, Transaction, Wallet


# -------------------------------
# User Registration Form
# -------------------------------
class UserRegisterForm(UserCreationForm):
    role = forms.ChoiceField(
        choices=[('user', 'User'), ('manager', 'Manager')],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    phone_number = forms.CharField(
        max_length=15, required=False, widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    address = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        required=False
    )
    first_name = forms.CharField(
        required=False, widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    last_name = forms.CharField(
        required=False, widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    account_number = forms.CharField(
        label="Wallet Account Number (Users only)",
        help_text="Enter your wallet account number if you're registering as a user.",
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = CustomUser
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'phone_number', 'address', 'role', 'account_number',
            'password1', 'password2'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'
            field.help_text = ''  # Remove default help texts

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        acc_num = cleaned_data.get('account_number')

        if role == 'user' and not acc_num:
            self.add_error('account_number', 'Account number is required for users.')

        if role == 'manager':
            cleaned_data['account_number'] = None


# -------------------------------
# Login Form (Custom)
# -------------------------------
class CustomLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


# -------------------------------
# Deposit Form
# -------------------------------
class DepositForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['wallet', 'amount', 'note']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        self.fields['wallet'].queryset = Wallet.objects.filter(user=user)


# -------------------------------
# Withdraw Form
# -------------------------------
class WithdrawForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['wallet', 'amount', 'note']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        self.fields['wallet'].queryset = Wallet.objects.filter(user=user)

    def clean(self):
        cleaned_data = super().clean()
        wallet = cleaned_data.get('wallet')
        amount = cleaned_data.get('amount')
        if wallet and amount and wallet.balance < amount:
            self.add_error('amount', 'Insufficient balance')


# -------------------------------
# Transfer Form
# -------------------------------
# class TransferForm(forms.ModelForm):
#     class Meta:
#         model = Transaction
#         fields = ['wallet', 'target_wallet', 'amount', 'note']

#     def __init__(self, *args, **kwargs):
#         user = kwargs.pop('user')
#         super().__init__(*args, **kwargs)
#         self.fields['wallet'].queryset = Wallet.objects.filter(user=user)
#         self.fields['target_wallet'].queryset = Wallet.objects.exclude(user=user)

#     def clean(self):
#         cleaned_data = super().clean()
#         wallet = cleaned_data.get('wallet')
#         target = cleaned_data.get('target_wallet')
#         amount = cleaned_data.get('amount')
#         if wallet and amount and wallet.balance < amount:
#             self.add_error('amount', 'Insufficient balance')
#         if wallet == target:
#             self.add_error('target_wallet', 'Cannot transfer to the same wallet')
class TransferForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['wallet', 'target_wallet', 'amount', 'note']

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

        # User can transfer between their own wallets as well
        self.user = user
        self.fields['wallet'].queryset = Wallet.objects.filter(user=user)
        self.fields['target_wallet'].queryset = Wallet.objects.exclude(id__in=self.fields['wallet'].queryset.values_list('id', flat=True)) | Wallet.objects.filter(user=user)

    def clean(self):
        cleaned_data = super().clean()
        wallet = cleaned_data.get('wallet')
        target = cleaned_data.get('target_wallet')
        amount = cleaned_data.get('amount')

        # Prevent same wallet transfer
        if wallet and target and wallet.id == target.id:
            self.add_error('target_wallet', 'Cannot transfer to the same wallet')

        # Balance check
        if wallet and amount and wallet.balance < amount:
            self.add_error('amount', 'Insufficient balance')
        
        # Currency match validation if needed
        if wallet and target and wallet.currency != target.currency:
            # Optional: warn if cross-currency transfer not allowed
            pass

        return cleaned_data


# -------------------------------
# OTP Form (New)
# -------------------------------
class OTPForm(forms.Form):
    otp = forms.CharField(
        max_length=6,
        label='Enter OTP',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter 6-digit OTP',
        })
    )

