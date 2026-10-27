
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.views.decorators.http import (
    require_http_methods,
    require_POST,
)

from .forms import DepartmentForm, ProgramForm
from .models import Department, Program
from .permissions import academic_admin_required


MAX_SEARCH_LENGTH = 100
MAX_DEPARTMENT_FILTER_LENGTH = 18
PAGE_SIZE = 10


# =====================================================
# COMMON HELPERS
# =====================================================

def save_record(form):
    """
    Save an already validated ModelForm.

    An atomic transaction protects the database
    from partially completed writes.
    """

    try:
        with transaction.atomic():
            return form.save()

    except IntegrityError:
        form.add_error(
            None,
            "This record conflicts with an existing "
            "record. Please check the code and "
            "department.",
        )

        return None


def filter_status(queryset, status):
    if status == "active":
        return queryset.filter(is_active=True)

    if status == "inactive":
        return queryset.filter(is_active=False)

    return queryset


def safe_search(request):
    return (
        request.GET.get("q", "")
        .strip()[:MAX_SEARCH_LENGTH]
    )


def safe_status(request):
    status = request.GET.get("status", "all")

    if status in ("all", "active", "inactive"):
        return status

    return "all"


def requested_active_state(request, current_state):
    """
    New UI sends an explicit archive/restore action.

    The legacy 'toggle' behavior remains supported
    for existing tests and old clients.

    Explicit actions are idempotent:
    submitting 'archive' twice stays archived.
    """

    action = request.POST.get(
        "action",
        "toggle",
    )

    if action == "archive":
        return False

    if action == "restore":
        return True

    if action == "toggle":
        return not current_state

    raise ValueError("Invalid status action.")


# =====================================================
# DEPARTMENT LIST
# =====================================================

@academic_admin_required
@require_http_methods(["GET"])
def department_list(request):
    search = safe_search(request)
    status = safe_status(request)

    departments = Department.objects.all()

    if search:
        departments = departments.filter(
            Q(code__icontains=search)
            | Q(name__icontains=search)
            | Q(description__icontains=search)
        )

    departments = filter_status(
        departments,
        status,
    )

    paginator = Paginator(
        departments,
        PAGE_SIZE,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    return render(
        request,
        "departments/department_list.html",
        {
            "page_obj": page_obj,
            "search": search,
            "status": status,
        },
    )


# =====================================================
# DEPARTMENT DETAIL
# =====================================================

@academic_admin_required
@require_http_methods(["GET"])
def department_detail(request, pk):
    department = get_object_or_404(
        Department,
        pk=pk,
    )

    programs = department.programs.all()

    return render(
        request,
        "departments/department_detail.html",
        {
            "department": department,
            "programs": programs,
        },
    )


# =====================================================
# CREATE DEPARTMENT
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def department_create(request):
    if request.method == "POST":
        form = DepartmentForm(request.POST)

        if form.is_valid():
            department = save_record(form)

            if department is not None:
                messages.success(
                    request,
                    "Department created successfully.",
                )

                return redirect(
                    "departments:department_detail",
                    pk=department.pk,
                )

    else:
        form = DepartmentForm()

    return render(
        request,
        "departments/record_form.html",
        {
            "form": form,
            "page_title": "Create Department",
            "back_url": "departments:department_list",
        },
    )


# =====================================================
# EDIT DEPARTMENT
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def department_edit(request, pk):
    department = get_object_or_404(
        Department,
        pk=pk,
    )

    if request.method == "POST":
        form = DepartmentForm(
            request.POST,
            instance=department,
        )

        if form.is_valid():
            updated = save_record(form)

            if updated is not None:
                messages.success(
                    request,
                    "Department updated successfully.",
                )

                return redirect(
                    "departments:department_detail",
                    pk=department.pk,
                )

    else:
        form = DepartmentForm(
            instance=department,
        )

    return render(
        request,
        "departments/record_form.html",
        {
            "form": form,
            "page_title": "Edit Department",
            "back_url": "departments:department_list",
        },
    )


# =====================================================
# ARCHIVE / RESTORE DEPARTMENT
# =====================================================

@academic_admin_required
@require_POST
def department_toggle(request, pk):

    with transaction.atomic():
        department = get_object_or_404(
            Department.objects.select_for_update(),
            pk=pk,
        )

        try:
            target_state = requested_active_state(
                request,
                department.is_active,
            )

        except ValueError:
            messages.error(
                request,
                "Invalid department status action.",
            )

            return redirect(
                "departments:department_detail",
                pk=department.pk,
            )

        if department.is_active == target_state:
            messages.info(
                request,
                "Department is already in "
                "the requested state.",
            )

            return redirect(
                "departments:department_detail",
                pk=department.pk,
            )

        department.is_active = target_state

        try:
            department.full_clean()

        except ValidationError as error:
            messages.error(
                request,
                "; ".join(error.messages),
            )

            return redirect(
                "departments:department_detail",
                pk=department.pk,
            )

        department.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

    messages.success(
        request,
        "Department status updated successfully.",
    )

    return redirect(
        "departments:department_detail",
        pk=department.pk,
    )


# =====================================================
# DELETE DEPARTMENT
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def department_delete(request, pk):
    department = get_object_or_404(
        Department,
        pk=pk,
    )

    if request.method == "POST":
        try:
            with transaction.atomic():
                department.delete()

        except ProtectedError:
            messages.error(
                request,
                "This department has related records. "
                "Archive it instead of deleting it.",
            )

            return redirect(
                "departments:department_detail",
                pk=pk,
            )

        messages.success(
            request,
            "Department deleted successfully.",
        )

        return redirect(
            "departments:department_list"
        )

    return render(
        request,
        "departments/delete_confirm.html",
        {
            "record": department,
            "record_type": "Department",
            "cancel_url": "departments:department_detail",
        },
    )


# =====================================================
# PROGRAM LIST
# =====================================================

@academic_admin_required
@require_http_methods(["GET"])
def program_list(request):
    search = safe_search(request)
    status = safe_status(request)

    department_id = request.GET.get(
        "department",
        "",
    ).strip()

    programs = Program.objects.select_related(
        "department"
    )

    if search:
        programs = programs.filter(
            Q(code__icontains=search)
            | Q(name__icontains=search)
            | Q(department__name__icontains=search)
        )

    programs = filter_status(
        programs,
        status,
    )

    if department_id:
        valid_id = (
            department_id.isascii()
            and department_id.isdecimal()
            and len(department_id)
            <= MAX_DEPARTMENT_FILTER_LENGTH
        )

        if valid_id:
            programs = programs.filter(
                department_id=int(department_id)
            )

        else:
            programs = programs.none()

    paginator = Paginator(
        programs,
        PAGE_SIZE,
    )

    page_obj = paginator.get_page(
        request.GET.get("page")
    )

    departments = Department.objects.order_by(
        "name"
    )

    return render(
        request,
        "departments/program_list.html",
        {
            "page_obj": page_obj,
            "departments": departments,
            "search": search,
            "status": status,
            "selected_department": department_id,
        },
    )


# =====================================================
# PROGRAM DETAIL
# =====================================================

@academic_admin_required
@require_http_methods(["GET"])
def program_detail(request, pk):
    program = get_object_or_404(
        Program.objects.select_related(
            "department"
        ),
        pk=pk,
    )

    return render(
        request,
        "departments/program_detail.html",
        {
            "program": program,
        },
    )


# =====================================================
# CREATE PROGRAM
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def program_create(request):
    if request.method == "POST":
        form = ProgramForm(request.POST)

        if form.is_valid():
            program = save_record(form)

            if program is not None:
                messages.success(
                    request,
                    "Program created successfully.",
                )

                return redirect(
                    "departments:program_detail",
                    pk=program.pk,
                )

    else:
        initial = {}

        department_id = request.GET.get(
            "department",
        )

        if department_id:
            initial["department"] = department_id

        form = ProgramForm(initial=initial)

    return render(
        request,
        "departments/record_form.html",
        {
            "form": form,
            "page_title": "Create Program",
            "back_url": "departments:program_list",
        },
    )


# =====================================================
# EDIT PROGRAM
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def program_edit(request, pk):
    program = get_object_or_404(
        Program,
        pk=pk,
    )

    if request.method == "POST":
        form = ProgramForm(
            request.POST,
            instance=program,
        )

        if form.is_valid():
            updated = save_record(form)

            if updated is not None:
                messages.success(
                    request,
                    "Program updated successfully.",
                )

                return redirect(
                    "departments:program_detail",
                    pk=program.pk,
                )

    else:
        form = ProgramForm(
            instance=program,
        )

    return render(
        request,
        "departments/record_form.html",
        {
            "form": form,
            "page_title": "Edit Program",
            "back_url": "departments:program_list",
        },
    )


# =====================================================
# ARCHIVE / RESTORE PROGRAM
# =====================================================

@academic_admin_required
@require_POST
def program_toggle(request, pk):

    with transaction.atomic():
        program = get_object_or_404(
            Program.objects.select_for_update(),
            pk=pk,
        )

        try:
            target_state = requested_active_state(
                request,
                program.is_active,
            )

        except ValueError:
            messages.error(
                request,
                "Invalid program status action.",
            )

            return redirect(
                "departments:program_detail",
                pk=program.pk,
            )

        if program.is_active == target_state:
            messages.info(
                request,
                "Program is already in "
                "the requested state.",
            )

            return redirect(
                "departments:program_detail",
                pk=program.pk,
            )

        program.is_active = target_state

        try:
            program.full_clean()

        except ValidationError as error:
            messages.error(
                request,
                "; ".join(error.messages),
            )

            return redirect(
                "departments:program_detail",
                pk=program.pk,
            )

        program.save(
            update_fields=[
                "is_active",
                "updated_at",
            ]
        )

    messages.success(
        request,
        "Program status updated successfully.",
    )

    return redirect(
        "departments:program_detail",
        pk=program.pk,
    )


# =====================================================
# DELETE PROGRAM
# =====================================================

@academic_admin_required
@require_http_methods(["GET", "POST"])
def program_delete(request, pk):
    program = get_object_or_404(
        Program,
        pk=pk,
    )

    if request.method == "POST":
        try:
            with transaction.atomic():
                program.delete()

        except ProtectedError:
            messages.error(
                request,
                "This program has related records. "
                "Archive it instead of deleting it.",
            )

            return redirect(
                "departments:program_detail",
                pk=pk,
            )

        messages.success(
            request,
            "Program deleted successfully.",
        )

        return redirect(
            "departments:program_list"
        )

    return render(
        request,
        "departments/delete_confirm.html",
        {
            "record": program,
            "record_type": "Program",
            "cancel_url": "departments:program_detail",
        },
    )
