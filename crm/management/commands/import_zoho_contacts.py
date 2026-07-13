import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm.models.contacts import Contact
from organizations.models import Workspace


STANDARD_MAP = {
    'First Name': 'first_name',
    'Last Name': 'last_name',
    'Email': 'email',
    'Secondary Email': 'secondary_email',
    'Phone': 'phone',
    'Mobile': 'mobile',
    'Mailing Street': 'mailing_street',
    'Mailing City': 'mailing_city',
    'Mailing State': 'mailing_state',
    'Mailing Zip': 'mailing_postal_code',
    'Lead Source': 'lead_source',
    'Status': 'status',
    'Description': 'description',
}

NEVER_IMPORT = {
    'Credit Card',
    'IP Address',
    'Contact Owner.id',
    'Created By.id',
    'Modified By.id',
    'Perfect Cleaning Last Contacted By.id',
    "Elaine's House Cleaning Last Contacted By.id",
    'Extra Help Pros Last Contacted By.id',
    'Elite Maids Last Contacted By.id',
    'Last Sale Closed By.id',
}


def as_bool(value):
    return str(value or '').strip().lower() in {'true', 'yes', '1', 'y'}


def fit_contact_field(field_name, value):
    value = str(value or '').strip()
    max_length = Contact._meta.get_field(field_name).max_length
    return value[:max_length] if max_length else value


class Command(BaseCommand):
    help = 'Import or update Zoho contacts into a workspace without creating accounts.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path')
        parser.add_argument('--workspace', required=True, help='Workspace slug')
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options['csv_path'])
        if not path.exists():
            raise CommandError(f'CSV file not found: {path}')
        workspace = Workspace.objects.filter(slug=options['workspace']).first()
        if not workspace:
            raise CommandError(f'Workspace not found: {options["workspace"]}')

        created = updated = skipped = 0
        seen_external_ids = set()
        with path.open('r', encoding='utf-8-sig', newline='') as source:
            reader = csv.DictReader(source)
            if 'Record Id' not in (reader.fieldnames or []):
                raise CommandError('Zoho Record Id column is required for a repeat-safe import.')
            for row_number, row in enumerate(reader, start=2):
                external_id = (row.get('Record Id') or '').strip()
                last_name = (row.get('Last Name') or '').strip()
                if not external_id or not last_name or external_id in seen_external_ids:
                    skipped += 1
                    continue
                seen_external_ids.add(external_id)

                values = {
                    model_field: fit_contact_field(model_field, row.get(csv_field))
                    for csv_field, model_field in STANDARD_MAP.items()
                }
                values.update({
                    'organization': workspace,
                    'account': None,
                    'email_opt_out': as_bool(row.get('Email Opt Out')),
                    'sms_opt_out': as_bool(row.get('SMS Opt Out')),
                })
                mapped = set(STANDARD_MAP) | {
                    'Record Id', 'Email Opt Out', 'SMS Opt Out', 'Credit Card',
                }
                zoho_fields = {
                    key: str(value).strip()
                    for key, value in row.items()
                    if key not in mapped and key not in NEVER_IMPORT and str(value or '').strip()
                }
                values['custom_data'] = {
                    'zoho_fields': zoho_fields,
                    'import': {'source': 'Zoho CRM', 'source_row': row_number},
                }

                _, was_created = Contact.objects.update_or_create(
                    organization=workspace,
                    external_source='zoho',
                    external_id=external_id,
                    defaults=values,
                )
                if was_created:
                    created += 1
                else:
                    updated += 1

        if options['dry_run']:
            transaction.set_rollback(True)
        mode = 'DRY RUN' if options['dry_run'] else 'IMPORTED'
        self.stdout.write(self.style.SUCCESS(
            f'{mode}: created={created}, updated={updated}, skipped={skipped}, workspace={workspace.slug}'
        ))
