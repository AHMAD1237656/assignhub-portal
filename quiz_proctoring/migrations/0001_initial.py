from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ('quizzes', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='ProctoringPolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=False)),
                ('require_camera', models.BooleanField(default=True)),
                ('log_browser_events', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('quiz', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='proctoring_policy', to='quizzes.quiz')),
            ],
        ),
        migrations.CreateModel(
            name='MonitoringSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('consent_at', models.DateTimeField()),
                ('camera_check_claimed', models.BooleanField(default=False)),
                ('started_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('last_heartbeat_at', models.DateTimeField(blank=True, null=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('attempt', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='monitoring_session', to='quizzes.quizattempt')),
            ],
        ),
        migrations.CreateModel(
            name='MonitoringEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('TAB_HIDDEN', 'Exam tab hidden'), ('WINDOW_BLUR', 'Window focus lost'), ('FULLSCREEN_EXIT', 'Fullscreen exited'), ('CAMERA_LOST', 'Camera unavailable'), ('CAMERA_RESTORED', 'Camera restored'), ('MONITOR_ERROR', 'Monitoring interrupted')], max_length=24)),
                ('review_status', models.CharField(choices=[('PENDING', 'Needs review'), ('REVIEWED', 'Reviewed'), ('DISMISSED', 'Dismissed')], default='PENDING', max_length=12)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_exam_events', to=settings.AUTH_USER_MODEL)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='events', to='quiz_proctoring.monitoringsession')),
            ],
            options={'ordering': ['-created_at', '-pk']},
        ),
        migrations.AddIndex(model_name='monitoringevent', index=models.Index(fields=['session', '-created_at'], name='ah_proctor_events_idx')),
    ]
