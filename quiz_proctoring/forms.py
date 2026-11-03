from django import forms
from .models import ProctoringPolicy


class PolicyForm(forms.ModelForm):
    class Meta:
        model = ProctoringPolicy
        fields = ['enabled', 'require_camera', 'log_browser_events']
        labels = {
            'enabled': 'Enable monitoring for this quiz',
            'require_camera': 'Require webcam device check and live preview',
            'log_browser_events': 'Record tab, focus, and fullscreen events',
        }
        help_texts = {
            'enabled': 'Existing quizzes stay unmonitored unless explicitly enabled.',
            'require_camera': 'A browser webcam check is not a cryptographic device attestation.',
            'log_browser_events': 'These events are reported by the browser and are not proof of misconduct.',
        }
