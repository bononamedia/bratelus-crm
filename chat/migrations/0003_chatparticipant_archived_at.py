from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('chat', '0002_chat_notifications')]

    operations = [
        migrations.AddField(
            model_name='chatparticipant',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
