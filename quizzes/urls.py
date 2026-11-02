from django.urls import path
from . import views

app_name = 'quizzes'
urlpatterns = [
    path('', views.quiz_list, name='list'),
    path('classes/<int:section_pk>/<str:year>/<str:term>/', views.class_courses, name='class_courses'),
    path('courses/<int:offering_pk>/', views.course_quizzes, name='course_quizzes'),
    path('courses/<int:offering_pk>/create/', views.quiz_create, name='create'),
    path('<int:pk>/', views.quiz_detail, name='detail'),
    path('<int:pk>/edit/', views.quiz_edit, name='edit'),
    path('<int:pk>/questions/add/', views.question_add, name='question_add'),
    path('<int:pk>/questions/<int:question_pk>/edit/', views.question_edit, name='question_edit'),
    path('<int:pk>/questions/<int:question_pk>/delete/', views.question_delete, name='question_delete'),
    path('<int:pk>/publish/', views.publish, name='publish'),
    path('<int:pk>/close/', views.close, name='close'),
    path('<int:pk>/delete/', views.delete_draft, name='delete_draft'),
    path('<int:pk>/release-results/', views.release_results, name='release_results'),
    path('<int:pk>/start/', views.start, name='start'),
    path('<int:pk>/take/', views.take, name='take'),
    path('<int:pk>/answer/', views.answer, name='answer'),
    path('<int:pk>/submit/', views.submit, name='submit'),
    path('<int:pk>/result/', views.result, name='result'),
    path('<int:pk>/roster/', views.roster, name='roster'),
]
