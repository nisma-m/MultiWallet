from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='dashboard_view'),
    path('deposit/', views.deposit_view, name='deposit_view'),
    path('withdraw/', views.withdraw_view, name='withdraw_view'),
    path('transfer/', views.transfer_view, name='transfer_view'),
    path('ledger/', views.ledger_view, name='ledger_view'),
    path('transactions/pending/', views.pending_transactions, name='pending_transactions'),
    path('transactions/approve/<int:tx_id>/', views.approve_transaction, name='approve_transaction'),
    path('transactions/reject/<int:tx_id>/', views.reject_transaction, name='reject_transaction'),

    path('manager/', views.manager_dashboard, name='manager_dashboard'),
    path('manager/transactions/', views.manager_transaction_history, name='manager_transaction_history'),
    path('manager/approvals/', views.pending_transactions, name='pending_transactions'),
    path('manager/login-history/', views.manager_login_history, name='manager_login_history'),



    

    # path('login/', auth_views.LoginView.as_view(template_name='register/login.html'), name='login'),
    path('login/', views.custom_login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('register/', views.register_view, name='register_view'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),


]



