from django import forms
from django.core.exceptions import ValidationError
from .models import Quiz, QuizQuestion


class QuizForm(forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ['title', 'instructions', 'opens_at', 'closes_at', 'duration_minutes', 'show_results']
        widgets = {
            'opens_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'closes_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'instructions': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['opens_at'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        self.fields['closes_at'].input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S']
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control' if not isinstance(field.widget, forms.CheckboxInput) else 'form-check-input'

    def clean(self):
        values = super().clean()
        if values.get('opens_at') and values.get('closes_at') and values['opens_at'] >= values['closes_at']:
            self.add_error('closes_at', 'Closing must be later than opening.')
        return values


class QuestionForm(forms.ModelForm):
    class Meta:
        model = QuizQuestion
        fields = ['text', 'option_a', 'option_b', 'option_c', 'option_d', 'correct_choice', 'points', 'order']
        widgets = {'text': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean(self):
        values = super().clean()
        opts = [values.get(f'option_{x}', '').strip().casefold() for x in 'abcd']
        if all(opts) and len(set(opts)) != 4:
            raise ValidationError('All four answer choices must be distinct.')
        return values
