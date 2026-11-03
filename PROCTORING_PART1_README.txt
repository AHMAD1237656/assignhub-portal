AssignHub — Exam Monitoring Part 1 (not yet AI detection)
=======================================================
Verified target branch: feature/quiz-engine, GitHub head dfd7a0a (2026-11-02).

WHAT IT DOES:
- New independent Django app: quiz_proctoring.
- Teacher/admin navigation: My Classes -> Courses -> Quizzes -> Student Attempts -> Event Review.
- Teacher enables monitoring on QUIZ DRAFT only. Existing quizzes default unmonitored.
- Student preflight: camera permission preview + clear consent BEFORE the exam timer starts.
- Proctored attempt uses quiz engine's existing server-authoritative timer, autosave and grading.
- Live camera preview stays in browser; video/images are NOT sent to Django.
- Browser-reported tab hidden, focus loss, fullscreen exit and camera interruption events.
- Authenticated server-side events, rate limit per kind, timestamps, role-based teacher review.
- No facial recognition, mobile phone detection, AI inference, cheating scores or lockdown in Part 1.
- Browser-reported events and camera check claims can be spoofed: NOT proof of cheating.

INSTALL from Quiz branch working tree, after committing/backing up your changes:
  python apply_assignhub_proctoring_part1.py --check
  python apply_assignhub_proctoring_part1.py --apply
  python manage.py migrate quiz_proctoring
  python manage.py check
  python manage.py makemigrations --check --dry-run
  python manage.py test quiz_proctoring quizzes notifications
  python manage.py runserver

DO NOT run older Quiz installer scripts again. No existing data is deleted.
The installer refuses to run on 'main' and refuses to overwrite differently customized new files.
It automatically backs up the six touched integration files outside the project root.

BROWSER TEST FLOW:
1. Teacher: /proctoring/ -> class -> course -> quiz -> configure on DRAFT only.
2. Publish quiz from normal Quiz module. Student opens quiz and enters device check.
3. Student checks webcam and consents; only then a monitored attempt is created.
4. Quiz timer, autosave and submit remain controlled by the existing Quiz module.
5. Browser changes tab / exits fullscreen -> incidents logged (when configured).
6. Teacher opens monitoring -> student attempts -> timeline -> reviewed/dismissed.
7. Admin sees reports read-only; another teacher or another student cannot access.
8. Non-proctored quiz still starts using the original Quiz workflow.
9. Test camera denial, page refresh, expired timer and internet disconnection.
10. If deployed remotely, camera access requires HTTPS (localhost is supported).

Privacy: disclose monitoring; obtain consent; avoid storing webcam streams;
use 'python manage.py prune_proctor_events --days 30' under an approved retention policy.
