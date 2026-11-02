AssignHub FINAL MODULE: QUIZZES — CLASS-FIRST EDITION
======================================================
This edition REPLACES the previous flat Quiz Center design.
IMPORTANT: use apply_assignhub_quizzes_class_first.py, not the older quiz installer.

TEACHER NAVIGATION
  Sidebar: Quizzes -> My Classes (only assigned/teaching classes)
    -> Select Class (section + academic year + term)
    -> Select Course (only assigned course offerings in that class)
    -> Course Quizzes -> Create Quiz -> Add MCQs -> Publish -> Attempts

STUDENT NAVIGATION
  Quizzes -> My Enrolled Classes -> Select Class -> Select Course
    -> Published/Closed Quiz -> Start -> Autosave MCQs -> Submit -> Result

ADMIN
  Class -> Course -> Quiz: read-only overview and attempt results.

CLASS ORGANIZATION
  A class is identified by Section + Academic Year + Term. This prevents
  different semester sessions being merged into the same class.
  Teacher classes are loaded from existing CourseOffering.teacher allocations.
  Student classes are loaded from active CourseEnrollment records.
  Student never sees draft quizzes, other sections or unauthorized courses.
  Quiz create form is LOCKED to the chosen course offering on the server.
  No manual choose-course dropdown can accidentally target a different class.

FEATURES UNCHANGED FROM V1
  Timed 4-option single-answer MCQs, one attempt, server-owned timer, autosave,
  automatic grading, result release setting, teacher reports/roster, permission
  isolation, no third-party AI, no Analytics/Reports module.

INSTALL
  Place apply_assignhub_quizzes_class_first.py beside manage.py and run:
    python apply_assignhub_quizzes_class_first.py --check
    python apply_assignhub_quizzes_class_first.py --apply
    python manage.py makemigrations quizzes
    python manage.py migrate
    python manage.py check
    python manage.py test quizzes
    python manage.py runserver

  Open http://127.0.0.1:8000/quizzes/

  If you installed the old quiz installer already, the new script can update
  exact, unmodified V1 files (with backups) without data migration changes.
  Customized quiz files are NOT overwritten: the installer aborts safely.
  Only three existing project files may be patched: config/settings.py,
  config/urls.py and templates/base.html. Other module logic stays untouched.

DEVELOPMENT TEST CHECKLIST
  1. Teacher Quiz > My Classes: no unrelated section/course.
  2. Select class > only assigned courses for that year and term.
  3. Select course > only that course's quizzes; filter by status.
  4. Create quiz > chosen course shown as read-only context; cannot forge.
  5. Add MCQs > publish > teacher/student scope check.
  6. Student Quiz > enrolled classes > courses > published quiz.
  7. Timed start > refresh does not reset timer.
  8. Autosave selection > refresh restores answers > submit > mark.
  9. Expired quiz auto-finalizes and cannot restart.
 10. Cross-class and direct URL access must be denied.

OPTIONAL EXPIRY WORKER
  python manage.py finalize_quiz_attempts
  powershell -ExecutionPolicy Bypass -File scripts\run_quiz_expiry_loop.ps1

No changes to existing Assignments, Notifications, Plagiarism or Typewriter
business logic. Automatic tests need to run on your own Django environment.

EXAM SECURITY NOTE
- Even when show_results is enabled, answer keys and marks stay hidden until the quiz
  is CLOSED or closes_at passes, to avoid leaking answers to other candidates.
- This is Quiz Engine PART 1 ONLY. No camera, AI, or browser proctoring is installed.
- This is a development feature, not a certified secure examination platform.
