from django import forms
from .models import ProctoringPolicy


class PolicyForm(forms.ModelForm):
    class Meta:
        model = ProctoringPolicy
        fields = ['enabled', 'require_camera', 'log_browser_events', 'ai_enabled', 'detect_multiple_faces', 'detect_face_absence', 'detect_head_movement', 'detect_phone']
        labels = {
            'enabled': 'Enable monitoring for this quiz',
            'require_camera': 'Require webcam device check and live preview',
            'log_browser_events': 'Record tab, focus, and fullscreen events',
            'ai_enabled': 'Enable local AI monitoring (experimental)',
            'detect_multiple_faces': 'Flag multiple faces in camera view',
            'detect_face_absence': 'Flag prolonged face absence',
            'detect_head_movement': 'Flag sustained head-angle deviations',
            'detect_phone': 'Flag possible mobile phones in camera view',
        }
        help_texts = {
            'enabled': 'Existing quizzes stay unmonitored unless explicitly enabled.',
            'require_camera': 'A browser webcam check is not a cryptographic device attestation.',
            'log_browser_events': 'These events are reported by the browser and are not proof of misconduct.',
            'ai_enabled': 'Runs MediaPipe and COCO-SSD on the student device; requires webcam, internet for model downloads, and teacher review. No video is uploaded.',
            'detect_multiple_faces': 'Face Landmarker counts up to four visible faces; repeated detection creates a review flag.',
            'detect_face_absence': 'Flags sustained missing-face periods; camera framing can cause false positives.',
            'detect_head_movement': 'Experimental head-angle heuristic, not eye tracking; do not treat as misconduct proof.',
            'detect_phone': 'COCO-SSD cell-phone class; can miss small/occluded phones or flag similar objects.',
        }


    def clean(self):
        values = super().clean()
        if values.get('ai_enabled'):
            if not values.get('enabled'):
                self.add_error('enabled', 'Enable exam monitoring before enabling AI.')
            if not values.get('require_camera'):
                self.add_error('require_camera', 'A webcam is required for local AI analysis.')
            if not any(values.get(flag) for flag in (
                'detect_multiple_faces', 'detect_face_absence',
                'detect_head_movement', 'detect_phone',
            )):
                self.add_error('ai_enabled', 'Enable at least one AI detection option.')
        return values
