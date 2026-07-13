from rest_framework import serializers
from .models import Account, Contact

class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = '__all__'

class ContactSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source='account.name', read_only=True)

    class Meta:
        model = Contact
        fields = ['id', 'account', 'account_name', 'first_name', 'last_name', 'email', 'phone', 'is_primary']