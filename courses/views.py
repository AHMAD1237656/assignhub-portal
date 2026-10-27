
from django.contrib import messages
from django.core.exceptions import (
    PermissionDenied,
    ValidationError,
)
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from departments.models import Program
from semesters.models import Section, Semester

from .forms import (
    CourseEnrollmentForm,
    CourseForm,
    CourseOfferingForm,
    safe_selected_id,
)
from .models import (
    Course,
    CourseEnrollment,
    CourseOffering,
)
from .permissions import (
    academic_admin_required,
    is_academic_admin,
    teacher_or_admin_required,
)


PAGE_SIZE = 10


def search_text(request):
    return request.GET.get(
        "q", ""
    ).strip()[:100]


def valid_status(request):
    status = request.GET.get("status", "all")

    if status in ("all", "active", "inactive"):
        return status

    return "all"


def is_ajax(request):
    return (
        request.headers.get("x-requested-with")
        == "XMLHttpRequest"
    )


def filter_by_status(queryset, status):
    if status == "active":
        return queryset.filter(is_active=True)

    if status == "inactive":
        return queryset.filter(is_active=False)

    return queryset


def paginate(request, queryset):
    return Paginator(
        queryset,
        PAGE_SIZE,
    ).get_page(request.GET.get("page"))


def base_query(request):
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def save_record(form):
    try:
        with transaction.atomic():
            return form.save()
    except IntegrityError:
        form.add_error(
            None,
            "Duplicate or conflicting record. "
            "Check the entered values.",
        )
        return None


def change_active_status(
    request, model, pk, detail_route
):
    action = request.POST.get("action")

    if action not in ("archive", "restore"):
        messages.error(
            request,
            "Invalid status action.",
        )
        return redirect(detail_route, pk=pk)

    with transaction.atomic():
        record = get_object_or_404(
            model.objects.select_for_update(),
            pk=pk,
        )

        target = action == "restore"

        if record.is_active == target:
            messages.info(
                request,
                "Record already has this status.",
            )
            return redirect(
                detail_route,
                pk=pk,
            )

        record.is_active = target

        try:
            record.full_clean()
        except ValidationError as exc:
            messages.error(
                request,
                "; ".join(exc.messages),
            )
            return redirect(detail_route, pk=pk)

        record.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

    messages.success(
        request,
        "Status updated.",
    )

    return redirect(detail_route, pk=pk)


def delete_record(
    request, model, pk, list_route, detail_route
):
    record = get_object_or_404(model, pk=pk)

    if request.method == "POST":
        try:
            with transaction.atomic():
                record.delete()
        except (ProtectedError, IntegrityError):
            messages.error(
                request,
                "Related data exists. Archive "
                "this record instead.",
            )
            return redirect(
                detail_route,
                pk=pk,
            )

        messages.success(
            request,
            "Record deleted.",
        )
        return redirect(list_route)

    return render(
        request,
        "courses/confirm_delete.html",
        {
            "record": record,
            "cancel_route": detail_route,
        },
    )


# ===================================================
# COURSES
# ===================================================

@academic_admin_required
@require_GET
def course_list(request):
    q = search_text(request)
    status = valid_status(request)

    program_id = safe_selected_id(
        request.GET.get("program")
    )

    semester_id = safe_selected_id(
        request.GET.get("semester")
    )

    courses = Course.objects.select_related(
        "program",
        "semester",
        "program__department",
    )

    if q:
        courses = courses.filter(
            Q(code__icontains=q)
            | Q(title__icontains=q)
            | Q(program__code__icontains=q)
            | Q(description__icontains=q)
        )

    raw_program = request.GET.get("program", "")

    if raw_program:
        courses = courses.filter(
            program_id=program_id or -1
        )

    if request.GET.get("semester"):
        courses = courses.filter(
            semester_id=semester_id or -1
        )

    courses = filter_by_status(courses, status)

    context = {
        "page_obj": paginate(request, courses),
        "programs": Program.objects.order_by(
            "code", "pk"
        ),
        "semesters": Semester.objects.filter(
            program_id=program_id
        ).order_by("number")
        if program_id
        else Semester.objects.none(),
        "selected_program": raw_program,
        "selected_semester": request.GET.get(
            "semester", ""
        ),
        "search": q,
        "status": status,
        "base_query": base_query(request),
    }

    template = (
        "courses/partials/course_results.html"
        if is_ajax(request)
        else "courses/course_list.html"
    )

    return render(request, template, context)


@academic_admin_required
@require_http_methods(["GET", "POST"])
def course_create(request):
    form = CourseForm(
        request.POST or None,
        initial={
            "program": safe_selected_id(
                request.GET.get("program")
            ),
        } if request.method == "GET" else None,
    )

    if request.method == "POST" and form.is_valid():
        record = save_record(form)

        if record:
            messages.success(
                request,
                "Course created successfully.",
            )
            return redirect(
                "courses:course_detail",
                pk=record.pk,
            )

    return render(
        request,
        "courses/record_form.html",
        {
            "form": form,
            "page_title": "Create Course",
            "cancel_route": "courses:course_list",
            "dependent_type": "course",
        },
    )


@academic_admin_required
@require_http_methods(["GET", "POST"])
def course_edit(request, pk):
    record = get_object_or_404(Course, pk=pk)

    form = CourseForm(
        request.POST or None,
        instance=record,
    )

    if request.method == "POST" and form.is_valid():
        saved = save_record(form)

        if saved:
            messages.success(
                request,
                "Course updated.",
            )
            return redirect(
                "courses:course_detail",
                pk=saved.pk,
            )

    return render(
        request,
        "courses/record_form.html",
        {
            "form": form,
            "page_title": "Edit Course",
            "cancel_route": "courses:course_list",
            "dependent_type": "course",
        },
    )


@academic_admin_required
@require_GET
def course_detail(request, pk):
    record = get_object_or_404(
        Course.objects.select_related(
            "program",
            "semester",
            "program__department",
        ),
        pk=pk,
    )

    related = record.offerings.select_related(
        "teacher", "section"
    )

    return render(
        request,
        "courses/detail.html",
        {
            "record": record,
            "kind": "Course",
            "related": related,
            "related_kind": "offerings",
            "edit_route": "courses:course_edit",
            "toggle_route": "courses:course_toggle",
            "delete_route": "courses:course_delete",
            "list_route": "courses:course_list",
            "create_related_route": "courses:offering_create",
        },
    )


@academic_admin_required
@require_POST
def course_toggle(request, pk):
    return change_active_status(
        request,
        Course,
        pk,
        "courses:course_detail",
    )


@academic_admin_required
@require_http_methods(["GET", "POST"])
def course_delete(request, pk):
    return delete_record(
        request,
        Course,
        pk,
        "courses:course_list",
        "courses:course_detail",
    )


# ===================================================
# COURSE OFFERINGS
# ===================================================

@teacher_or_admin_required
@require_GET
def offering_list(request):
    q = search_text(request)
    status = valid_status(request)

    offerings = CourseOffering.objects.select_related(
        "course",
        "course__program",
        "course__semester",
        "section",
        "teacher",
    )

    if not is_academic_admin(request.user):
        offerings = offerings.filter(
            teacher=request.user
        )

    if q:
        offerings = offerings.filter(
            Q(course__code__icontains=q)
            | Q(course__title__icontains=q)
            | Q(section__code__icontains=q)
            | Q(teacher__username__icontains=q)
        )

    program_id = safe_selected_id(
        request.GET.get("program")
    )

    if request.GET.get("program"):
        offerings = offerings.filter(
            course__program_id=program_id or -1
        )

    year = request.GET.get(
        "year", ""
    ).strip()[:9]

    if year:
        offerings = offerings.filter(
            academic_year=year
        )

    term = request.GET.get("term", "")

    if term in CourseOffering.Term.values:
        offerings = offerings.filter(term=term)

    offerings = filter_by_status(offerings, status)

    context = {
        "page_obj": paginate(request, offerings),
        "programs": Program.objects.order_by("code"),
        "selected_program": request.GET.get(
            "program", ""
        ),
        "search": q,
        "status": status,
        "year": year,
        "term": term,
        "terms": CourseOffering.Term.choices,
        "base_query": base_query(request),
        "is_academic_admin": is_academic_admin(
            request.user
        ),
    }

    template = (
        "courses/partials/offering_results.html"
        if is_ajax(request)
        else "courses/offering_list.html"
    )

    return render(request, template, context)


@academic_admin_required
@require_http_methods(["GET", "POST"])
def offering_create(request):
    form = CourseOfferingForm(
        request.POST or None,
        initial={
            "course": safe_selected_id(
                request.GET.get("course")
            ),
        } if request.method == "GET" else None,
    )

    if request.method == "POST" and form.is_valid():
        record = save_record(form)

        if record:
            messages.success(
                request,
                "Course Offering created.",
            )
            return redirect(
                "courses:offering_detail",
                pk=record.pk,
            )

    return render(
        request,
        "courses/record_form.html",
        {
            "form": form,
            "page_title": "Create Course Offering",
            "cancel_route": "courses:offering_list",
            "dependent_type": "offering",
        },
    )


@academic_admin_required
@require_http_methods(["GET", "POST"])
def offering_edit(request, pk):
    record = get_object_or_404(
        CourseOffering,
        pk=pk,
    )

    form = CourseOfferingForm(
        request.POST or None,
        instance=record,
    )

    if request.method == "POST" and form.is_valid():
        saved = save_record(form)

        if saved:
            messages.success(
                request,
                "Course Offering updated.",
            )
            return redirect(
                "courses:offering_detail",
                pk=saved.pk,
            )

    return render(
        request,
        "courses/record_form.html",
        {
            "form": form,
            "page_title": "Edit Course Offering",
            "cancel_route": "courses:offering_list",
            "dependent_type": "offering",
        },
    )


@teacher_or_admin_required
@require_GET
def offering_detail(request, pk):
    record = get_object_or_404(
        CourseOffering.objects.select_related(
            "course",
            "section",
            "teacher",
            "course__program",
        ),
        pk=pk,
    )

    admin_access = is_academic_admin(request.user)

    if (
        not admin_access
        and record.teacher_id != request.user.pk
    ):
        raise PermissionDenied

    return render(
        request,
        "courses/detail.html",
        {
            "record": record,
            "kind": "Offering",
            "related": record.enrollments.select_related(
                "student"
            ),
            "related_kind": "enrollments",
            "edit_route": "courses:offering_edit",
            "toggle_route": "courses:offering_toggle",
            "delete_route": "courses:offering_delete",
            "list_route": "courses:offering_list",
            "create_related_route": "courses:enrollment_create",
            "can_manage": admin_access,
        },
    )


@academic_admin_required
@require_POST
def offering_toggle(request, pk):
    return change_active_status(
        request,
        CourseOffering,
        pk,
        "courses:offering_detail",
    )


@academic_admin_required
@require_http_methods(["GET", "POST"])
def offering_delete(request, pk):
    return delete_record(
        request,
        CourseOffering,
        pk,
        "courses:offering_list",
        "courses:offering_detail",
    )


# ===================================================
# BASIC ENROLLMENT MANAGEMENT
# ===================================================

@academic_admin_required
@require_GET
def enrollment_list(request):
    q = search_text(request)

    enrollments = (
        CourseEnrollment.objects.select_related(
            "student",
            "offering",
            "offering__course",
            "offering__section",
        )
    )

    if q:
        enrollments = enrollments.filter(
            Q(student__username__icontains=q)
            | Q(offering__course__code__icontains=q)
            | Q(offering__section__code__icontains=q)
        )

    status = request.GET.get("status", "all")

    if status == "active":
        enrollments = enrollments.filter(
            status=CourseEnrollment.Status.ACTIVE
        )
    elif status == "dropped":
        enrollments = enrollments.filter(
            status=CourseEnrollment.Status.DROPPED
        )
    else:
        status = "all"

    context = {
        "page_obj": paginate(request, enrollments),
        "search": q,
        "status": status,
        "base_query": base_query(request),
    }

    template = (
        "courses/partials/enrollment_results.html"
        if is_ajax(request)
        else "courses/enrollment_list.html"
    )

    return render(request, template, context)


@academic_admin_required
@require_http_methods(["GET", "POST"])
def enrollment_create(request):
    form = CourseEnrollmentForm(
        request.POST or None,
        initial={
            "offering": safe_selected_id(
                request.GET.get("offering")
            ),
        } if request.method == "GET" else None,
    )

    if request.method == "POST" and form.is_valid():
        record = save_record(form)

        if record:
            messages.success(
                request,
                "Student enrolled.",
            )
            return redirect(
                "courses:enrollment_list"
            )

    return render(
        request,
        "courses/record_form.html",
        {
            "form": form,
            "page_title": "Enroll Student",
            "cancel_route": "courses:enrollment_list",
        },
    )


@academic_admin_required
@require_http_methods(["GET", "POST"])
def enrollment_edit(request, pk):
    record = get_object_or_404(
        CourseEnrollment,
        pk=pk,
    )

    form = CourseEnrollmentForm(
        request.POST or None,
        instance=record,
    )

    if request.method == "POST" and form.is_valid():
        saved = save_record(form)

        if saved:
            messages.success(
                request,
                "Enrollment status updated.",
            )
            return redirect(
                "courses:enrollment_list"
            )

    return render(
        request,
        "courses/record_form.html",
        {
            "form": form,
            "page_title": "Edit Enrollment",
            "cancel_route": "courses:enrollment_list",
        },
    )


@academic_admin_required
@require_http_methods(["GET", "POST"])
def enrollment_delete(request, pk):
    record = get_object_or_404(
        CourseEnrollment,
        pk=pk,
    )

    if request.method == "POST":
        # Preserve the historical enrollment.
        # Dropping is preferable to hard deletion.
        if record.status != CourseEnrollment.Status.DROPPED:
            record.status = CourseEnrollment.Status.DROPPED
            record.full_clean()
            record.save(
                update_fields=["status", "updated_at"]
            )

        messages.success(
            request,
            "Enrollment dropped.",
        )

        return redirect(
            "courses:enrollment_list"
        )

    return render(
        request,
        "courses/confirm_delete.html",
        {
            "record": record,
            "cancel_route": "courses:enrollment_list",
            "is_drop": True,
        },
    )


# ===================================================
# DEPENDENT DROPDOWN APIs
# ===================================================

@academic_admin_required
@require_GET
def sections_for_course_api(request):
    course_id = safe_selected_id(
        request.GET.get("course")
    )

    if not course_id:
        return JsonResponse(
            {"error": "Valid course ID required."},
            status=400,
        )

    course = get_object_or_404(
        Course,
        pk=course_id,
    )

    sections = Section.objects.filter(
        semester_id=course.semester_id,
        is_active=True,
        semester__is_active=True,
        semester__program__is_active=True,
        semester__program__department__is_active=True,
    ).order_by("code")

    return JsonResponse({
        "results": [
            {
                "id": section.pk,
                "label": f"Section {section.code}",
            }
            for section in sections
        ]
    })
