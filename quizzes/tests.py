"""Quiz regression tests; run: python manage.py test quizzes"""
from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from assignments.tests import AssignmentTestBase
from courses.models import CourseOffering, CourseEnrollment
from .models import Quiz, QuizQuestion, QuizAttempt, QuizAnswer
from .services import refresh


class QuizWorkflowTests(AssignmentTestBase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.quiz = Quiz.objects.create(
            course_offering=self.offering, created_by=self.teacher, title='Python Midterm',
            opens_at=now - timedelta(minutes=5), closes_at=now + timedelta(hours=2),
            duration_minutes=30, status=Quiz.Status.DRAFT,
        )
        self.q1 = QuizQuestion.objects.create(
            quiz=self.quiz, text='What does len() return?', option_a='Length',
            option_b='File', option_c='String', option_d='Path', correct_choice='A', points=2,
        )
        self.q2 = QuizQuestion.objects.create(
            quiz=self.quiz, text='What is 2 + 2?', option_a='1', option_b='2',
            option_c='4', option_d='8', correct_choice='C', points=3, order=2,
        )
        self.quiz.status = Quiz.Status.PUBLISHED
        self.quiz.save(update_fields=['status'])

    def u(self, name, *args):
        return reverse('quizzes:' + name, args=args)

    def test_teacher_sees_own_quiz_not_other_teacher(self):
        self.client.force_login(self.teacher2)
        self.assertNotContains(self.client.get(self.u('list')), 'Python Midterm')
        self.assertEqual(self.client.get(self.u('detail', self.quiz.pk)).status_code, 403)

    def test_student_requires_active_enrollment(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.u('detail', self.quiz.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.u('take', self.quiz.pk)).status_code, 404)  # must start first
        self.client.force_login(self.teacher2)
        self.assertEqual(self.client.post(self.u('start', self.quiz.pk)).status_code, 403)

    def test_teacher_cannot_edit_after_publication(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(self.u('edit', self.quiz.pk)).status_code, 403)
        self.assertEqual(self.client.post(self.u('question_delete', self.quiz.pk, self.q1.pk)).status_code, 403)

    def test_single_attempt_server_timer_and_correct_marking(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(self.u('start', self.quiz.pk)).status_code, 302)
        self.assertEqual(self.client.post(self.u('start', self.quiz.pk)).status_code, 302)
        self.assertEqual(QuizAttempt.objects.filter(quiz=self.quiz, student=self.student).count(), 1)
        take = self.client.get(self.u('take', self.quiz.pk))
        self.assertEqual(take.status_code, 200)
        self.assertNotContains(take, 'Correct answer:')
        self.assertNotContains(take, 'correct_choice')
        self.assertTrue(self.client.post(self.u('answer', self.quiz.pk), {'question_id': self.q1.pk, 'choice': 'A'}).json()['saved'])
        self.assertTrue(self.client.post(self.u('answer', self.quiz.pk), {'question_id': self.q2.pk, 'choice': 'B'}).json()['saved'])
        self.client.post(self.u('submit', self.quiz.pk))
        attempt = QuizAttempt.objects.get(quiz=self.quiz, student=self.student)
        self.assertEqual(attempt.status, QuizAttempt.Status.SUBMITTED)
        self.assertEqual((attempt.earned_marks, attempt.total_marks), (2, 5))
        self.assertEqual(self.client.post(self.u('answer', self.quiz.pk), {'question_id': self.q1.pk, 'choice': 'B'}).status_code, 409)

    def test_question_from_other_quiz_rejected(self):
        other = Quiz.objects.create(course_offering=self.offering, created_by=self.teacher, title='Other Quiz',
                                    opens_at=self.quiz.opens_at, closes_at=self.quiz.closes_at, duration_minutes=30)
        question = QuizQuestion.objects.create(quiz=other, text='secret?', option_a='A', option_b='B', option_c='C', option_d='D', correct_choice='A')
        self.client.force_login(self.student)
        self.client.post(self.u('start', self.quiz.pk))
        response = self.client.post(self.u('answer', self.quiz.pk), {'question_id': question.pk, 'choice': 'A'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(QuizAnswer.objects.exists())

    def test_expired_attempt_scores_saved_choices_and_cannot_resume(self):
        self.client.force_login(self.student)
        self.client.post(self.u('start', self.quiz.pk))
        self.client.post(self.u('answer', self.quiz.pk), {'question_id': self.q1.pk, 'choice': 'A'})
        attempt = QuizAttempt.objects.get(quiz=self.quiz, student=self.student)
        QuizAttempt.objects.filter(pk=attempt.pk).update(expires_at=timezone.now() - timedelta(seconds=2))
        self.assertEqual(self.client.get(self.u('take', self.quiz.pk)).status_code, 302)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, QuizAttempt.Status.AUTO_SUBMITTED)
        self.assertEqual(attempt.earned_marks, 2)
        self.assertEqual(self.client.post(self.u('start', self.quiz.pk)).status_code, 302)
        self.assertEqual(QuizAttempt.objects.filter(quiz=self.quiz, student=self.student).count(), 1)

    def test_student_cannot_see_results_while_unreleased(self):
        self.quiz.show_results = False
        self.quiz.save(update_fields=['show_results'])
        self.client.force_login(self.student)
        self.client.post(self.u('start', self.quiz.pk))
        self.client.post(self.u('submit', self.quiz.pk))
        response = self.client.get(self.u('result', self.quiz.pk))
        self.assertNotContains(response, 'Correct choice:')
        self.assertNotContains(response, '0 / 5')
        self.assertNotContains(response, 'Length')

    def test_correct_answers_not_exposed_before_quiz_closes(self):
        self.client.force_login(self.student)
        self.client.post(self.u('start', self.quiz.pk))
        self.client.post(self.u('submit', self.quiz.pk))
        response = self.client.get(self.u('result', self.quiz.pk))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Correct choice:')
        self.assertNotContains(response, '2 / 5')
        self.client.force_login(self.teacher)
        self.client.post(self.u('close', self.quiz.pk))
        self.client.force_login(self.student)
        response = self.client.get(self.u('result', self.quiz.pk))
        self.assertContains(response, 'Correct choice:')

    def test_admin_can_view_results_but_cannot_publish(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.u('roster', self.quiz.pk)).status_code, 200)
        self.assertEqual(self.client.post(self.u('close', self.quiz.pk)).status_code, 403)
        self.assertEqual(self.client.post(self.u('question_add', self.quiz.pk)).status_code, 403)

    def test_anonymous_login_redirect_and_csrf(self):
        self.assertEqual(self.client.get(self.u('list')).status_code, 302)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.student)
        self.assertEqual(guarded.post(self.u('start', self.quiz.pk)).status_code, 403)

    def test_teacher_can_create_draft_add_question_and_publish(self):
        self.client.force_login(self.teacher)
        now = timezone.localtime()
        response = self.client.post(self.u('create', self.offering.pk), {
            'title': 'Fresh Test', 'instructions': '',
            'opens_at': (now + timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M'),
            'closes_at': (now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'duration_minutes': 20, 'show_results': 'on',
        })
        self.assertEqual(response.status_code, 302)
        q = Quiz.objects.get(title='Fresh Test')
        self.assertEqual(q.status, Quiz.Status.DRAFT)
        response = self.client.post(self.u('publish', q.pk))
        q.refresh_from_db()
        self.assertEqual(q.status, Quiz.Status.DRAFT)  # cannot publish empty quiz
        self.client.post(self.u('question_add', q.pk), {
            'text': 'An MCQ?', 'option_a': 'One', 'option_b': 'Two', 'option_c': 'Three',
            'option_d': 'Four', 'correct_choice': 'B', 'points': 1, 'order': 1,
        })
        self.assertEqual(q.questions.count(), 1)
        self.client.post(self.u('publish', q.pk))
        q.refresh_from_db()
        self.assertEqual(q.status, Quiz.Status.PUBLISHED)

    def test_close_auto_finalizes_on_result_request(self):
        self.client.force_login(self.student)
        self.client.post(self.u('start', self.quiz.pk))
        self.client.force_login(self.teacher)
        self.client.post(self.u('close', self.quiz.pk))
        self.client.force_login(self.student)
        response = self.client.get(self.u('detail', self.quiz.pk))
        self.assertEqual(response.status_code, 200)
        attempt = QuizAttempt.objects.get(quiz=self.quiz, student=self.student)
        self.assertEqual(attempt.status, QuizAttempt.Status.AUTO_SUBMITTED)

    def test_teacher_can_release_results_after_closing(self):
        self.quiz.show_results = False
        self.quiz.save(update_fields=['show_results'])
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.post(self.u('release_results', self.quiz.pk)).status_code, 403)
        self.client.post(self.u('close', self.quiz.pk))
        self.assertEqual(self.client.post(self.u('release_results', self.quiz.pk)).status_code, 302)
        self.quiz.refresh_from_db()
        self.assertTrue(self.quiz.show_results)

    def test_class_first_navigation_is_scoped(self):
        self.client.force_login(self.teacher)
        landing = self.client.get(self.u('list'))
        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, 'Section A')
        self.assertNotContains(landing, 'Section B')
        class_url = self.u('class_courses', self.section.pk, self.offering.academic_year, self.offering.term)
        self.assertContains(self.client.get(class_url), 'Python Fundamentals')
        self.assertEqual(self.client.get(self.u('course_quizzes', self.other_offering.pk)).status_code, 404)
        self.assertContains(self.client.get(self.u('course_quizzes', self.offering.pk)), 'Python Midterm')
        self.client.force_login(self.student)
        self.assertContains(self.client.get(self.u('list')), 'Section A')
        self.assertNotContains(self.client.get(self.u('list')), 'Section B')
        self.assertEqual(self.client.get(self.u('course_quizzes', self.other_offering.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.u('class_courses', self.other_section.pk, self.other_offering.academic_year, self.other_offering.term)).status_code, 403)

    def test_quiz_create_is_locked_to_selected_course(self):
        self.client.force_login(self.teacher)
        now = timezone.localtime()
        data = {
            'title': 'Locked to class', 'opens_at': (now + timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M'),
            'closes_at': (now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'duration_minutes': 20, 'show_results': 'on',
            'course_offering': self.other_offering.pk,  # malicious forged input must be ignored
        }
        response = self.client.post(self.u('create', self.offering.pk), data)
        self.assertEqual(response.status_code, 302)
        created = Quiz.objects.get(title='Locked to class')
        self.assertEqual(created.course_offering_id, self.offering.pk)
        self.assertEqual(self.client.post(self.u('create', self.other_offering.pk), data).status_code, 404)

    def test_student_does_not_see_draft_in_course_list(self):
        Quiz.objects.create(
            course_offering=self.offering, created_by=self.teacher, title='Private draft',
            opens_at=self.quiz.opens_at, closes_at=self.quiz.closes_at,
            duration_minutes=10, status=Quiz.Status.DRAFT,
        )
        self.client.force_login(self.student)
        self.assertNotContains(self.client.get(self.u('course_quizzes', self.offering.pk)), 'Private draft')
        self.assertContains(self.client.get(self.u('course_quizzes', self.offering.pk)), 'Python Midterm')

    def test_single_class_groups_multiple_course_offerings(self):
        extra = CourseOffering.objects.create(
            course=self.other_course, section=self.section, teacher=self.teacher,
            academic_year=self.offering.academic_year, term=self.offering.term,
        )
        self.client.force_login(self.teacher)
        landing = self.client.get(self.u('list'))
        self.assertEqual(len(landing.context['classes']), 1)
        self.assertEqual(landing.context['classes'][0]['course_count'], 2)
        courses = self.client.get(self.u('class_courses', self.section.pk, self.offering.academic_year, self.offering.term))
        self.assertContains(courses, 'Python Fundamentals')
        self.assertContains(courses, 'Database Systems')
        self.client.force_login(self.student)
        student_courses = self.client.get(self.u('class_courses', self.section.pk, self.offering.academic_year, self.offering.term))
        self.assertContains(student_courses, 'Python Fundamentals')
        self.assertNotContains(student_courses, 'Database Systems')
        CourseEnrollment.objects.create(offering=extra, student=self.student, status=CourseEnrollment.Status.ACTIVE)
        student_courses = self.client.get(self.u('class_courses', self.section.pk, self.offering.academic_year, self.offering.term))
        self.assertContains(student_courses, 'Database Systems')
