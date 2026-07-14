import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('chat', '0001_initial')]
    operations = [
        migrations.AddField(
            model_name='chatparticipant', name='unread_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name='WebPushSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('endpoint', models.URLField(max_length=1000, unique=True)),
                ('p256dh', models.CharField(max_length=255)),
                ('auth', models.CharField(max_length=255)),
                ('user_agent', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_push_subscriptions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-updated_at',)},
        ),
    ]
