ASSIGNHUB — ASSIGNMENT WORKSPACE REDESIGN
=========================================
Based on verified GitHub HEAD:
27333e16fb25d5b5c66fac76a18b583e3e11e5a1
Repository: AHMAD1237656/assignhub-portal

WHAT CHANGES
------------
1. Replaces the old assignments listing template with a navy-blue,
   responsive Assignment Workspace dashboard.
2. Adds role-scoped course tiles for rapid navigation.
3. Adds GET filters: search, course, section, semester, academic year, term.
4. Adds status tabs: All, Published, Draft, Closed, Due Soon, Overdue.
   Students only see statuses applicable to their authorized assignments.
5. Adds sorting and pagination (12 assignments per page).
6. Adds distinct count annotations for active enrollments, final submissions,
   awaiting grades, and needs-review plagiarism reports.
7. Hides the Edit action when editing is locked by a final submission or
   a started timed-writing attempt.
8. Preserves all existing URLs, permissions, submission, grading, roster,
   manual similarity and automatic plagiarism logic.
9. No model updates or migrations required.

FILES THE INSTALLER MODIFIES
----------------------------
MODIFY assignments/views.py  (assignment_list function ONLY)
MODIFY templates/assignments/assignment_list.html
ADD    assignments/assignment_directory.py
ADD    assignments/test_assignment_directory.py
ADD    static/css/assignment_directory.css

PRE-INSTALL
-----------
- Commit or back up pending changes in your project.
- Confirm Git HEAD is the reviewed commit:
  git log -1 --oneline
- Ensure you are in the Python virtual environment.

INSTALL (PowerShell)
--------------------
1. Extract this ZIP to the Django project directory:
   D:\assignhub-portal\AssignHub_Assignments_Redesign_Package\

2. Open PowerShell:
   cd D:\assignhub-portal

3. Check first (no modifications):
   python .\AssignHub_Assignments_Redesign_Package\apply_assignment_redesign.py --check

4. Apply:
   python .\AssignHub_Assignments_Redesign_Package\apply_assignment_redesign.py

5. Validate:
   python manage.py check
   python manage.py test assignments.test_assignment_directory assignments.tests.AssignmentListTests
   python manage.py test assignments.test_auto_plagiarism

6. Start the app:
   python manage.py runserver

7. In the browser (teacher login):
   http://127.0.0.1:8000/assignments/

8. Verify a course, section, status and search filter; then pagination.
   Click View Details / Submissions and confirm existing workflows remain.

NO migrate / makemigrations COMMANDS ARE NECESSARY.

BACKUP AND RESTORE
------------------
The installer creates backup copies OUTSIDE the repository:
D:\AssignHub_AssignmentRedesign_Backups\<timestamp>\...

To roll back:
- Copy the backed-up assignments/views.py and
  templates/assignments/assignment_list.html into the matching project paths.
- Delete ONLY the 3 files added by this installer:
  assignments/assignment_directory.py
  assignments/test_assignment_directory.py
  static/css/assignment_directory.css
- Then restart Django.

If there are uncommitted local modifications to the reviewed files,
preflight safely refuses to overwrite them. Use --allow-modified ONLY after
reviewing why your local files differ; backups are always created on install.

MANUAL TEST CASES
-----------------
Teacher 1: 10 courses, many sections -> use the Course tiles and filters.
Student: only enrolled, active, published assignments; no create/edit.
Admin: all assignments, view details and rosters but cannot edit as teacher.
Draft assignment: teacher edit allowed if no final submissions / timed attempts.
Submitted assignment: teacher Edit button hidden; grading remains available.
Plagiarism flags: card displays count of NEEDS_REVIEW reports, not verdict.
Multiple filters: course+section+year+term combinations must work.
Pagination: 12 cards per page, filters preserved when paging.

VERIFICATION LIMITATIONS
------------------------
Installer was tested with a synthetic local project for patch anchors,
syntax and idempotence. The user's Windows Django + SQLite runtime was not
accessible; Django tests must be executed locally before committing.

CLEAN UP BEFORE YOUR NEXT GIT COMMIT
------------------------------------
After installation succeeds and you have run the test suite, you may remove
D:\assignhub-portal\AssignHub_Assignments_Redesign_Package\ from project root.
The installed Django code will continue working because the installer copies
payload files into their actual project paths. Keep the separate backups
until you are satisfied with the redesign.
Then run: git status; git add assignments/views.py assignments/assignment_directory.py assignments/test_assignment_directory.py templates/assignments/assignment_list.html static/css/assignment_directory.css
