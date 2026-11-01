"""Course/section-aware AssignHub assignment directory.

Only presentation and read-only query logic lives here. The existing
assignment detail, creation, grading, automatic plagiarism and permissions
remain responsible for all write operations.
"""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from courses.models import CourseOffering, CourseEnrollment
from timed_writing.models import TimedWritingAttempt

from .models import Assignment, Submission, PlagiarismScan
from .permissions import is_admin, is_student, is_teacher


PAGE_SIZE = 12
VALID_TABS = {"all", "published", "draft", "closed", "overdue", "due_soon"}
VALID_SORTS = {"newest", "oldest", "deadline", "course", "section", "most_submitted"}


def _positive_id(raw):
    """Return a safe PK for URL query parameters; ignore malformed values."""
    raw = str(raw or "")
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 15:
        return None
    number = int(raw)
    return number if number > 0 else None


def _url_with(request, **updates):
    """Build links without losing the user's current course/section/search filters."""
    params = request.GET.copy()
    params.pop("page", None)
    for key, value in updates.items():
        if value in (None, "", "all"):
            params.pop(key, None)
        else:
            params[key] = str(value)
    encoded = params.urlencode()
    url = reverse("assignments:list")
    return url + ("?" + encoded if encoded else "")


def _visible_assignments(user, *, teacher, student, admin):
    """Preserve the permission scope of the original assignment_list view."""
    if teacher:
        return Assignment.objects.filter(created_by=user)

    if student:
        return Assignment.objects.filter(
            status=Assignment.Status.PUBLISHED,
            course_offering__is_active=True,
            course_offering__course__is_active=True,
            course_offering__section__is_active=True,
            course_offering__course__semester__is_active=True,
            course_offering__course__program__is_active=True,
            course_offering__course__program__department__is_active=True,
            course_offering__enrollments__student=user,
            course_offering__enrollments__status=CourseEnrollment.Status.ACTIVE,
        ).distinct()

    if admin:
        return Assignment.objects.all()

    raise PermissionDenied("You cannot view assignments.")


def _visible_offerings(user, base_assignments, *, teacher, student, admin):
    """Use role-scoped offerings so filters never disclose other teachers' classes."""
    if teacher:
        return CourseOffering.objects.filter(teacher=user)

    if student:
        return CourseOffering.objects.filter(
            enrollments__student=user,
            enrollments__status=CourseEnrollment.Status.ACTIVE,
            is_active=True,
            course__is_active=True,
            section__is_active=True,
        ).distinct()

    if admin:
        return CourseOffering.objects.all()

    return CourseOffering.objects.none()


def _progress_annotations(queryset):
    """Count distinct enrolled students, final submissions and flagged reports."""
    return queryset.annotate(
        enrolled_count=Count(
            "course_offering__enrollments",
            filter=Q(
                course_offering__enrollments__status=CourseEnrollment.Status.ACTIVE
            ),
            distinct=True,
        ),
        submitted_count=Count(
            "submissions",
            filter=Q(
                submissions__status__in=[
                    Submission.Status.SUBMITTED,
                    Submission.Status.GRADED,
                ]
            ),
            distinct=True,
        ),
        awaiting_grade_count=Count(
            "submissions",
            filter=Q(submissions__status=Submission.Status.SUBMITTED),
            distinct=True,
        ),
        flagged_count=Count(
            "submissions",
            filter=Q(
                submissions__plagiarism_scan__status=PlagiarismScan.Status.NEEDS_REVIEW
            ),
            distinct=True,
        ),
        has_timed_attempt=Exists(
            TimedWritingAttempt.objects.filter(config__assignment_id=OuterRef("pk"))
        ),
    )


def assignment_directory(request):
    """Render the redesigned GET-only listing using the original role rules."""
    user = request.user
    teacher = is_teacher(user)
    student = is_student(user)
    admin = is_admin(user)
    show_progress = teacher or admin

    base = _visible_assignments(
        user, teacher=teacher, student=student, admin=admin
    )
    offerings = _visible_offerings(
        user, base, teacher=teacher, student=student, admin=admin
    )
    now = timezone.now()
    week_from_now = now + timedelta(days=7)

    # Keep the options scoped to the current user's authorized offerings.
    courses = (
        offerings.values("course_id", "course__code", "course__title")
        .distinct()
        .order_by("course__code", "course__title", "course_id")
    )
    course_counts = dict(
        base.exclude(course_offering__isnull=True)
        .values("course_offering__course_id")
        .annotate(total=Count("pk", distinct=True))
        .values_list("course_offering__course_id", "total")
    )
    course_choices = [
        {
            "id": row["course_id"],
            "label": f'{row["course__code"]} — {row["course__title"]}',
            "code": row["course__code"],
            "title": row["course__title"],
            "count": course_counts.get(row["course_id"], 0),
            "url": _url_with(request, course=row["course_id"], section=None, semester=None),
        }
        for row in courses
    ]

    course_id = _positive_id(request.GET.get("course"))
    section_id = _positive_id(request.GET.get("section"))
    semester_id = _positive_id(request.GET.get("semester"))

    selected_offerings = offerings
    if course_id is not None:
        selected_offerings = selected_offerings.filter(course_id=course_id)

    # Sections, semesters, years and terms are sourced from authorized offerings.
    sections = (
        selected_offerings.values(
            "section_id",
            "section__code",
            "section__semester__number",
            "section__semester__program__code",
        )
        .distinct()
        .order_by(
            "section__semester__program__code",
            "section__semester__number",
            "section__code",
            "section_id",
        )
    )
    section_choices = [
        {
            "id": row["section_id"],
            "label": (
                f'{row["section__semester__program__code"]} / '
                f'Sem {row["section__semester__number"]} / '
                f'Section {row["section__code"]}'
            ),
        }
        for row in sections
    ]
    semester_choices = [
        {"id": row["section__semester_id"],
         "label": (
             f'{row["section__semester__program__code"]} / '
             f'Semester {row["section__semester__number"]}'
         )}
        for row in selected_offerings.values(
            "section__semester_id",
            "section__semester__number",
            "section__semester__program__code",
        ).distinct().order_by(
            "section__semester__program__code",
            "section__semester__number",
            "section__semester_id",
        )
    ]

    year_choices = list(
        selected_offerings.order_by("-academic_year")
        .values_list("academic_year", flat=True).distinct()
    )
    term_choices = [
        {"value": term, "label": display}
        for term, display in CourseOffering.Term.choices
    ]

    search = (request.GET.get("q") or "").strip()[:120]
    year = (request.GET.get("year") or "").strip()[:9]
    term = (request.GET.get("term") or "").strip().upper()
    if term not in dict(CourseOffering.Term.choices):
        term = ""
    tab = (request.GET.get("status") or "all").strip().lower()
    if tab not in VALID_TABS:
        tab = "all"
    sort = (request.GET.get("sort") or "newest").strip().lower()
    if sort not in VALID_SORTS:
        sort = "newest"
    if student and sort == "most_submitted":
        sort = "newest"

    # Scope for counts / cards: course, section, semester, year and search.
    scoped = base
    if search:
        scoped = scoped.filter(
            Q(title__icontains=search)
            | Q(instructions__icontains=search)
            | Q(course_offering__course__code__icontains=search)
            | Q(course_offering__course__title__icontains=search)
            | Q(course_offering__section__code__icontains=search)
        )
    if course_id is not None:
        scoped = scoped.filter(course_offering__course_id=course_id)
    if section_id is not None:
        scoped = scoped.filter(course_offering__section_id=section_id)
    if semester_id is not None:
        scoped = scoped.filter(
            course_offering__section__semester_id=semester_id
        )
    if year:
        scoped = scoped.filter(course_offering__academic_year=year)
    if term:
        scoped = scoped.filter(course_offering__term=term)

    summary = scoped.aggregate(
        total=Count("pk", distinct=True),
        published=Count(
            "pk", filter=Q(status=Assignment.Status.PUBLISHED), distinct=True
        ),
        draft=Count(
            "pk", filter=Q(status=Assignment.Status.DRAFT), distinct=True
        ),
        closed=Count(
            "pk", filter=Q(status=Assignment.Status.CLOSED), distinct=True
        ),
        overdue=Count(
            "pk",
            filter=Q(status=Assignment.Status.PUBLISHED, deadline__lt=now),
            distinct=True,
        ),
        due_soon=Count(
            "pk",
            filter=Q(
                status=Assignment.Status.PUBLISHED,
                deadline__gte=now,
                deadline__lte=week_from_now,
            ),
            distinct=True,
        ),
    )

    # Apply a status tab on top of the academic/search scope.
    assignments = scoped
    if tab == "published":
        assignments = assignments.filter(status=Assignment.Status.PUBLISHED)
    elif tab == "draft":
        assignments = assignments.filter(status=Assignment.Status.DRAFT)
    elif tab == "closed":
        assignments = assignments.filter(status=Assignment.Status.CLOSED)
    elif tab == "overdue":
        assignments = assignments.filter(
            status=Assignment.Status.PUBLISHED, deadline__lt=now
        )
    elif tab == "due_soon":
        assignments = assignments.filter(
            status=Assignment.Status.PUBLISHED,
            deadline__gte=now,
            deadline__lte=week_from_now,
        )

    assignments = assignments.select_related(
        "created_by",
        "course_offering",
        "course_offering__course",
        "course_offering__course__program",
        "course_offering__section",
        "course_offering__section__semester",
        "course_offering__section__semester__program",
    )
    if show_progress:
        assignments = _progress_annotations(assignments)

    ordering = {
        "newest": ("-created_at", "-pk"),
        "oldest": ("created_at", "pk"),
        "deadline": ("deadline", "pk"),
        "course": (
            "course_offering__course__code",
            "course_offering__section__code",
            "-created_at",
            "-pk",
        ),
        "section": (
            "course_offering__section__semester__number",
            "course_offering__section__code",
            "course_offering__course__code",
            "-created_at",
            "-pk",
        ),
        "most_submitted": ("-submitted_count", "deadline", "pk"),
    }
    assignments = assignments.order_by(*ordering[sort])

    paginator = Paginator(assignments, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    available_tabs = [
        ("all", "All", summary["total"]),
        ("published", "Published", summary["published"]),
    ]
    if not student:
        available_tabs.extend([
            ("draft", "Draft", summary["draft"]),
            ("closed", "Closed", summary["closed"]),
        ])
    available_tabs.extend([
        ("due_soon", "Due Soon", summary["due_soon"]),
        ("overdue", "Overdue", summary["overdue"]),
    ])
    status_tabs = [
        {"value": value, "label": label, "count": count,
         "active": value == tab, "url": _url_with(request, status=value)}
        for value, label, count in available_tabs
    ]

    # Pagination links preserve every active filter and sort parameter.
    def page_url(number):
        params = request.GET.copy()
        params["page"] = str(number)
        query = params.urlencode()
        return reverse("assignments:list") + ("?" + query if query else "")

    page_urls = {
        "first": page_url(1),
        "previous": page_url(page_obj.previous_page_number())
            if page_obj.has_previous() else "",
        "next": page_url(page_obj.next_page_number())
            if page_obj.has_next() else "",
        "last": page_url(paginator.num_pages),
    }

    has_filters = bool(
        search or course_id or section_id or semester_id or year or term
        or tab != "all" or sort != "newest"
    )

    return render(request, "assignments/assignment_list.html", {
        # Keeping `assignments` as a QuerySet preserves old tests/integrations.
        "assignments": assignments,
        "page_assignments": page_obj.object_list,
        "page_obj": page_obj,
        "filtered_count": paginator.count,
        "show_progress": show_progress,
        "can_create": teacher,
        "is_teacher_user": teacher,
        "is_student_user": student,
        "is_admin_user": admin,
        "summary": summary,
        "status_tabs": status_tabs,
        "course_choices": course_choices,
        "section_choices": section_choices,
        "semester_choices": semester_choices,
        "year_choices": year_choices,
        "term_choices": term_choices,
        "selected_course": course_id,
        "selected_section": section_id,
        "selected_semester": semester_id,
        "selected_year": year,
        "selected_term": term,
        "selected_status": tab,
        "selected_sort": sort,
        "search_query": search,
        "page_urls": page_urls,
        "clear_url": reverse("assignments:list"),
        "has_filters": has_filters,
        "now": now,
        "one_week_from_now": week_from_now,
    })
