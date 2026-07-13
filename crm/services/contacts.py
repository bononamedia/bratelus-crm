from copy import deepcopy

from django.db import transaction

from crm.models.contacts import Account, Contact, PaymentMethod, Property


COPY_FIELDS = (
    'first_name', 'last_name', 'email', 'secondary_email', 'phone', 'mobile',
    'mailing_street', 'mailing_city', 'mailing_state', 'mailing_postal_code',
    'mailing_country', 'lead_source', 'status', 'description', 'email_opt_out',
    'sms_opt_out', 'external_source', 'external_id', 'is_primary',
)


def contact_copy_values(source, target_workspace):
    custom_data = deepcopy(source.custom_data or {})
    custom_data['duplication'] = {
        'source_contact_id': source.id,
        'source_workspace_id': str(source.organization_id),
        'source_workspace_name': source.organization.name,
    }
    values = {field: getattr(source, field) for field in COPY_FIELDS}
    values.update({
        'organization': target_workspace,
        'account': None,
        'custom_data': custom_data,
    })
    return values


def existing_contact_copy(source, target_workspace):
    queryset = Contact.objects.filter(organization=target_workspace)
    if source.external_id:
        return queryset.filter(
            external_source=source.external_source,
            external_id=source.external_id,
        ).first()
    return queryset.filter(
        custom_data__duplication__source_contact_id=source.id,
    ).first()


def duplicate_contact(source, target_workspace):
    if source.organization_id == target_workspace.id:
        return source, False
    existing = existing_contact_copy(source, target_workspace)
    if existing:
        return existing, False
    return Contact.objects.create(**contact_copy_values(source, target_workspace)), True


ACCOUNT_COPY_FIELDS = (
    'name', 'phone', 'email', 'website', 'billing_address', 'billing_street',
    'billing_city', 'billing_state', 'billing_postal_code', 'billing_country',
    'shipping_street', 'shipping_city', 'shipping_state', 'shipping_postal_code',
    'shipping_country',
)


def existing_account_copy(source, target_workspace):
    return Account.objects.filter(
        organization=target_workspace,
        custom_data__duplication__source_account_id=source.id,
    ).first()


@transaction.atomic
def duplicate_account_bundle(source, target_workspace):
    if source.organization_id == target_workspace.id:
        return source, False, {'contacts': 0, 'properties': 0, 'payment_methods': 0}
    existing = existing_account_copy(source, target_workspace)
    if existing:
        return existing, False, {
            'contacts': existing.contacts.count(),
            'properties': existing.properties.count(),
            'payment_methods': existing.payment_methods.count(),
        }

    custom_data = deepcopy(source.custom_data or {})
    custom_data['duplication'] = {
        'source_account_id': source.id,
        'source_workspace_id': str(source.organization_id),
        'source_workspace_name': source.organization.name,
    }
    values = {field: getattr(source, field) for field in ACCOUNT_COPY_FIELDS}
    target_account = Account.objects.create(
        organization=target_workspace,
        custom_data=custom_data,
        **values,
    )

    contact_count = 0
    for source_contact in source.contacts.select_related('organization'):
        target_contact, was_created = duplicate_contact(source_contact, target_workspace)
        if target_contact.account_id is None:
            target_contact.account = target_account
            target_contact.save(update_fields=['account'])
        contact_count += int(was_created or target_contact.account_id == target_account.id)

    property_map = {}
    for source_property in source.properties.all():
        property_data = deepcopy(source_property.custom_data or {})
        property_data['duplication'] = {
            'source_property_id': source_property.id,
            'source_workspace_id': str(source.organization_id),
        }
        target_property = Property.objects.create(
            account=target_account,
            name=source_property.name,
            address=source_property.address,
            unit_number=source_property.unit_number,
            gate_code=source_property.gate_code,
            location_lat=source_property.location_lat,
            location_lng=source_property.location_lng,
            custom_data=property_data,
        )
        property_map[source_property.id] = target_property

    payment_count = 0
    for source_method in source.payment_methods.all():
        PaymentMethod.objects.create(
            account=target_account,
            is_default=source_method.is_default,
            assigned_property=property_map.get(source_method.assigned_property_id),
            card_type=source_method.card_type,
            last_four=source_method.last_four,
            processor_token='',
            expiration_date=source_method.expiration_date,
        )
        payment_count += 1

    return target_account, True, {
        'contacts': contact_count,
        'properties': len(property_map),
        'payment_methods': payment_count,
    }
