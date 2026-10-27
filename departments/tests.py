
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import (
    Client,
    TestCase,
    override_settings,
)
from django.urls import reverse

from accounts.models import UserProfile

from .forms import DepartmentForm, ProgramForm
from .models import Department, Program
from .permissions import is_academic_admin


User = get_user_model()


def department_payload(**kwargs):
    data = {
        "code": "EE",
        "name": "Electrical Engineering",
        "description": "Engineering department",
        "is_active": "on",
    }
    data.update(kwargs)
    return data


def program_payload(department_id, **kwargs):
    data = {
        "department": department_id,
        "code": "BSEE",
        "name": "BS Electrical Engineering",
        "duration_semesters": 8,
        "description": "Four year program",
        "is_active": "on",
    }
    data.update(kwargs)
    return data


@override_settings(
    PASSWORD_HASHERS=[
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]
)
class DepartmentTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):

        cls.admin = User.objects.create_superuser(
            username="academic_admin",
            email="admin@example.com",
            password="StrongPassword123!",
        )

        cls.teacher = User.objects.create_user(
            username="teacher",
            password="StrongPassword123!",
            is_staff=True,
        )

        UserProfile.objects.create(
            user=cls.teacher,
            role=UserProfile.Role.TEACHER,
        )

        cls.student = User.objects.create_user(
            username="student",
            password="StrongPassword123!",
        )

        UserProfile.objects.create(
            user=cls.student,
            role=UserProfile.Role.STUDENT,
        )

        cls.staff_admin = User.objects.create_user(
            username="staff_admin",
            password="StrongPassword123!",
            is_staff=True,
        )

        UserProfile.objects.create(
            user=cls.staff_admin,
            role=UserProfile.Role.ADMIN,
        )

        cls.nonstaff_admin = User.objects.create_user(
            username="nonstaff_admin",
            password="StrongPassword123!",
        )

        UserProfile.objects.create(
            user=cls.nonstaff_admin,
            role=UserProfile.Role.ADMIN,
        )

        cls.cs = Department.objects.create(
            code="CS",
            name="Computer Science",
            description="Computing department",
        )

        cls.se = Department.objects.create(
            code="SE",
            name="Software Engineering",
        )

        cls.bscs = Program.objects.create(
            department=cls.cs,
            code="BSCS",
            name="BS Computer Science",
            duration_semesters=8,
        )

        cls.bsse = Program.objects.create(
            department=cls.se,
            code="BSSE",
            name="BS Software Engineering",
            duration_semesters=8,
        )

    def login(self, user=None):
        self.client.force_login(
            user or self.admin
        )

    def dept_url(self, name, pk=None):
        if pk is None:
            return reverse(
                f"departments:{name}"
            )
        return reverse(
            f"departments:{name}",
            args=[pk],
        )

    def program_url(self, name, pk=None):
        return self.dept_url(name, pk)


# =====================================================
# AUTHORIZATION
# =====================================================

class DepartmentPermissionTests(DepartmentTestBase):

    def test_superuser_is_admin(self):
        self.assertTrue(
            is_academic_admin(self.admin)
        )

    def test_staff_admin_profile_authorized(self):
        self.assertTrue(
            is_academic_admin(self.staff_admin)
        )

    def test_teacher_not_authorized(self):
        self.assertFalse(
            is_academic_admin(self.teacher)
        )

    def test_student_not_authorized(self):
        self.assertFalse(
            is_academic_admin(self.student)
        )

    def test_nonstaff_admin_profile_denied(self):
        self.assertFalse(
            is_academic_admin(self.nonstaff_admin)
        )

    def test_anonymous_redirected(self):
        response = self.client.get(
            self.dept_url("department_list")
        )
        self.assertEqual(
            response.status_code,
            302,
        )

    def test_teacher_cannot_view_departments(self):
        self.login(self.teacher)

        response = self.client.get(
            self.dept_url("department_list")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_student_cannot_view_programs(self):
        self.login(self.student)

        response = self.client.get(
            self.program_url("program_list")
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_teacher_cannot_create_department(self):
        self.login(self.teacher)

        response = self.client.post(
            self.dept_url("department_create"),
            department_payload(),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertFalse(
            Department.objects.filter(
                code="EE"
            ).exists()
        )

    def test_student_cannot_create_program(self):
        self.login(self.student)

        response = self.client.post(
            self.program_url("program_create"),
            program_payload(self.cs.pk),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_teacher_cannot_delete_department(self):
        self.login(self.teacher)

        response = self.client.post(
            self.dept_url(
                "department_delete",
                self.cs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertTrue(
            Department.objects.filter(
                pk=self.cs.pk
            ).exists()
        )

    def test_student_cannot_toggle_program(self):
        self.login(self.student)

        response = self.client.post(
            self.program_url(
                "program_toggle",
                self.bscs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_staff_admin_can_view_departments(self):
        self.login(self.staff_admin)

        response = self.client.get(
            self.dept_url("department_list")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_nonstaff_admin_cannot_post(self):
        self.login(self.nonstaff_admin)

        response = self.client.post(
            self.dept_url("department_create"),
            department_payload(),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_inactive_admin_denied(self):
        self.staff_admin.is_active = False
        self.staff_admin.save()

        self.assertFalse(
            is_academic_admin(self.staff_admin)
        )


# =====================================================
# DEPARTMENT CRUD
# =====================================================

class DepartmentCRUDTests(DepartmentTestBase):

    def setUp(self):
        self.login()

    def test_department_list_loads(self):
        response = self.client.get(
            self.dept_url("department_list")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_department_detail_loads(self):
        response = self.client.get(
            self.dept_url(
                "department_detail",
                self.cs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_create_form_loads(self):
        response = self.client.get(
            self.dept_url("department_create")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_create_department(self):
        response = self.client.post(
            self.dept_url("department_create"),
            department_payload(),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            Department.objects.filter(
                code="EE"
            ).exists()
        )

    def test_code_normalized_to_uppercase(self):
        self.client.post(
            self.dept_url("department_create"),
            department_payload(code="  ee  "),
        )

        self.assertTrue(
            Department.objects.filter(
                code="EE"
            ).exists()
        )

    def test_duplicate_code_rejected(self):
        response = self.client.post(
            self.dept_url("department_create"),
            department_payload(code="cs"),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            Department.objects.filter(
                code="CS"
            ).count(),
            1,
        )

    def test_empty_name_rejected(self):
        response = self.client.post(
            self.dept_url("department_create"),
            department_payload(name=""),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "name",
            response.context["form"].errors,
        )

    def test_invalid_code_rejected(self):
        response = self.client.post(
            self.dept_url("department_create"),
            department_payload(code="CS Faculty!"),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "code",
            response.context["form"].errors,
        )

    def test_edit_department(self):
        response = self.client.post(
            self.dept_url(
                "department_edit",
                self.cs.pk,
            ),
            department_payload(
                code="CS",
                name="Computer Sciences",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.cs.refresh_from_db()

        self.assertEqual(
            self.cs.name,
            "Computer Sciences",
        )

    def test_archive_with_active_programs_blocked(self):
        response = self.client.post(
            self.dept_url(
                "department_toggle",
                self.cs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.cs.refresh_from_db()

        self.assertTrue(
            self.cs.is_active
        )

    def test_archive_after_archiving_programs(self):
        self.bscs.is_active = False
        self.bscs.save()

        self.client.post(
            self.dept_url(
                "department_toggle",
                self.cs.pk,
            )
        )

        self.cs.refresh_from_db()

        self.assertFalse(
            self.cs.is_active
        )

    def test_restore_department(self):
        self.bscs.is_active = False
        self.bscs.save()

        self.cs.is_active = False
        self.cs.save()

        response = self.client.post(
            self.dept_url(
                "department_toggle",
                self.cs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.cs.refresh_from_db()

        self.assertTrue(
            self.cs.is_active
        )

    def test_delete_without_programs(self):
        department = Department.objects.create(
            code="MATH",
            name="Mathematics",
        )

        pk = department.pk

        response = self.client.post(
            self.dept_url(
                "department_delete",
                pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            Department.objects.filter(
                pk=pk
            ).exists()
        )

    def test_delete_with_programs_blocked(self):
        response = self.client.post(
            self.dept_url(
                "department_delete",
                self.cs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            Department.objects.filter(
                pk=self.cs.pk
            ).exists()
        )

    def test_get_does_not_delete_department(self):
        response = self.client.get(
            self.dept_url(
                "department_delete",
                self.cs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            Department.objects.filter(
                pk=self.cs.pk
            ).exists()
        )

    def test_toggle_get_not_allowed(self):
        response = self.client.get(
            self.dept_url(
                "department_toggle",
                self.cs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_missing_department_404(self):
        response = self.client.get(
            self.dept_url(
                "department_detail",
                999999,
            )
        )

        self.assertEqual(
            response.status_code,
            404,
        )


# =====================================================
# PROGRAM CRUD
# =====================================================

class ProgramCRUDTests(DepartmentTestBase):

    def setUp(self):
        self.login()

    def test_program_list_loads(self):
        response = self.client.get(
            self.program_url("program_list")
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_program_detail_loads(self):
        response = self.client.get(
            self.program_url(
                "program_detail",
                self.bscs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_create_program(self):
        response = self.client.post(
            self.program_url("program_create"),
            program_payload(self.cs.pk),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertTrue(
            Program.objects.filter(
                department=self.cs,
                code="BSEE",
            ).exists()
        )

    def test_duplicate_program_same_department(self):
        response = self.client.post(
            self.program_url("program_create"),
            program_payload(
                self.cs.pk,
                code="bscs",
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            Program.objects.filter(
                department=self.cs,
                code="BSCS",
            ).count(),
            1,
        )

    def test_same_code_in_other_department_allowed(self):
        response = self.client.post(
            self.program_url("program_create"),
            program_payload(
                self.se.pk,
                code="BSCS",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

    def test_invalid_semester_count_zero(self):
        response = self.client.post(
            self.program_url("program_create"),
            program_payload(
                self.cs.pk,
                duration_semesters=0,
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "duration_semesters",
            response.context["form"].errors,
        )

    def test_invalid_semester_count_above_twelve(self):
        response = self.client.post(
            self.program_url("program_create"),
            program_payload(
                self.cs.pk,
                duration_semesters=13,
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_missing_department_rejected(self):
        response = self.client.post(
            self.program_url("program_create"),
            program_payload(
                "",
            ),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertIn(
            "department",
            response.context["form"].errors,
        )

    def test_fake_department_id_rejected(self):
        response = self.client.post(
            self.program_url("program_create"),
            program_payload(999999),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_program_edit(self):
        response = self.client.post(
            self.program_url(
                "program_edit",
                self.bscs.pk,
            ),
            program_payload(
                self.cs.pk,
                code="BSCS",
                name="Bachelor of Computer Science",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.bscs.refresh_from_db()

        self.assertEqual(
            self.bscs.name,
            "Bachelor of Computer Science",
        )

    def test_archive_program(self):
        response = self.client.post(
            self.program_url(
                "program_toggle",
                self.bscs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.bscs.refresh_from_db()

        self.assertFalse(
            self.bscs.is_active
        )

    def test_restore_program(self):
        self.bscs.is_active = False
        self.bscs.save()

        self.client.post(
            self.program_url(
                "program_toggle",
                self.bscs.pk,
            )
        )

        self.bscs.refresh_from_db()

        self.assertTrue(
            self.bscs.is_active
        )

    def test_restore_program_in_inactive_department_blocked(self):
        self.bscs.is_active = False
        self.bscs.save()

        self.cs.is_active = False
        self.cs.save()

        response = self.client.post(
            self.program_url(
                "program_toggle",
                self.bscs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.bscs.refresh_from_db()

        self.assertFalse(
            self.bscs.is_active
        )

    def test_create_in_archived_department_rejected(self):
        self.bscs.is_active = False
        self.bscs.save()

        self.cs.is_active = False
        self.cs.save()

        response = self.client.post(
            self.program_url("program_create"),
            program_payload(self.cs.pk),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertFalse(
            Program.objects.filter(
                department=self.cs,
                code="BSEE",
            ).exists()
        )

    def test_delete_program(self):
        pk = self.bscs.pk

        response = self.client.post(
            self.program_url(
                "program_delete",
                pk,
            )
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        self.assertFalse(
            Program.objects.filter(
                pk=pk
            ).exists()
        )

    def test_program_toggle_get_not_allowed(self):
        response = self.client.get(
            self.program_url(
                "program_toggle",
                self.bscs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            405,
        )

    def test_program_delete_get_safe(self):
        response = self.client.get(
            self.program_url(
                "program_delete",
                self.bscs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            Program.objects.filter(
                pk=self.bscs.pk
            ).exists()
        )


# =====================================================
# SEARCH AND FILTERING
# =====================================================

class DepartmentFilteringTests(DepartmentTestBase):

    def setUp(self):
        self.login()

    def test_department_search(self):
        response = self.client.get(
            self.dept_url("department_list"),
            {"q": "Computer"},
        )

        self.assertContains(
            response,
            "Computer Science",
        )

        self.assertNotContains(
            response,
            "Software Engineering",
        )

    def test_department_status_filter(self):
        self.se.is_active = False
        self.se.save()

        response = self.client.get(
            self.dept_url("department_list"),
            {"status": "inactive"},
        )

        self.assertEqual(
            list(response.context["page_obj"]),
            [self.se],
        )

    def test_program_department_filter(self):
        response = self.client.get(
            self.program_url("program_list"),
            {"department": str(self.cs.pk)},
        )

        programs = list(
            response.context["page_obj"]
        )

        self.assertEqual(
            programs,
            [self.bscs],
        )

    def test_program_search(self):
        response = self.client.get(
            self.program_url("program_list"),
            {"q": "BSCS"},
        )

        programs = list(
            response.context["page_obj"]
        )

        self.assertEqual(
            programs,
            [self.bscs],
        )

    def test_invalid_department_filter_safe(self):
        response = self.client.get(
            self.program_url("program_list"),
            {"department": "invalid"},
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            len(response.context["page_obj"]),
            0,
        )

    def test_invalid_page_safe(self):
        response = self.client.get(
            self.dept_url("department_list"),
            {"page": "not-a-number"},
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_pagination(self):
        for i in range(15):
            Department.objects.create(
                code=f"D{i}",
                name=f"Department {i}",
            )

        response = self.client.get(
            self.dept_url("department_list")
        )

        self.assertEqual(
            len(response.context["page_obj"]),
            10,
        )

        self.assertGreater(
            response.context[
                "page_obj"
            ].paginator.num_pages,
            1,
        )


# =====================================================
# MODEL / DATABASE INTEGRITY
# =====================================================

class DepartmentModelTests(DepartmentTestBase):

    def test_department_string(self):
        self.assertEqual(
            str(self.cs),
            "CS - Computer Science",
        )

    def test_program_string(self):
        self.assertIn(
            "BSCS",
            str(self.bscs),
        )

    def test_department_code_normalized(self):
        department = Department.objects.create(
            code=" math ",
            name="Mathematics",
        )

        self.assertEqual(
            department.code,
            "MATH",
        )

    def test_program_code_normalized(self):
        program = Program.objects.create(
            department=self.cs,
            code=" bscy ",
            name="Cybersecurity",
        )

        self.assertEqual(
            program.code,
            "BSCY",
        )

    def test_database_duplicate_department_blocked(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Department.objects.create(
                    code="cs",
                    name="Duplicate",
                )

    def test_database_duplicate_program_blocked(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Program.objects.create(
                    department=self.cs,
                    code="bscs",
                    name="Duplicate Program",
                )

    def test_department_program_relation(self):
        self.assertIn(
            self.bscs,
            self.cs.programs.all(),
        )

    def test_program_department_relation(self):
        self.assertEqual(
            self.bscs.department,
            self.cs,
        )


# =====================================================
# CSRF / WEB SECURITY
# =====================================================

class DepartmentSecurityTests(DepartmentTestBase):

    def setUp(self):
        self.login()

    def test_department_creation_requires_csrf(self):
        secure_client = Client(
            enforce_csrf_checks=True
        )

        secure_client.force_login(self.admin)

        response = secure_client.post(
            self.dept_url("department_create"),
            department_payload(),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_program_creation_requires_csrf(self):
        secure_client = Client(
            enforce_csrf_checks=True
        )

        secure_client.force_login(self.admin)

        response = secure_client.post(
            self.program_url("program_create"),
            program_payload(self.cs.pk),
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_department_delete_requires_csrf(self):
        secure_client = Client(
            enforce_csrf_checks=True
        )

        secure_client.force_login(self.admin)

        response = secure_client.post(
            self.dept_url(
                "department_delete",
                self.cs.pk,
            )
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_get_does_not_modify_status(self):
        original = self.cs.is_active

        self.client.get(
            self.dept_url(
                "department_toggle",
                self.cs.pk,
            )
        )

        self.cs.refresh_from_db()

        self.assertEqual(
            self.cs.is_active,
            original,
        )

    def test_search_does_not_execute_sql_payload(self):
        response = self.client.get(
            self.dept_url("department_list"),
            {
                "q": "' OR 1=1 --",
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertEqual(
            Department.objects.count(),
            2,
        )

    def test_html_is_escaped(self):
        Department.objects.create(
            code="XSS",
            name="<script>alert(1)</script>",
        )

        response = self.client.get(
            self.dept_url("department_list")
        )

        self.assertNotContains(
            response,
            "<script>alert(1)</script>",
        )


# =====================================================
# COMPLETE END-TO-END ADMIN WORKFLOW
# =====================================================

class DepartmentEndToEndTests(DepartmentTestBase):

    def test_department_program_lifecycle(self):
        self.login()

        # 1. Create department.
        response = self.client.post(
            self.dept_url("department_create"),
            department_payload(
                code="IT",
                name="Information Technology",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        department = Department.objects.get(
            code="IT"
        )

        # 2. Create program under department.
        response = self.client.post(
            self.program_url("program_create"),
            program_payload(
                department.pk,
                code="BSIT",
                name="BS Information Technology",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        program = Program.objects.get(
            department=department,
            code="BSIT",
        )

        # 3. Edit program.
        response = self.client.post(
            self.program_url(
                "program_edit",
                program.pk,
            ),
            program_payload(
                department.pk,
                code="BSIT",
                name="Updated BS IT",
            ),
        )

        self.assertEqual(
            response.status_code,
            302,
        )

        program.refresh_from_db()

        self.assertEqual(
            program.name,
            "Updated BS IT",
        )

        # 4. Archive program.
        self.client.post(
            self.program_url(
                "program_toggle",
                program.pk,
            )
        )

        program.refresh_from_db()

        self.assertFalse(
            program.is_active
        )

        # 5. Archive department.
        self.client.post(
            self.dept_url(
                "department_toggle",
                department.pk,
            )
        )

        department.refresh_from_db()

        self.assertFalse(
            department.is_active
        )

        # 6. Restore department.
        self.client.post(
            self.dept_url(
                "department_toggle",
                department.pk,
            )
        )

        department.refresh_from_db()

        self.assertTrue(
            department.is_active
        )

        # 7. Restore program.
        self.client.post(
            self.program_url(
                "program_toggle",
                program.pk,
            )
        )

        program.refresh_from_db()

        self.assertTrue(
            program.is_active
        )

        # 8. Delete program.
        program_pk = program.pk

        self.client.post(
            self.program_url(
                "program_delete",
                program_pk,
            )
        )

        self.assertFalse(
            Program.objects.filter(
                pk=program_pk
            ).exists()
        )

        # 9. Delete department.
        department_pk = department.pk

        self.client.post(
            self.dept_url(
                "department_delete",
                department_pk,
            )
        )

        self.assertFalse(
            Department.objects.filter(
                pk=department_pk
            ).exists()
        )
