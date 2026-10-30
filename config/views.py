
from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import UserProfile
from departments.models import Department, Program
from semesters.models import Semester, Section

from courses.models import (
    Course,
    CourseOffering,
    CourseEnrollment,
)

from assignments.models import (
    Assignment,
    Submission,
)

from class_allocations.models import StudentClassAllocation

from student_onboarding.models import (
    StudentIdentity,
    StudentImportBatch,
)


User = get_user_model()


# ==========================================
# ROLE IDENTIFICATION
# ==========================================

def get_dashboard_role(user):
    """
    Detect logged-in user's AssignHub role.
    Never use is_staff alone for admin access.
    """

    if not user.is_authenticated:
        return "guest"

    if user.is_superuser:
        return "admin"

    role = (
        UserProfile.objects
        .filter(user=user)
        .values_list("role", flat=True)
        .first()
    )

    if role == UserProfile.Role.ADMIN:
        return "admin"

    if role == UserProfile.Role.TEACHER:
        return "teacher"

    if role == UserProfile.Role.STUDENT:
        return "student"

    return "unknown"


# ==========================================
# PHASE 9.2 - ADMIN DASHBOARD
# ==========================================

def get_admin_dashboard_data():
    """
    System-wide Admin metrics.
    Called for Admin users only.
    """

    student_profiles = UserProfile.objects.filter(
        role=UserProfile.Role.STUDENT
    )

    teacher_profiles = UserProfile.objects.filter(
        role=UserProfile.Role.TEACHER
    )

    return {

        # USERS

        "total_students": student_profiles.count(),

        "active_students": student_profiles.filter(
            user__is_active=True
        ).count(),

        "total_teachers": teacher_profiles.count(),

        "active_teachers": teacher_profiles.filter(
            user__is_active=True
        ).count(),

        # ACADEMIC STRUCTURE

        "total_departments": Department.objects.count(),

        "total_programs": Program.objects.count(),

        "total_semesters": Semester.objects.count(),

        "total_sections": Section.objects.count(),

        # COURSES

        "total_courses": Course.objects.count(),

        "total_offerings": CourseOffering.objects.count(),

        "active_offerings": CourseOffering.objects.filter(
            is_active=True
        ).count(),

        "total_enrollments": CourseEnrollment.objects.filter(
            status=CourseEnrollment.Status.ACTIVE
        ).count(),

        # CLASS ALLOCATIONS

        "total_allocations": (
            StudentClassAllocation.objects.filter(
                status=StudentClassAllocation.Status.ACTIVE
            ).count()
        ),

        # ASSIGNMENTS

        "total_assignments": Assignment.objects.count(),

        "published_assignments": Assignment.objects.filter(
            status=Assignment.Status.PUBLISHED
        ).count(),

        "draft_assignments": Assignment.objects.filter(
            status=Assignment.Status.DRAFT
        ).count(),

        # SUBMISSIONS

        "total_submissions": Submission.objects.filter(
            status__in=[
                Submission.Status.SUBMITTED,
                Submission.Status.GRADED,
            ]
        ).count(),

        "pending_grading": Submission.objects.filter(
            status=Submission.Status.SUBMITTED
        ).count(),

        "graded_submissions": Submission.objects.filter(
            status=Submission.Status.GRADED
        ).count(),

        # STUDENT ONBOARDING

        "total_imported_students": (
            StudentIdentity.objects.count()
        ),

        "pending_activations": (
            StudentIdentity.objects.filter(
                status=StudentIdentity.Status.PENDING
            ).count()
        ),

        "activated_imported_students": (
            StudentIdentity.objects.filter(
                status=StudentIdentity.Status.ACTIVE
            ).count()
        ),

        "cancelled_accounts": (
            StudentIdentity.objects.filter(
                status=StudentIdentity.Status.CANCELLED
            ).count()
        ),

        # RECENT ACTIVITY

        "recent_imports": (
            StudentImportBatch.objects
            .select_related("section", "created_by")
            .order_by("-created_at")[:5]
        ),

        "recent_assignments": (
            Assignment.objects
            .select_related(
                "created_by",
                "course_offering",
            )
            .order_by("-created_at")[:5]
        ),
    }


# ==========================================
# PHASE 9.3 - TEACHER DASHBOARD
# ==========================================

def get_teacher_dashboard_data(user):
    """
    Live dashboard statistics for one teacher.

    Every query is restricted to:
    - offerings assigned to this teacher
    - assignments created by this teacher
    - submissions belonging to those assignments

    Never expose other teachers' data.
    """

    now = timezone.now()

    # --------------------------------------
    # TEACHER COURSE OFFERINGS
    # --------------------------------------

    offerings = CourseOffering.objects.filter(
        teacher=user,
        is_active=True,
    )

    # Count distinct courses as well as sections.
    total_offerings = offerings.count()

    total_courses = (
        offerings
        .values("course_id")
        .distinct()
        .count()
    )

    # --------------------------------------
    # TEACHER STUDENTS
    # --------------------------------------

    active_enrollments = CourseEnrollment.objects.filter(
        offering__teacher=user,
        offering__is_active=True,
        status=CourseEnrollment.Status.ACTIVE,
        student__is_active=True,
    )

    # Unique students across all assigned classes.
    total_students = (
        active_enrollments
        .values("student_id")
        .distinct()
        .count()
    )

    # A student enrolled in multiple courses
    # counts once in total_students, but each
    # enrollment counts here.
    total_enrollments = active_enrollments.count()

    # --------------------------------------
    # TEACHER ASSIGNMENTS
    # --------------------------------------

    assignments = Assignment.objects.filter(
        created_by=user
    )

    total_assignments = assignments.count()

    published_assignments = assignments.filter(
        status=Assignment.Status.PUBLISHED
    ).count()

    draft_assignments = assignments.filter(
        status=Assignment.Status.DRAFT
    ).count()

    closed_assignments = assignments.filter(
        status=Assignment.Status.CLOSED
    ).count()

    upcoming_assignments = (
        assignments
        .filter(
            status=Assignment.Status.PUBLISHED,
            deadline__gte=now,
            course_offering__is_active=True,
        )
        .select_related(
            "course_offering",
            "course_offering__course",
            "course_offering__section",
        )
        .order_by("deadline", "pk")[:5]
    )

    # --------------------------------------
    # TEACHER SUBMISSIONS
    # --------------------------------------

    submissions = Submission.objects.filter(
        assignment__created_by=user
    )

    submitted_or_graded = submissions.filter(
        status__in=[
            Submission.Status.SUBMITTED,
            Submission.Status.GRADED,
        ]
    )

    total_submissions = submitted_or_graded.count()

    pending_grading = submissions.filter(
        status=Submission.Status.SUBMITTED
    ).count()

    graded_submissions = submissions.filter(
        status=Submission.Status.GRADED
    ).count()

    grading_percentage = (
        round((graded_submissions / total_submissions) * 100)
        if total_submissions
        else 0
    )

    # Submissions needing grading first.
    grading_queue = (
        submissions
        .filter(
            status=Submission.Status.SUBMITTED
        )
        .select_related(
            "student",
            "assignment",
            "assignment__course_offering",
            "assignment__course_offering__course",
        )
        .order_by("submitted_at", "pk")[:6]
    )

    # Latest finalized submissions.
    recent_submissions = (
        submitted_or_graded
        .select_related(
            "student",
            "assignment",
            "assignment__course_offering",
            "assignment__course_offering__course",
        )
        .order_by("-submitted_at", "-pk")[:5]
    )

    # --------------------------------------
    # TEACHER CLASS CARDS
    # --------------------------------------

    my_classes = (
        offerings
        .select_related(
            "course",
            "section",
            "section__semester",
        )
        .annotate(
            student_count=Count(
                "enrollments",
                filter=Q(
                    enrollments__status=(
                        CourseEnrollment.Status.ACTIVE
                    ),
                    enrollments__student__is_active=True,
                ),
                distinct=True,
            )
        )
        .order_by(
            "course__code",
            "section__code",
        )[:6]
    )

    # --------------------------------------
    # DASHBOARD CONTEXT
    # --------------------------------------

    return {
        "teacher_total_courses": total_courses,
        "teacher_total_offerings": total_offerings,
        "teacher_total_students": total_students,
        "teacher_total_enrollments": total_enrollments,

        "teacher_total_assignments": total_assignments,
        "teacher_published_assignments": published_assignments,
        "teacher_draft_assignments": draft_assignments,
        "teacher_closed_assignments": closed_assignments,

        "teacher_total_submissions": total_submissions,
        "teacher_pending_grading": pending_grading,
        "teacher_graded_submissions": graded_submissions,
        "teacher_grading_percentage": grading_percentage,

        "teacher_upcoming_assignments": upcoming_assignments,
        "teacher_grading_queue": grading_queue,
        "teacher_recent_submissions": recent_submissions,
        "teacher_my_classes": my_classes,
    }


# ==========================================
# MAIN ROLE-BASED DASHBOARD
# ==========================================

def home(request):
    """
    Main AssignHub homepage.

    Admin:   System-wide university overview
    Teacher: Personal teaching and grading dashboard
    Student: Student dashboard (Phase 9.4)
    Guest:   Public welcome screen
    """

    role = get_dashboard_role(request.user)

    context = {
        "dashboard_role": role,
    }

    if role == "admin":

        context.update(
            get_admin_dashboard_data()
        )

    elif role == "teacher":

        context.update(
            get_teacher_dashboard_data(request.user)
        )

    return render(
        request,
        "home.html",
        context,
    )
