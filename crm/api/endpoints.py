from rest_framework import generics
from crm.models import Account, Contact
from crm.serializers import AccountSerializer, ContactSerializer

class AccountListCreateAPI(generics.ListCreateAPIView):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer

class ContactListCreateAPI(generics.ListCreateAPIView):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer