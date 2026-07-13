import os
from django.core.management.base import BaseCommand
from django.apps import apps

class Command(BaseCommand):
    help = 'Generates a markdown file of the entire database architecture'

    def handle(self, *args, **options):
        output = "# Bratelus Database Architecture\n\n"
        output += "> *This document is auto-generated directly from the Django models.*\n\n"
        
        # Only document our custom SaaS apps
        target_apps = ['workspaces', 'crm', 'fsm', 'finance']

        for app_name in target_apps:
            output += f"## Module: {app_name.upper()}\n\n"
            
            try:
                app_config = apps.get_app_config(app_name)
            except LookupError:
                continue

            for model in app_config.get_models():
                output += f"### {model.__name__}\n"
                output += "| Field Name | Data Type | Details / Relationships |\n"
                output += "|------------|-----------|-------------------------|\n"

                for field in model._meta.get_fields():
                    # Get the field type safely
                    field_type = field.get_internal_type() if hasattr(field, 'get_internal_type') else type(field).__name__
                    
                    # If it's a foreign key, show where it points
                    details = ""
                    if field.is_relation and hasattr(field, 'related_model') and field.related_model:
                        details = f"→ {field.related_model.__name__}"
                    
                    output += f"| `{field.name}` | {field_type} | {details} |\n"
                
                output += "\n"

        # Save to the root directory
        filepath = os.path.join(os.getcwd(), 'ARCHITECTURE.md')
        with open(filepath, 'w') as f:
            f.write(output)

        self.stdout.write(self.style.SUCCESS(f'Successfully generated {filepath}!'))