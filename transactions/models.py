from django.db import models
from accounts.models import UserBankAccount
# Create your models here.
from .constants import TRANSACTION_TYPE

class Transaction(models.Model):
    account = models.ForeignKey(UserBankAccount, related_name = 'transactions', on_delete = models.CASCADE) 
    
    amount = models.DecimalField(decimal_places=2, max_digits = 12)
    balance_after_transaction = models.DecimalField(decimal_places=2, max_digits = 12)
    transaction_type = models.IntegerField(choices=TRANSACTION_TYPE, null = True)
    timestamp = models.DateTimeField(auto_now_add=True)
    loan_approve = models.BooleanField(default=False) 
    
    class Meta:
        ordering = ['timestamp'] 

class Transfer(models.Model):
    sender = models.ForeignKey(UserBankAccount, related_name="sent_transfers", on_delete=models.CASCADE)
    receiver = models.ForeignKey(UserBankAccount, related_name="received_transfers", on_delete=models.CASCADE)
    amount = models.DecimalField(decimal_places=2, max_digits=12)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Transfer from {self.sender.account_no} to {self.receiver.account_no} of {self.amount} at {self.timestamp}"
    
class BankStatus(models.Model):
    is_bankrupt = models.BooleanField(default=False)

    def __str__(self):
        return "Bank is bankrupt" if self.is_bankrupt else "Bank is operational"