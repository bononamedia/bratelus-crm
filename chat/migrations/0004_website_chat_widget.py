import uuid

import django.db.models.deletion
from django.db import migrations, models


def populate_visitor_keys(apps, schema_editor):
    conversation_model = apps.get_model('chat', 'ChatConversation')
    for conversation in conversation_model.objects.filter(visitor_key__isnull=True).iterator():
        conversation.visitor_key = uuid.uuid4()
        conversation.save(update_fields=['visitor_key'])


class Migration(migrations.Migration):
    dependencies = [
        ('chat', '0003_chatparticipant_archived_at'),
        ('crm', '0006_crm_archive'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatconversation',
            name='contact',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='chat_conversations',
                to='crm.contact',
            ),
        ),
        migrations.AddField(
            model_name='chatconversation',
            name='visitor_key',
            field=models.UUIDField(editable=False, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='chatconversation',
            name='visitor_page_url',
            field=models.URLField(blank=True, max_length=1000),
        ),
        migrations.CreateModel(
            name='WebsiteChatWidget',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_key', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('is_enabled', models.BooleanField(default=False)),
                ('brand_color', models.CharField(default='#2563eb', max_length=7)),
                ('greeting', models.CharField(default='Hi! How can our team help you today?', max_length=180)),
                ('require_email', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('workspace', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='website_chat_widget', to='organizations.workspace')),
            ],
        ),
        migrations.RunPython(populate_visitor_keys, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='chatconversation',
            name='visitor_key',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
