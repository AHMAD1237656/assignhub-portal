
from django.contrib import messages
from django.core.exceptions import ValidationError
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
from departments.permissions import academic_admin_required

from .forms import SectionForm, SemesterForm
from .models import Section, Semester


PAGE_SIZE = 10
MAX_SEARCH_LENGTH = 100


# =====================================================
# SHARED HELPERS
# =====================================================

def parse_id(raw_value):
    """
    Returns:
      None: no filter supplied
      -1: invalid filter
      positive integer: valid ID
    """
    if raw_value is None or raw_value == "":
        return None

    value = str(raw_value).strip()

    if not (
        value.isascii()
        and value.isdecimal()
        and len(value) <= 18
    ):
        return -1

    number = int(value)

    return number if number > 0 else -1


def search_value(request):
    return request.GET.get(
        "q", ""
    ).strip()[:MAX_SEARCH_LENGTH]


def status_value(request):
    status = request.GET.get(
        "status", "all"
    )

    if status in (
        "all",
        "active",
        "inactive",
    ):
        return status

    return "all"


def apply_status(queryset, status):
    if status == "active":
        return queryset.filter(
            is_active=True
        )

    if status == "inactive":
        return queryset.filter(
            is_active=False
        )

    return queryset


def is_ajax(request):
    return (
        request.headers.get(
            "x-requested-with"
        ) == "XMLHttpRequest"
    )


def get_page(request, queryset):
    paginator = Paginator(
        queryset,
        PAGE_SIZE,
    )

    return paginator.get_page(
        request.GET.get("page")
    )


def pagination_query(request, **overrides):
    params = request.GET.copy()
    params.pop("page", None)

    for key, value in overrides.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = str(value)

    return params.urlencode()


def save_form(form):
    try:
        with transaction.atomic():
            return form.save()

    except IntegrityError:
        form.add_error(
            None,
            "Record save nahi ho saka. "
            "Duplicate ya conflicting data "
            "check karein.",
        )
        return None


def change_status(request, model, pk, detail_name):
    """
    Explicit archive/restore actions prevent
    accidental reversal from repeated requests.
    """
    action = request.POST.get("action")

    with transaction.atomic():

        record = get_object_or_404(
            model.objects.select_for_update(),
            pk=pk,
        )

        if action not in ("archive", "restore"):
            messages.error(
                request,
                "Invalid status action.",
            )
            return redirect(
                detail_name,
                pk=record.pk,
            )

        target_state = action == "restore"

        if record.is_active == target_state:
            messages.info(
                request,
                "Record already has this status.",
            )
            return redirect(
                detail_name,
                pk=record.pk,
            )

        record.is_active = target_state

        try:
            record.full_clean()

        except ValidationError as error:
            messages.error(
                request,
                "; ".join(error.messages),
            )
            return redirect(
                detail_name,
                pk=record.pk,
            )

        record.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

    messages.success(
        request,
        "Status updated successfully.",
    )

    return redirect(
        detail_name,
        pk=record.pk,
    )


def delete_record(
    request,
    model,
    pk,
    record_type,
    list_name,
    detail_name,
):
    record = get_object_or_404(
        model,
        pk=pk,
    )

    if request.method == "POST":

        try:
            with transaction.atomic():
                record.delete()

        except ProtectedError:
            messages.error(
                request,
                "Related academic records exist. "
                "Archive this record instead.",
            )
            return redirect(
                detail_name,
                pk=pk,
            )

        messages.success(
            request,
            f"{record_type} deleted successfully.",
        )
        return redirect(list_name)

    return render(
        request,
        "semesters/delete_confirm.html",
        {
            "record": record,
            "record_type": record_type,
            "cancel_url": detail_name,
        },
    )


# =====================================================
# SEMESTER LIST + LIVE SEARCH
# =====================================================

@academic_admin_required
@require_GET
def semester_list(request):

    search = search_value(request)
    status = status_value(request)

    program_id = parse_id(
        request.GET.get("program")
    )

    semesters = (
        Semester.objects.select_related(
            "program",
            "program__department",
        )
    )

    if search:
        semesters = semesters.filter(
            Q(
                program__code__icontains=search
            )
            | Q(
                program__name__icontains=search
            )
            | Q(
                program__department__name__icontains=search
            )
            | Q(
                description__icontains=search
            )
        )

        # Searching "1" also finds Semester 1.
        if search.isascii() and search.isdecimal():
            number = int(search[:6])

            semesters = (
                Semester.objects.select_related(
                    "program",
                    "program__department",
                )
                .filter(
                    Q(pk__in=semesters.values("pk"))
                    | Q(number=number)
                )
            )

    if program_id is not None:
        semesters = semesters.filter(
            program_id=program_id
        )

    semesters = apply_status(
        semesters,
        status,
    )

    page_obj = get_page(
        request,
        semesters,
    )

    context = {
        "page_obj": page_obj,
        "search": search,
        "status": status,
        "selected_program": (
            ""
            if program_id is None
            else str(program_id)
        ),
        "programs": Program.objects.select_related(
            "department"
        ).order_by(
            "department__name",
            "code",
        ),
        "base_query": pagination_query(
            request,
            q=search,
            status=status,
            program=(
                ""
                if program_id is None
                else program_id
            ),
        ),
    }

    template = (
        "semesters/partials/semester_results.html"
        if is_ajax(request)
        else "semesters/semester_list.html"
    )

    return render(
        request,
        template,
        context,
    )


# =====================================================
# SEMESTER DETAIL
# =====================================================

@academic_admin_required
@require_GET
def semester_detail(request, pk):

    semester = get_object_or_404(
        Semester.objects.select_related(
            "program",
            "program__department",
        ),
        pk=pk,
    )

    sections = semester.sections.all()

    return render(
        request,
        "semesters/semester_detail.html",
        {
            "semester": semester,
            "sections": sections,
        },
    )


# =====================================================
# CREATE SEMESTER
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def semester_create(request):

    if request.method == "POST":
        form = SemesterForm(request.POST)

        if form.is_valid():
            record = save_form(form)

            if record is not None:
                messages.success(
                    request,
                    "Semester created successfully.",
                )
                return redirect(
                    "semesters:semester_detail",
                    pk=record.pk,
                )
    else:
        initial = {}

        program_id = parse_id(
            request.GET.get("program")
        )

        if program_id and program_id > 0:
            initial["program"] = program_id

        form = SemesterForm(
            initial=initial
        )

    return render(
        request,
        "semesters/record_form.html",
        {
            "form": form,
            "page_title": "Create Semester",
            "back_url": "semesters:semester_list",
        },
    )


# =====================================================
# EDIT SEMESTER
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def semester_edit(request, pk):

    semester = get_object_or_404(
        Semester,
        pk=pk,
    )

    if request.method == "POST":
        form = SemesterForm(
            request.POST,
            instance=semester,
        )

        if form.is_valid():
            record = save_form(form)

            if record is not None:
                messages.success(
                    request,
                    "Semester updated successfully.",
                )
                return redirect(
                    "semesters:semester_detail",
                    pk=record.pk,
                )

    else:
        form = SemesterForm(
            instance=semester
        )

    return render(
        request,
        "semesters/record_form.html",
        {
            "form": form,
            "page_title": "Edit Semester",
            "back_url": "semesters:semester_list",
        },
    )


# =====================================================
# SEMESTER ARCHIVE / RESTORE
# =====================================================

@academic_admin_required
@require_POST
def semester_toggle(request, pk):
    return change_status(
        request,
        Semester,
        pk,
        "semesters:semester_detail",
    )


# =====================================================
# DELETE SEMESTER
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def semester_delete(request, pk):
    return delete_record(
        request,
        Semester,
        pk,
        "Semester",
        "semesters:semester_list",
        "semesters:semester_detail",
    )


# =====================================================
# SECTION LIST + LIVE SEARCH
# =====================================================

@academic_admin_required
@require_GET
def section_list(request):

    search = search_value(request)
    status = status_value(request)

    program_id = parse_id(
        request.GET.get("program")
    )

    semester_id = parse_id(
        request.GET.get("semester")
    )

    # A semester must be selected within a program.
    if program_id is None:
        semester_id = None

    sections = (
        Section.objects.select_related(
            "semester",
            "semester__program",
            "semester__program__department",
        )
    )

    if search:
        sections = sections.filter(
            Q(code__icontains=search)
            | Q(
                semester__program__code__icontains=search
            )
            | Q(
                semester__program__name__icontains=search
            )
            | Q(description__icontains=search)
        )

    if program_id is not None:
        sections = sections.filter(
            semester__program_id=program_id
        )

    if semester_id is not None:
        sections = sections.filter(
            semester_id=semester_id
        )

    sections = apply_status(
        sections,
        status,
    )

    semester_options = Semester.objects.none()

    if program_id is not None and program_id > 0:
        semester_options = (
            Semester.objects.filter(
                program_id=program_id
            ).order_by("number")
        )

    page_obj = get_page(
        request,
        sections,
    )

    context = {
        "page_obj": page_obj,
        "search": search,
        "status": status,
        "selected_program": (
            ""
            if program_id is None
            else str(program_id)
        ),
        "selected_semester": (
            ""
            if semester_id is None
            else str(semester_id)
        ),
        "programs": Program.objects.select_related(
            "department"
        ).order_by(
            "department__name",
            "code",
        ),
        "semester_options": semester_options,
        "base_query": pagination_query(
            request,
            q=search,
            status=status,
            program=(
                ""
                if program_id is None
                else program_id
            ),
            semester=(
                ""
                if semester_id is None
                else semester_id
            ),
        ),
    }

    template = (
        "semesters/partials/section_results.html"
        if is_ajax(request)
        else "semesters/section_list.html"
    )

    return render(
        request,
        template,
        context,
    )


# =====================================================
# SECTION DETAIL
# =====================================================

@academic_admin_required
@require_GET
def section_detail(request, pk):

    section = get_object_or_404(
        Section.objects.select_related(
            "semester",
            "semester__program",
        ),
        pk=pk,
    )

    return render(
        request,
        "semesters/section_detail.html",
        {
            "section": section,
        },
    )


# =====================================================
# CREATE SECTION
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def section_create(request):

    if request.method == "POST":
        form = SectionForm(request.POST)

        if form.is_valid():
            record = save_form(form)

            if record is not None:
                messages.success(
                    request,
                    "Section created successfully.",
                )
                return redirect(
                    "semesters:section_detail",
                    pk=record.pk,
                )

    else:
        initial = {}

        semester_id = parse_id(
            request.GET.get("semester")
        )

        if semester_id and semester_id > 0:
            initial["semester"] = semester_id

        form = SectionForm(
            initial=initial
        )

    return render(
        request,
        "semesters/record_form.html",
        {
            "form": form,
            "page_title": "Create Section",
            "back_url": "semesters:section_list",
        },
    )


# =====================================================
# EDIT SECTION
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def section_edit(request, pk):

    section = get_object_or_404(
        Section,
        pk=pk,
    )

    if request.method == "POST":
        form = SectionForm(
            request.POST,
            instance=section,
        )

        if form.is_valid():
            record = save_form(form)

            if record is not None:
                messages.success(
                    request,
                    "Section updated successfully.",
                )
                return redirect(
                    "semesters:section_detail",
                    pk=record.pk,
                )

    else:
        form = SectionForm(
            instance=section
        )

    return render(
        request,
        "semesters/record_form.html",
        {
            "form": form,
            "page_title": "Edit Section",
            "back_url": "semesters:section_list",
        },
    )


# =====================================================
# SECTION ARCHIVE / RESTORE
# =====================================================

@academic_admin_required
@require_POST
def section_toggle(request, pk):
    return change_status(
        request,
        Section,
        pk,
        "semesters:section_detail",
    )


# =====================================================
# DELETE SECTION
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def section_delete(request, pk):
    return delete_record(
        request,
        Section,
        pk,
        "Section",
        "semesters:section_list",
        "semesters:section_detail",
    )


# =====================================================
# DEPENDENT DROPDOWN API:
# PROGRAM -> SEMESTERS
# =====================================================

@academic_admin_required
@require_GET
def semester_options_api(request):

    program_id = parse_id(
        request.GET.get("program")
    )

    if program_id is None or program_id < 1:
        return JsonResponse(
            {
                "error": "Valid program ID required.",
            },
            status=400,
        )

    semesters = Semester.objects.filter(
        program_id=program_id,
        is_active=True,
        program__is_active=True,
        program__department__is_active=True,
    ).order_by("number")

    return JsonResponse({
        "results": [
            {
                "id": semester.pk,
                "label": (
                    f"Semester {semester.number}"
                ),
            }
            for semester in semesters
        ],
    })


# =====================================================
# DEPENDENT DROPDOWN API:
# SEMESTER -> SECTIONS
# =====================================================

@academic_admin_required
@require_GET
def section_options_api(request):

    semester_id = parse_id(
        request.GET.get("semester")
    )

    if semester_id is None or semester_id < 1:
        return JsonResponse(
            {
                "error": "Valid semester ID required.",
            },
            status=400,
        )

    sections = Section.objects.filter(
        semester_id=semester_id,
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
        ],
    })
