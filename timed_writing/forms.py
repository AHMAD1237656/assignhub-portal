from django import forms

from .models import TimedWritingConfig


class TimedWritingConfigForm(forms.ModelForm):

    class Meta:
        model = TimedWritingConfig

        fields = [
            "duration_minutes",
            "is_enabled",
        ]

        widgets = {
            "duration_minutes": forms.NumberInput(
                attrs={
                    "min": 1,
                    "max": 240,
                    "class": "form-control",
                }
            ),
            "is_enabled": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }