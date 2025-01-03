from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.utils import timezone
from django.shortcuts import get_object_or_404,render, redirect
from django.views import View
from django.http import HttpResponse
from django.views.generic import CreateView, ListView
from transactions.constants import DEPOSIT, WITHDRAWAL,LOAN, LOAN_PAID
from datetime import datetime
from django.db.models import Sum
from transactions.forms import (
    DepositForm,
    WithdrawForm,
    LoanRequestForm,
)
from accounts.models import UserBankAccount
from transactions.models import Transaction, Transfer, BankStatus
from decimal import Decimal
from django.core.mail import EmailMessage, EmailMultiAlternatives, send_mail
from django.template.loader import render_to_string
from django.conf import settings

def send_transaction_email(user, amount, subject, template):
    from_email = settings.EMAIL_HOST_USER  
    message = render_to_string(template, {
        'user': user,
        'amount': amount,
    })
    send_email = EmailMultiAlternatives(
        subject,
        '',
        from_email=from_email,
        to=[user.email]
    )
    send_email.attach_alternative(message, "text/html")
    send_email.send()

 
class TransactionCreateMixin(LoginRequiredMixin, CreateView):
    template_name = 'transactions/transaction_form.html'
    model = Transaction
    title = ''
    success_url = reverse_lazy('transaction_report')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({
            'account': self.request.user.account
        })
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': self.title
        })
        return context


class DepositMoneyView(TransactionCreateMixin):
    form_class = DepositForm
    title = 'Deposit'

    def get_initial(self):
        initial = {'transaction_type': DEPOSIT}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        account = self.request.user.account
        account.balance += amount 
        account.save(
            update_fields=[
                'balance'
            ]
        )
        messages.success(
            self.request,
            f'{"{:,.2f}".format(float(amount))}$ was deposited to your account successfully'
        )
        send_transaction_email(self.request.user, amount, "Deposite Message", "transactions/deposite_email.html")
        return super().form_valid(form)


class WithdrawMoneyView(TransactionCreateMixin):
    form_class = WithdrawForm
    title = 'Withdraw Money'

    def get_initial(self):
        initial = {'transaction_type': WITHDRAWAL}
        return initial

    def form_valid(self, form):
        bank_status = BankStatus.objects.first()
        if not bank_status or bank_status.is_bankrupt:
            messages.error(self.request, "Bank has been bankrupted. Withdrawals are not possible.")
            return redirect('withdraw_money')  
        
        amount = form.cleaned_data.get('amount')
        if self.request.user.account.balance < amount:
            messages.error(self.request, "Insufficient balance.")
            return redirect('withdraw_money')  

        self.request.user.account.balance -= form.cleaned_data.get('amount')
        self.request.user.account.save(update_fields=['balance'])

        messages.success(
            self.request,
            f'Successfully withdrawn {"{:,.2f}".format(float(amount))}$ from your account'
        )
        send_transaction_email(self.request.user, amount, "Withdrawal Message", "transactions/withdrawal_email.html")
        return super().form_valid(form)

class LoanRequestView(TransactionCreateMixin):
    form_class = LoanRequestForm
    title = 'Request For Loan'

    def get_initial(self):
        initial = {'transaction_type': LOAN}
        return initial

    def form_valid(self, form):
        amount = form.cleaned_data.get('amount')
        current_loan_count = Transaction.objects.filter(
            account=self.request.user.account,transaction_type=3,loan_approve=True).count()
        if current_loan_count >= 3:
            return HttpResponse("You have cross the loan limits")
        messages.success(
            self.request,
            f'Loan request for {"{:,.2f}".format(float(amount))}$ submitted successfully'
        )
        send_transaction_email(self.request.user, amount, "Loan Request Message", "transactions/loan_email.html")
        return super().form_valid(form)
    
class TransactionReportView(LoginRequiredMixin, ListView):
    template_name = 'transactions/transaction_report.html'
    model = Transaction
    balance = 0
    
    def get_queryset(self):
        queryset = super().get_queryset().filter(
            account=self.request.user.account
        )
        start_date_str = self.request.GET.get('start_date')
        end_date_str = self.request.GET.get('end_date')
        
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            queryset = queryset.filter(timestamp__date__gte=start_date, timestamp__date__lte=end_date)
            self.balance = Transaction.objects.filter(
                timestamp__date__gte=start_date, timestamp__date__lte=end_date
            ).aggregate(Sum('amount'))['amount__sum']
        else:
            self.balance = self.request.user.account.balance
       
        return queryset.distinct() 
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'account': self.request.user.account
        })

        return context
    
        
class PayLoanView(LoginRequiredMixin, View):
    def get(self, request, loan_id):
        loan = get_object_or_404(Transaction, id=loan_id)
        print(loan)
        if loan.loan_approve:
            user_account = loan.account
            
            if loan.amount < user_account.balance:
                user_account.balance -= loan.amount
                loan.balance_after_transaction = user_account.balance
                user_account.save()
                loan.loan_approved = True
                loan.transaction_type = LOAN_PAID
                loan.save()
                return redirect('transactions:loan_list')
            else:
                messages.error(
            self.request,
            f'Loan amount is greater than available balance'
        )

        return redirect('loan_list')


class LoanListView(LoginRequiredMixin,ListView):
    model = Transaction
    template_name = 'transactions/loan_request.html'
    context_object_name = 'loans' 
    
    def get_queryset(self):
        user_account = self.request.user.account
        queryset = Transaction.objects.filter(account=user_account,transaction_type=3)
        print(queryset)
        return queryset
    
class TransferMoneyView(LoginRequiredMixin, View):
    def post(self, request):
        sender = request.user.account 
        receiver_account_no = request.POST.get('receiver_account_no')
        amount = float(request.POST.get('amount'))

        try:
            receiver = UserBankAccount.objects.get(account_no=receiver_account_no)
        except UserBankAccount.DoesNotExist:
            messages.error(request, "Account does not exist.")
            return redirect('transfer_money')

        if sender.balance < amount:
            messages.error(request, "Insufficient balance.")
            return redirect('transfer_money')

        sender.balance -= Decimal(amount)
        receiver.balance += Decimal(amount)
        sender.save(update_fields=['balance'])
        receiver.save(update_fields=['balance'])

        Transfer.objects.create(sender=sender, receiver=receiver, amount=amount)

        send_transaction_email(
            request.user, 
            amount,
            "Transfer Confirmation",
            "transactions/transfer_email_sender.html"
        )
        if receiver.user.email:  
            send_transaction_email(
                receiver.user, 
                amount,
                "You've Received Money",
                "transactions/transfer_email_receiver.html"
            )
        messages.success(request, f"Successfully transferred ${'{:,.2f}'.format(amount)} to account {receiver_account_no}.")
        return redirect('transaction_report')
    def get(self, request):
        return render(request, 'transactions/transfer_money.html')

