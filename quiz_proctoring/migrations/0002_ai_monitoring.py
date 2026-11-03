"""Opt-in AI monitoring policy and structured, reviewable browser-side model events."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('quiz_proctoring', '0001_initial')]

    operations = [
        migrations.AddField(model_name='proctoringpolicy', name='ai_enabled', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='proctoringpolicy', name='detect_multiple_faces', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='proctoringpolicy', name='detect_face_absence', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='proctoringpolicy', name='detect_head_movement', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='proctoringpolicy', name='detect_phone', field=models.BooleanField(default=True)),
        migrations.AddField(model_name='monitoringevent', name='source', field=models.CharField(max_length=8, choices=[('BROWSER','Browser / device'),('AI','Local AI model')], default='BROWSER')),
        migrations.AddField(model_name='monitoringevent', name='confidence', field=models.FloatField(null=True, blank=True)),
        migrations.AddField(model_name='monitoringevent', name='duration_seconds', field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddField(model_name='monitoringevent', name='observed_faces', field=models.PositiveSmallIntegerField(null=True, blank=True)),
        migrations.AlterField(model_name='monitoringevent', name='kind', field=models.CharField(max_length=24, choices=[
            ('TAB_HIDDEN','Exam tab hidden'),
            ('WINDOW_BLUR','Window focus lost'),
            ('FULLSCREEN_EXIT','Fullscreen exited'),
            ('CAMERA_LOST','Camera unavailable'),
            ('CAMERA_RESTORED','Camera restored'),
            ('MONITOR_ERROR','Monitoring interrupted'),
            ('NO_FACE','No face visible (model signal)'),
            ('MULTIPLE_FACES','Multiple faces detected (model signal)'),
            ('HEAD_TURNED','Sustained head-angle change (heuristic)'),
            ('PHONE_VISIBLE','Possible mobile phone visible (model signal)'),
        ])),
    ]
