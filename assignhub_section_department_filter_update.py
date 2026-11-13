from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent

def load(path):
    p = ROOT / path
    if not p.is_file():
        raise FileNotFoundError(path)
    return p.read_text(encoding="utf-8")

def save(path, data):
    (ROOT / path).write_text(data, encoding="utf-8")

def sub_once(data, pattern, replacement, label, flags=re.S):
    updated, count = re.subn(pattern, replacement, data, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}.")
    return updated

# SectionForm: temporary Department and Program fields, with server-side
# validation that the selected hierarchy matches the Section.semester FK.
p = "semesters/forms.py"
data = load(p)
section_form = r'''class SectionForm(StyledModelForm):

    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=True,
        label="Department",
        empty_label="Select Department",
    )
    program = forms.ModelChoiceField(
        queryset=Program.objects.none(),
        required=True,
        label="Program",
        empty_label="Select Program",
    )

    class Meta:
        model = Section
        fields = [
            "semester", "code", "capacity",
            "description", "is_active",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"placeholder": "e.g. A"}),
            "capacity": forms.NumberInput(attrs={"min": 1, "max": 500}),
            "description": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        current_semester = self.instance.semester if self.instance.pk else None
        current_program_id = current_semester.program_id if current_semester else None
        current_department_id = (
            current_semester.program.department_id if current_semester else None
        )

        if self.is_bound:
            department_id = self.data.get(self.add_prefix("department"))
            program_id = self.data.get(self.add_prefix("program"))
        else:
            department_id = self.initial.get("department") or current_department_id
            program_id = self.initial.get("program") or current_program_id

        departments = Department.objects.filter(is_active=True)
        if current_department_id:
            departments = departments | Department.objects.filter(
                pk=current_department_id
            )
        self.fields["department"].queryset = departments.order_by("name")

        programs = Program.objects.none()
        if department_id:
            programs = Program.objects.filter(
                department_id=department_id,
                is_active=True,
                department__is_active=True,
            )
            if current_program_id and str(department_id) == str(current_department_id):
                programs = programs | Program.objects.filter(
                    pk=current_program_id,
                    department_id=current_department_id,
                )
        self.fields["program"].queryset = (
            programs.select_related("department").order_by("code")
        )

        semesters = Semester.objects.none()
        if program_id:
            semesters = Semester.objects.filter(
                program_id=program_id,
                is_active=True,
                program__is_active=True,
                program__department__is_active=True,
            )
            if current_semester and str(program_id) == str(current_program_id):
                semesters = semesters | Semester.objects.filter(
                    pk=current_semester.pk
                )
        self.fields["semester"].queryset = (
            semesters.select_related("program", "program__department")
            .order_by("number")
        )

        self.order_fields([
            "department", "program", "semester", "code",
            "capacity", "description", "is_active",
        ])
        self.fields["department"].widget.attrs["id"] = "id_department"
        self.fields["program"].widget.attrs["id"] = "id_program"
        self.fields["semester"].widget.attrs["id"] = "id_semester"

    def clean(self):
        cleaned = super().clean()
        department = cleaned.get("department")
        program = cleaned.get("program")
        semester = cleaned.get("semester")

        if department and program and program.department_id != department.pk:
            self.add_error(
                "program",
                "Selected program does not belong to the selected department.",
            )
        if program and semester and semester.program_id != program.pk:
            self.add_error(
                "semester",
                "Selected semester does not belong to the selected program.",
            )
        if department and semester:
            if semester.program.department_id != department.pk:
                self.add_error(
                    "semester",
                    "Selected semester does not belong to the selected department.",
                )
        return cleaned

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()
'''
data = sub_once(data, r"class SectionForm\(StyledModelForm\):.*\Z", section_form + "\n",
                "Replace SectionForm")
save(p, data)

# Section list view: add Department filtering and dropdown context.
p = "semesters/views.py"
data = load(p)
data = sub_once(
    data,
    r'''    program_id = parse_id\(
        request\.GET\.get\("program"\)
    \)

    semester_id = parse_id\(
        request\.GET\.get\("semester"\)
    \)

    # A semester must be selected within a program\.
    if program_id is None:
        semester_id = None
''',
    '''    department_id = parse_id(request.GET.get("department"))
    program_id = parse_id(request.GET.get("program"))
    semester_id = parse_id(request.GET.get("semester"))

    # Backward compatibility for URLs that contain program only.
    if department_id is None and program_id and program_id > 0:
        selected_program = Program.objects.filter(
            pk=program_id
        ).only("department_id").first()
        if selected_program:
            department_id = selected_program.department_id

    if program_id is None:
        semester_id = None
''',
    "Section list filter variables",
)
data = sub_once(
    data,
    r'''    if program_id is not None:
        sections = sections\.filter\(
            semester__program_id=program_id
        \)
''',
    '''    if department_id is not None:
        sections = sections.filter(
            semester__program__department_id=department_id
        )

    if program_id is not None:
        sections = sections.filter(
            semester__program_id=program_id
        )
''',
    "Department queryset filter",
)
data = sub_once(
    data,
    r'''    semester_options = Semester\.objects\.none\(\)

    if program_id is not None and program_id > 0:
        semester_options = \(
            Semester\.objects\.filter\(
                program_id=program_id
            \)\.order_by\("number"\)
        \)
''',
    '''    # List filters include archived hierarchy records so old sections
    # remain discoverable.
    departments = Department.objects.order_by("name")

    programs = Program.objects.none()
    if department_id is not None and department_id > 0:
        programs = Program.objects.filter(
            department_id=department_id
        ).order_by("code")

    semester_options = Semester.objects.none()
    if program_id is not None and program_id > 0:
        semester_options = Semester.objects.filter(
            program_id=program_id
        ).order_by("number")
''',
    "Section list dropdown querysets",
)
data = sub_once(
    data,
    r'''        "status": status,
        "selected_program": \(
''',
    '''        "status": status,
        "departments": departments,
        "selected_department": (
            "" if department_id is None else str(department_id)
        ),
        "selected_program": (
''',
    "Section list selected department context",
)
data = sub_once(
    data,
    r'''"programs": Program\.objects\.select_related\(
            "department"
        \)\.order_by\(
            "department__name",
            "code",
        \),''',
    '"programs": programs,',
    "Section list programs context",
)
data = sub_once(
    data,
    r'''            status=status,
            program=\(
                ""
                if program_id is None
                else program_id
            \),''',
    '''            status=status,
            department=(
                "" if department_id is None else department_id
            ),
            program=(
                "" if program_id is None else program_id
            ),''',
    "Section pagination preserves department",
)

# Prefill all three hierarchy fields when Section Create is opened from
# a Semester context/detail page.
data = sub_once(
    data,
    r'''        if semester_id and semester_id > 0:
            initial\["semester"\] = semester_id
''',
    '''        if semester_id and semester_id > 0:
            selected_semester = Semester.objects.select_related(
                "program", "program__department"
            ).filter(pk=semester_id).first()
            if selected_semester:
                initial["semester"] = selected_semester.pk
                initial["program"] = selected_semester.program_id
                initial["department"] = selected_semester.program.department_id
''',
    "Section create hierarchy prefill",
)

# Existing APIs remain active-only by default. The list screen explicitly
# requests include_archived=1 so historical records can be filtered.
data = sub_once(
    data,
    r'''    semesters = Semester\.objects\.filter\(
        program_id=program_id,
        is_active=True,
        program__is_active=True,
        program__department__is_active=True,
    \)\.order_by\("number"\)''',
    '''    semesters = Semester.objects.filter(program_id=program_id)
    if request.GET.get("include_archived") != "1":
        semesters = semesters.filter(
            is_active=True,
            program__is_active=True,
            program__department__is_active=True,
        )
    semesters = semesters.order_by("number")''',
    "Semester options API archive-aware mode",
)
data = sub_once(
    data,
    r'''    programs = Program\.objects\.filter\(
        department_id=department_id,
        is_active=True,
        department__is_active=True,
    \)\.order_by\("code"\)''',
    '''    programs = Program.objects.filter(department_id=department_id)
    if request.GET.get("include_archived") != "1":
        programs = programs.filter(
            is_active=True,
            department__is_active=True,
        )
    programs = programs.order_by("code")''',
    "Program options API archive-aware mode",
)
save(p, data)

# Shared form template: Department > Program > Semester cascade.
save("templates/semesters/record_form.html", r'''{% extends "base.html" %}

{% block title %}{{ page_title }} | AssignHub{% endblock %}

{% block content %}
<div class="container py-3">
    <div class="row justify-content-center">
        <div class="col-lg-8">
            <div class="card shadow-sm">
                <div class="card-body p-4">
                    <h2 class="fw-bold mb-4">{{ page_title }}</h2>
                    <form method="post" novalidate>
                        {% csrf_token %}
                        {% if form.non_field_errors %}
                        <div class="alert alert-danger">{{ form.non_field_errors }}</div>
                        {% endif %}

                        {% for field in form %}
                            {% if field.name == "is_active" %}
                            <div class="form-check mb-3">
                                {{ field }}
                                <label class="form-check-label" for="{{ field.id_for_label }}">{{ field.label }}</label>
                                {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                            </div>
                            {% else %}
                            <div class="mb-3">
                                <label class="form-label fw-semibold" for="{{ field.id_for_label }}">{{ field.label }}</label>
                                {{ field }}
                                {% if field.name == "department" %}
                                <div class="form-text">First select the department.</div>
                                {% elif field.name == "program" %}
                                <div class="form-text">Programs are filtered by the selected department.</div>
                                {% elif field.name == "semester" and form.department %}
                                <div class="form-text">Select the program first, then choose its semester.</div>
                                {% endif %}
                                {% if field.help_text %}<div class="form-text">{{ field.help_text }}</div>{% endif %}
                                {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                            </div>
                            {% endif %}
                        {% endfor %}

                        <div class="d-flex gap-2 mt-4">
                            <button type="submit" class="btn btn-dark">Save</button>
                            <a href="{% url back_url %}" class="btn btn-outline-secondary">Cancel</a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% if form.department %}
{% block extra_js %}
{{ block.super }}
<script>
document.addEventListener("DOMContentLoaded", function () {
    const department = document.getElementById("id_department");
    const program = document.getElementById("id_program");
    const semester = document.getElementById("id_semester");
    if (!department || !program) return;

    const programsApi = "{% url 'semesters:program_options_api' %}";
    const semestersApi = "{% url 'semesters:semester_options_api' %}";

    function reset(select, label) {
        if (select) select.replaceChildren(new Option(label, ""));
    }

    async function load(select, api, key, value, placeholder) {
        reset(select, "Loading...");
        select.disabled = true;
        if (!value) {
            reset(select, placeholder);
            return;
        }
        try {
            const url = new URL(api, window.location.origin);
            url.searchParams.set(key, value);
            const response = await fetch(url.toString(), {
                credentials: "same-origin",
                headers: {"X-Requested-With": "XMLHttpRequest"}
            });
            if (!response.ok) throw new Error("Could not load options");
            const payload = await response.json();
            reset(select, placeholder);
            payload.results.forEach(item =>
                select.add(new Option(item.label, String(item.id)))
            );
            select.disabled = payload.results.length === 0;
            if (!payload.results.length) reset(select, "No options available");
        } catch (error) {
            reset(select, "Could not load options");
            select.disabled = true;
            console.error(error);
        }
    }

    department.addEventListener("change", async function () {
        await load(program, programsApi, "department", this.value, "Select Program");
        if (semester) {
            reset(semester, "Select Program First");
            semester.disabled = true;
        }
    });

    if (semester) {
        program.addEventListener("change", function () {
            load(semester, semestersApi, "program", this.value, "Select Semester");
        });
    }

    // Keep server-selected options intact on first render (especially edit forms).
    program.disabled = !department.value;
    if (semester) semester.disabled = !program.value;
});
</script>
{% endblock %}
{% endif %}
''')

# Department-aware Section List.
save("templates/semesters/section_list.html", r'''{% extends "base.html" %}
{% load static %}

{% block title %}Sections | AssignHub{% endblock %}

{% block content %}
<div class="container py-3">
    <div class="d-flex justify-content-between align-items-center flex-wrap gap-3 mb-4">
        <div>
            <h2 class="fw-bold mb-1">Sections</h2>
            <p class="text-muted mb-0">Filter sections by department, program and semester.</p>
        </div>
        <div class="d-flex gap-2">
            <a href="{% url 'semesters:semester_list' %}" class="btn btn-outline-dark">Semesters</a>
            <a href="{% url 'semesters:section_create' %}" class="btn btn-dark">+ Add Section</a>
        </div>
    </div>

    <div class="card shadow-sm mb-4">
        <div class="card-body">
            <form method="get" action="{% url 'semesters:section_list' %}"
                  data-live-search data-results-target="section-results"
                  data-debounce="200"
                  data-programs-api="{% url 'semesters:program_options_api' %}"
                  data-semesters-api="{% url 'semesters:semester_options_api' %}"
                  data-include-archived="1" class="row g-3">

                <div class="col-md-3">
                    <label for="section-search" class="form-label">Live Search</label>
                    <input id="section-search" type="search" name="q" value="{{ search }}"
                           class="form-control" autocomplete="off" placeholder="Search section code">
                </div>

                <div class="col-md-3">
                    <label for="section-department" class="form-label">Department</label>
                    <select id="section-department" name="department" class="form-select">
                        <option value="">All Departments</option>
                        {% for department in departments %}
                        <option value="{{ department.pk }}" {% if selected_department == department.pk|stringformat:"s" %}selected{% endif %}>
                            {{ department.code }} - {{ department.name }}
                        </option>
                        {% endfor %}
                    </select>
                </div>

                <div class="col-md-2">
                    <label for="section-program" class="form-label">Program</label>
                    <select id="section-program" name="program" class="form-select" {% if not selected_department %}disabled{% endif %}>
                        <option value="">All Programs</option>
                        {% for program in programs %}
                        <option value="{{ program.pk }}" {% if selected_program == program.pk|stringformat:"s" %}selected{% endif %}>
                            {{ program.code }}
                        </option>
                        {% endfor %}
                    </select>
                </div>

                <div class="col-md-2">
                    <label for="section-semester" class="form-label">Semester</label>
                    <select id="section-semester" name="semester" class="form-select" {% if not selected_program %}disabled{% endif %}>
                        <option value="">All Semesters</option>
                        {% for semester in semester_options %}
                        <option value="{{ semester.pk }}" {% if selected_semester == semester.pk|stringformat:"s" %}selected{% endif %}>
                            Semester {{ semester.number }}
                        </option>
                        {% endfor %}
                    </select>
                </div>

                <div class="col-md-2">
                    <label for="section-status" class="form-label">Status</label>
                    <select id="section-status" name="status" class="form-select">
                        <option value="all" {% if status == "all" %}selected{% endif %}>All</option>
                        <option value="active" {% if status == "active" %}selected{% endif %}>Active</option>
                        <option value="inactive" {% if status == "inactive" %}selected{% endif %}>Archived</option>
                    </select>
                </div>

                <div class="col-12">
                    <button type="submit" class="btn btn-outline-dark btn-sm">Apply Filters</button>
                </div>
            </form>
            <div class="small text-muted mt-2" data-search-notice role="status" aria-live="polite"></div>
        </div>
    </div>

    <div id="section-results" aria-live="polite">
        {% include "semesters/partials/section_results.html" %}
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script defer src="{% static 'js/academic-live-search.js' %}"></script>
{% endblock %}
''')

# Enhance existing AJAX dropdown script without replacing its search/pagination code.
p = "static/js/academic-live-search.js"
data = load(p)
data = sub_once(
    data,
    r'''    const programSelect = form\.querySelector\(
        'select\[name="program"\]'
    \);

    const semesterSelect = form\.querySelector\(
        'select\[name="semester"\]'
    \);

    const semestersApi = form\.dataset\.semestersApi;''',
    '''    const departmentSelect = form.querySelector(
        'select[name="department"]'
    );

    const programSelect = form.querySelector(
        'select[name="program"]'
    );

    const semesterSelect = form.querySelector(
        'select[name="semester"]'
    );

    const programsApi = form.dataset.programsApi;
    const semestersApi = form.dataset.semestersApi;
    const includeArchived = form.dataset.includeArchived === "1";''',
    "Live search dropdown references",
)
data = sub_once(
    data,
    r'''        if \(
            target === programSelect
            && semesterSelect
            && semestersApi
        \) \{
            updateSemesterOptions\(
                target\.value
            \);
        \}

        scheduleSearch\(\);''',
    '''        if (target === departmentSelect && programSelect && programsApi) {
            updateProgramOptions(target.value);
        } else if (target === programSelect && semesterSelect && semestersApi) {
            updateSemesterOptions(target.value);
        }

        scheduleSearch();''',
    "Live search cascading change handler",
)
data = sub_once(
    data,
    r'''    // -----------------------------------------------
    // PROGRAM -> SEMESTER DEPENDENT DROPDOWN
    // -----------------------------------------------

    async function updateSemesterOptions\(programId\) \{''',
    '''    // -----------------------------------------------
    // DEPARTMENT -> PROGRAM DEPENDENT DROPDOWN
    // -----------------------------------------------

    async function updateProgramOptions(departmentId) {
        if (!programSelect || !programsApi) return;

        dropdownVersion += 1;
        const version = dropdownVersion;
        if (dropdownController) {
            dropdownController.abort();
            dropdownController = null;
        }

        programSelect.replaceChildren(new Option("All Programs", ""));
        programSelect.disabled = true;
        if (semesterSelect) {
            semesterSelect.replaceChildren(new Option("All Semesters", ""));
            semesterSelect.disabled = true;
        }
        if (!departmentId) return;

        const controller = new AbortController();
        dropdownController = controller;
        const url = new URL(programsApi, window.location.origin);
        url.searchParams.set("department", departmentId);
        if (includeArchived) url.searchParams.set("include_archived", "1");

        try {
            const response = await fetch(url.toString(), {
                method: "GET",
                credentials: "same-origin",
                headers: {"Accept": "application/json"},
                signal: controller.signal
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const payload = await response.json();
            if (version !== dropdownVersion) return;

            payload.results.forEach(item =>
                programSelect.add(new Option(item.label, String(item.id)))
            );
            programSelect.disabled = false;
        } catch (error) {
            if (error.name !== "AbortError" && version === dropdownVersion) {
                setNotice("Unable to load programs. Please select the department again.");
            }
        } finally {
            if (dropdownController === controller) dropdownController = null;
        }
    }


    // -----------------------------------------------
    // PROGRAM -> SEMESTER DEPENDENT DROPDOWN
    // -----------------------------------------------

    async function updateSemesterOptions(programId) {''',
    "Insert Department to Program AJAX loader",
)
data = sub_once(
    data,
    r'''        url\.searchParams\.set\(
            "program",
            programId
        \);

        try \{''',
    '''        url.searchParams.set("program", programId);
        if (includeArchived) {
            url.searchParams.set("include_archived", "1");
        }

        try {''',
    "List-only archived semester query parameter",
)
save(p, data)

print("Section Department > Program > Semester implementation applied.")
print("Updated:")
for item in (
    "semesters/forms.py",
    "semesters/views.py",
    "templates/semesters/record_form.html",
    "templates/semesters/section_list.html",
    "static/js/academic-live-search.js",
):
    print(" - " + item)
print("No model changes or migrations were made.")
print("Run: python manage.py test semesters")
