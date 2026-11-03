from django.urls import path
from . import views

app_name = 'quiz_proctoring'
urlpatterns = [
    path('', views.classes, name='classes'),
    path('classes/<int:section_pk>/<str:year>/<str:term>/', views.class_courses, name='class_courses'),
    path('courses/<int:offering_pk>/', views.course_quizzes, name='course_quizzes'),
    path('quizzes/<int:quiz_pk>/', views.quiz_monitoring, name='quiz_monitoring'),
    path('quizzes/<int:quiz_pk>/settings/', views.settings, name='settings'),
    path('quizzes/<int:quiz_pk>/device-check/', views.device_check, name='device_check'),
    path('quizzes/<int:quiz_pk>/heartbeat/', views.heartbeat, name='heartbeat'),
    path('quizzes/<int:quiz_pk>/event/', views.record_event, name='event'),
    path('attempts/<int:attempt_pk>/', views.attempt_events, name='attempt_events'),
    path('events/<int:event_pk>/review/', views.review_event, name='review_event'),
]
