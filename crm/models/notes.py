from builtins import property as builtin_property

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from organizations.models import Workspace

from .contacts import Account, Contact, Property


class CRMNote(models.Model):
    TARGET_CHOICES = [
        ('contact', 'Contact'),
        ('account', 'Account'),
        ('property', 'Property'),
        ('job', 'Job'),
    ]
    CATEGORY_CHOICES = [
        ('general', 'General'),
        ('service', 'Service'),
        ('access', 'Access'),
        ('billing', 'Billing'),
        ('safety', 'Safety'),
    ]
    VISIBILITY_CHOICES = [
        ('internal', 'Internal only'),
        ('customer', 'Customer visible'),
    ]

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='crm_notes')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='crm_notes',
    )
    target_type = models.CharField(max_length=20, choices=TARGET_CHOICES)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    job = models.ForeignKey('fsm.Job', on_delete=models.CASCADE, null=True, blank=True, related_name='notes')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='internal')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['workspace', 'target_type', 'created_at']),
        ]

    def clean(self):
        targets = {
            'account': self.account,
            'contact': self.contact,
            'property': self.property,
            'job': self.job,
        }
        if not targets.get(self.target_type):
            raise ValidationError({self.target_type: 'Choose the record this note is about.'})
        if sum(value is not None for value in targets.values()) != 1:
            raise ValidationError('A note must have exactly one target.')

    @builtin_property
    def target_object(self):
        return getattr(self, self.target_type, None)

    def __str__(self):
        return f'{self.get_target_type_display()}: {self.body[:60]}'
