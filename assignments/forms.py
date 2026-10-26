from django import forms

from .models import Assignment, Submission


class AssignmentForm(forms.ModelForm):

    class Meta:
        model = Assignment
        fields = (
            "title",
            "instructions",
            "attachment",
            "deadline",
            "total_marks",
            "rubric",
            "status",
        )

        widgets = {
            "instructions": forms.Textarea(
                attrs={
                    "rows": 6,
                    "class": "form-control",
                }
            ),

            "rubric": forms.Textarea(
                attrs={
                    "rows": 5,
                    "class": "form-control",
                }
            ),

            "deadline": forms.DateTimeInput(
                attrs={
                    "type": "datetime-local",
                    "class": "form-control",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            if name not in ("instructions", "rubric", "deadline"):
                field.widget.attrs["class"] = "form-control"


class SubmissionForm(forms.ModelForm):

    class Meta:
        model = Submission

        fields = (
            "text_content",
            "submission_file",
        )

        widgets = {
            "text_content": forms.Textarea(
                attrs={
                    "rows": 12,
                    "class": "form-control",
                    "placeholder": "Write your answer here...",
                }
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        text_content = cleaned_data.get("text_content")
        submission_file = cleaned_data.get("submission_file")

        if not text_content and not submission_file:
            raise forms.ValidationError(
                "Please provide a written answer or upload a file."
            )

        return cleaned_data


class GradeSubmissionForm(forms.ModelForm):

    class Meta:
        model = Submission

        fields = (
            "marks",
            "feedback",
        )

        widgets = {
            "marks": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                }
            ),

            "feedback": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 6,
                }
            ),
        }