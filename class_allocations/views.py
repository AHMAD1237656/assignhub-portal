from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.db.models import Count, Q
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.http import require_POST

from assignments.permissions import (
    is_admin,
    is_teacher,
)
from courses.models import (
    CourseEnrollment,
    CourseOffering,
)

from .forms import (
    AllocationFilterForm,
    BulkAllocationForm,
    ClassPeriodForm,
)
from .models import StudentClassAllocation
from .services import allocate_students


def require_admin(user):
    if not is_admin(user):
        raise PermissionDenied(
            "Only administrators can manage "
            "class allocations."
        )


def show_validation_errors(request, error):
    for message in error.messages:
        messages.error(request, message)


@login_required
def dashboard(request):
    require_admin(request.user)

    allocations = (
        StudentClassAllocation.objects
        .select_related(
            "student",
            "section",
            "section__semester",
            "section__semester__program",
            "assigned_by",
        )
    )

    filter_form = AllocationFilterForm(
        request.GET or None
    )

    can_sync = False
    selected_period = None

    if filter_form.is_valid():
        section = filter_form.cleaned_data["section"]
        year = filter_form.cleaned_data["academic_year"]
        term = filter_form.cleaned_data["term"]

        if section:
            allocations = allocations.filter(
                section=section
            )

        if year:
            allocations = allocations.filter(
                academic_year=year
            )

        if term:
            allocations = allocations.filter(
                term=term
            )

        if section and year and term:
            can_sync = True
            selected_period = {
                "section": section,
                "academic_year": year,
                "term": term,
            }

    allocations = allocations[:100]

    context = {
        "allocations": allocations,
        "filter_form": filter_form,
        "can_sync": can_sync,
        "selected_period": selected_period,
        "active_count": (
            StudentClassAllocation.objects.filter(
                status=StudentClassAllocation.Status.ACTIVE
            ).count()
        ),
        "history_count": (
            StudentClassAllocation.objects.filter(
                status=StudentClassAllocation.Status.TRANSFERRED
            ).count()
        ),
    }

    return render(
        request,
        "class_allocations/dashboard.html",
        context,
    )


@login_required
def allocate(request):
    require_admin(request.user)

    if request.method == "POST":
        form = BulkAllocationForm(request.POST)

        if form.is_valid():
            try:
                result = allocate_students(
                    students=form.students,
                    section=form.cleaned_data["section"],
                    academic_year=(
                        form.cleaned_data["academic_year"]
                    ),
                    term=form.cleaned_data["term"],
                    assigned_by=request.user,
                    allow_transfer=(
                        form.cleaned_data["allow_transfer"]
                    ),
                    reason=form.cleaned_data["reason"],
                )

            except ValidationError as error:
                for error_message in error.messages:
                    form.add_error(
                        None,
                        error_message,
                    )

            else:
                messages.success(
                    request,
                    (
                        f"Allocation completed: "
                        f"{result.created} new allocations, "
                        f"{result.transferred} transfers, "
                        f"{result.already_allocated} existing, "
                        f"{result.enrollments_created} new "
                        f"course enrollments, "
                        f"{result.enrollments_restored} restored."
                    ),
                )

                if result.available_offerings == 0:
                    messages.warning(
                        request,
                        (
                            "No active course offerings were "
                            "found for this class period. "
                            "Create the offerings and use "
                            "Sync Enrollments afterward."
                        ),
                    )

                return redirect(
                    "class_allocations:dashboard"
                )

    else:
        form = BulkAllocationForm()

    return render(
        request,
        "class_allocations/allocate.html",
        {"form": form},
    )


@login_required
@require_POST
def sync_enrollments(request):
    require_admin(request.user)

    form = ClassPeriodForm(request.POST)

    if not form.is_valid():
        messages.error(
            request,
            "Invalid section or academic period.",
        )
        return redirect(
            "class_allocations:dashboard"
        )

    section = form.cleaned_data["section"]
    year = form.cleaned_data["academic_year"]
    term = form.cleaned_data["term"]

    allocations = (
        StudentClassAllocation.objects.filter(
            section=section,
            academic_year=year,
            term=term,
            status=StudentClassAllocation.Status.ACTIVE,
        )
        .select_related("student")
        .order_by("student_id")
    )

    students = [
        allocation.student
        for allocation in allocations
    ]

    if not students:
        messages.warning(
            request,
            "No active student allocations found "
            "for this class period.",
        )
        return redirect(
            "class_allocations:dashboard"
        )

    try:
        result = allocate_students(
            students=students,
            section=section,
            academic_year=year,
            term=term,
            assigned_by=request.user,
            allow_transfer=False,
            reason="Enrollment synchronization",
        )

    except ValidationError as error:
        show_validation_errors(
            request,
            error,
        )

    else:
        messages.success(
            request,
            (
                f"Synchronization complete. "
                f"{result.enrollments_created} new "
                f"enrollments, "
                f"{result.enrollments_restored} restored, "
                f"{result.enrollments_existing} unchanged."
            ),
        )

        if result.available_offerings == 0:
            messages.warning(
                request,
                "No active course offerings exist "
                "for the selected period.",
            )

    return redirect(
        "class_allocations:dashboard"
    )


@login_required
def my_classes(request):
    if not is_teacher(request.user):
        raise PermissionDenied(
            "Only teachers can view their assigned classes."
        )

    offerings = (
        CourseOffering.objects.filter(
            teacher=request.user,
        )
        .select_related(
            "course",
            "section",
            "section__semester",
            "section__semester__program",
        )
        .annotate(
            active_student_count=Count(
                "enrollments",
                filter=Q(
                    enrollments__status=(
                        CourseEnrollment.Status.ACTIVE
                    )
                ),
                distinct=True,
            )
        )
        .order_by(
            "-academic_year",
            "term",
            "course__code",
            "section__code",
        )
    )

    return render(
        request,
        "class_allocations/my_classes.html",
        {"offerings": offerings},
    )


@login_required
def class_roster(request, offering_id):

    if not (
        is_teacher(request.user)
        or is_admin(request.user)
    ):
        raise PermissionDenied

    offering = get_object_or_404(
        CourseOffering.objects.select_related(
            "course",
            "section",
            "section__semester",
            "section__semester__program",
        ),
        pk=offering_id,
    )

    if (
        not is_admin(request.user)
        and offering.teacher_id != request.user.pk
    ):
        raise PermissionDenied(
            "You cannot view another teacher's roster."
        )

    enrollments = (
        CourseEnrollment.objects.filter(
            offering=offering,
            status=CourseEnrollment.Status.ACTIVE,
        )
        .select_related("student")
        .order_by("student__username")
    )

    return render(
        request,
        "class_allocations/class_roster.html",
        {
            "offering": offering,
            "enrollments": enrollments,
            "student_count": enrollments.count(),
        },
    )