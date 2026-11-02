from django.contrib import admin
from .models import Quiz, QuizQuestion, QuizAttempt, QuizAnswer


class ReadOnlyQuizAdmin(admin.ModelAdmin):
    """All quiz writes go through teacher-owned application workflows."""
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Quiz)
class QuizAdmin(ReadOnlyQuizAdmin):
    list_display = ('title', 'created_by', 'course_offering', 'status', 'closes_at')
    list_filter = ('status',)
    search_fields = ('title', 'created_by__username')


@admin.register(QuizQuestion)
class QuestionAdmin(ReadOnlyQuizAdmin):
    list_display = ('quiz', 'order', 'points')


@admin.register(QuizAttempt)
class AttemptAdmin(ReadOnlyQuizAdmin):
    list_display = ('quiz', 'student', 'status', 'earned_marks', 'total_marks')
    list_filter = ('status',)


@admin.register(QuizAnswer)
class AnswerAdmin(ReadOnlyQuizAdmin):
    list_display = ('attempt', 'question', 'selected_choice')
