from dataclasses import dataclass

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import UserProfile
from courses.models import (
    CourseEnrollment,
    CourseOffering,
    validate_academic_year,
)
from semesters.models import Section

from .models import StudentClassAllocation


User = get_user_model()


@dataclass
class AllocationResult:
    created: int = 0
    already_allocated: int = 0
    transferred: int = 0
    enrollments_created: int = 0
    enrollments_restored: int = 0
    enrollments_existing: int = 0
    enrollments_dropped: int = 0
    available_offerings: int = 0


def active_offerings(section, academic_year, term):
    """
    Return only active offerings belonging to
    an active academic hierarchy.
    """

    return CourseOffering.objects.filter(
        section=section,
        academic_year=academic_year,
        term=term,
        is_active=True,
        course__is_active=True,
        section__is_active=True,
        section__semester__is_active=True,
        section__semester__program__is_active=True,
        section__semester__program__department__is_active=True,
    ).select_related("course")


def validate_section(section):
    """
    An archived section or parent academic record
    cannot receive new allocations.
    """

    if not all([
        section.is_active,
        section.semester.is_active,
        section.semester.program.is_active,
        section.semester.program.department.is_active,
    ]):
        raise ValidationError(
            "Selected section or its academic "
            "hierarchy is inactive."
        )


def ensure_no_live_timed_attempt(student, old_section, year, term):
    """
    Never transfer a student while an active
    timed writing attempt is still running.
    """

    if not apps.is_installed("timed_writing"):
        return

    TimedWritingAttempt = apps.get_model(
        "timed_writing",
        "TimedWritingAttempt",
    )

    has_live_attempt = (
        TimedWritingAttempt.objects.filter(
            student=student,
            status="ACTIVE",
            expires_at__gt=timezone.now(),
            config__assignment__course_offering__section=old_section,
            config__assignment__course_offering__academic_year=year,
            config__assignment__course_offering__term=term,
        ).exists()
    )

    if has_live_attempt:
        raise ValidationError(
            f"{student.username} has a running "
            "timed writing attempt. Complete or "
            "expire that attempt before transfer."
        )


def ensure_no_other_section_enrollments(
    student,
    section,
    academic_year,
    term,
    old_section=None,
):
    """
    Prevent class allocation from silently
    overriding unrelated manual enrollments.
    """

    allowed_section_ids = [section.pk]

    if old_section is not None:
        allowed_section_ids.append(old_section.pk)

    conflicting = (
        CourseEnrollment.objects.filter(
            student=student,
            status=CourseEnrollment.Status.ACTIVE,
            offering__academic_year=academic_year,
            offering__term=term,
        )
        .exclude(
            offering__section_id__in=allowed_section_ids
        )
        .select_related("offering__section")
        .first()
    )

    if conflicting:
        raise ValidationError(
            f"{student.username} has an active "
            "manual enrollment in another section "
            "for this academic period. Resolve "
            "that enrollment before allocation."
        )


@transaction.atomic
def allocate_students(
    *,
    students,
    section,
    academic_year,
    term,
    assigned_by,
    allow_transfer=False,
    reason="",
):
    """
    Allocate students and synchronize their
    enrollments in a single transaction.

    Any validation failure rolls back the batch.
    """

    students = list(students)

    student_ids = sorted({
        student.pk
        for student in students
    })

    if not student_ids:
        raise ValidationError(
            "Select at least one student."
        )

    if len(student_ids) > 500:
        raise ValidationError(
            "A single operation cannot exceed "
            "500 students."
        )

    validate_academic_year(academic_year)

    valid_terms = {
        value
        for value, label in CourseOffering.Term.choices
    }

    if term not in valid_terms:
        raise ValidationError("Invalid academic term.")

    # Lock the section to serialize capacity checks
    # when using a database that supports row locks.
    section = (
        Section.objects.select_for_update()
        .select_related(
            "semester",
            "semester__program",
            "semester__program__department",
        )
        .get(pk=section.pk)
    )

    validate_section(section)

    # Lock student rows in deterministic order.
    locked_students = list(
        User.objects.select_for_update()
        .filter(pk__in=student_ids)
        .order_by("pk")
    )

    if len(locked_students) != len(student_ids):
        raise ValidationError(
            "One or more students no longer exist."
        )

    valid_student_ids = set(
        UserProfile.objects.filter(
            user_id__in=student_ids,
            role=UserProfile.Role.STUDENT,
        ).values_list(
            "user_id",
            flat=True,
        )
    )

    for student in locked_students:
        if not student.is_active:
            raise ValidationError(
                f"{student.username} is inactive."
            )

        if student.pk not in valid_student_ids:
            raise ValidationError(
                f"{student.username} is not a Student."
            )

    offerings = list(
        active_offerings(
            section,
            academic_year,
            term,
        ).order_by("pk")
    )

    current_allocations = {
        allocation.student_id: allocation
        for allocation in (
            StudentClassAllocation.objects
            .select_for_update()
            .select_related("section")
            .filter(
                student_id__in=student_ids,
                academic_year=academic_year,
                term=term,
                status=StudentClassAllocation.Status.ACTIVE,
            )
        )
    }

    # Preflight validation: no changes yet.
    for student in locked_students:
        current = current_allocations.get(student.pk)

        if current and current.section_id != section.pk:
            if not allow_transfer:
                raise ValidationError(
                    f"{student.username} is already "
                    f"allocated to {current.section}. "
                    "Enable Section Transfer to move "
                    "this student."
                )

            ensure_no_live_timed_attempt(
                student,
                current.section,
                academic_year,
                term,
            )

        old_section = None

        if current and current.section_id != section.pk:
            old_section = current.section

        ensure_no_other_section_enrollments(
            student,
            section,
            academic_year,
            term,
            old_section,
        )

    # Count both managed allocations and students
    # already enrolled manually in the target class.
    allocated_ids = set(
        StudentClassAllocation.objects.filter(
            section=section,
            academic_year=academic_year,
            term=term,
            status=StudentClassAllocation.Status.ACTIVE,
        ).values_list(
            "student_id",
            flat=True,
        )
    )

    enrolled_ids = set(
        CourseEnrollment.objects.filter(
            offering__section=section,
            offering__academic_year=academic_year,
            offering__term=term,
            status=CourseEnrollment.Status.ACTIVE,
        ).values_list(
            "student_id",
            flat=True,
        )
    )


    # Reserve seats for imported students who have
    # not completed their email activation yet.
    reserved_ids = set()

    if apps.is_installed("student_onboarding"):

        StudentIdentity = apps.get_model(
            "student_onboarding",
            "StudentIdentity",
        )

        reserved_ids = set(
            StudentIdentity.objects.filter(
                section=section,
                academic_year=academic_year,
                term=term,
                status="PENDING",
            ).values_list(
                "user_id",
                flat=True,
            )
        )

    # A student counts only once even if they appear
    # in allocation, enrollment, and reservation data.
    occupied_ids = (
        allocated_ids
        | enrolled_ids
        | reserved_ids
    )

    new_occupants = (
        set(student_ids) - occupied_ids
    )


    total_after = (
        len(occupied_ids)
        + len(new_occupants)
    )

    if total_after > section.capacity:
        free_seats = max(
            0,
            section.capacity - len(occupied_ids),
        )

        raise ValidationError(
            f"Section capacity exceeded. "
            f"Only {free_seats} seats are available."
        )

    result = AllocationResult(
        available_offerings=len(offerings)
    )

    now = timezone.now()

    for student in locked_students:
        current = current_allocations.get(student.pk)

        # Existing allocation in the same section:
        # do not duplicate; just synchronize offerings.
        if current and current.section_id == section.pk:
            result.already_allocated += 1

        else:
            # Controlled transfer in the same period.
            if current is not None:

                old_section = current.section

                current.status = (
                    StudentClassAllocation.Status.TRANSFERRED
                )
                current.ended_at = now

                current.save(
                    update_fields=[
                        "status",
                        "ended_at",
                    ]
                )

                dropped = (
                    CourseEnrollment.objects.filter(
                        student=student,
                        offering__section=old_section,
                        offering__academic_year=academic_year,
                        offering__term=term,
                        status=CourseEnrollment.Status.ACTIVE,
                    ).update(
                        status=CourseEnrollment.Status.DROPPED,
                        updated_at=now,
                    )
                )

                result.enrollments_dropped += dropped
                result.transferred += 1

            StudentClassAllocation.objects.create(
                student=student,
                section=section,
                academic_year=academic_year,
                term=term,
                status=StudentClassAllocation.Status.ACTIVE,
                assigned_by=assigned_by,
                reason=reason.strip(),
            )

            result.created += 1

        # Automatic enrollment in all active
        # course offerings of the target section.
        for offering in offerings:

            enrollment, created = (
                CourseEnrollment.objects.get_or_create(
                    student=student,
                    offering=offering,
                    defaults={
                        "status": CourseEnrollment.Status.ACTIVE,
                    },
                )
            )

            if created:
                result.enrollments_created += 1

            elif (
                enrollment.status
                == CourseEnrollment.Status.DROPPED
            ):
                enrollment.status = (
                    CourseEnrollment.Status.ACTIVE
                )
                enrollment.save(
                    update_fields=[
                        "status",
                        "updated_at",
                    ]
                )

                result.enrollments_restored += 1

            else:
                result.enrollments_existing += 1

    return result