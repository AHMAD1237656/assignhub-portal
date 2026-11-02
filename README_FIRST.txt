AssignHub Notification Center — ADDITIVE MODULE
==============================================
Based on verified GitHub commit 099a815 (2 Nov 2026).

WHAT IS INSTALLED
- notifications/ Django app, models + migration, signals, views, tests, commands
- templates/notifications/ and static/css/notifications.css + static/js/notifications.js
- scripts/run_notification_reminders.ps1 (hourly local development reminders)
- FOUR small patches only: config/settings.py, config/urls.py,
  templates/base.html, assignments/auto_plagiarism.py

NOT CHANGED
- Existing assignments models, submissions, grade editing, activation flow,
  class allocations, timed-writing timer, plagiarism scoring or OCR pipeline
- Existing database rows; no deletion or data recreation

INSTALLATION
1. Put apply_assignhub_notifications.py in D:\assignhub-portal.
2. Run: python apply_assignhub_notifications.py --check
3. Run: python apply_assignhub_notifications.py
4. Run: python manage.py migrate notifications
5. Run: python manage.py check
6. Run: python manage.py makemigrations --check --dry-run notifications
7. Run: python manage.py test notifications
8. Run: python manage.py test assignments.test_auto_plagiarism accounts
9. Restart Django server and plagiarism worker.

In development, run reminders from another PowerShell terminal:
   powershell -ExecutionPolicy Bypass -File scripts\run_notification_reminders.ps1
Or manually:
   python manage.py send_deadline_notifications
The command can be scheduled hourly in production.

TEST EVENTS
1. Teacher publishes assignment -> active enrolled students receive an alert.
2. Student final submits -> owning teacher receives an alert.
3. Teacher grades -> that student receives result alert.
4. OCR worker saves NEEDS_REVIEW -> teacher receives integrity alert.
5. Student activates -> active administrator accounts receive activation alert.
6. Reminder command -> active enrolled students with pending work and deadline
   within 24 hours get one reminder per assignment.
7. Teacher closes assignment -> active enrolled students notified.
8. Notification bell works on teacher, student and admin pages; Open / Read
   routes use POST + CSRF and enforce recipient ownership.

NOTIFICATION CHANNELS
This is a complete in-app notification center. It does not send SMS, browser
push, desktop alerts or additional emails. Existing activation email is unchanged.
30-second polling updates the unread badge; full dropdown contents update on
page refresh. The reminder script only runs when the terminal/process is active.

SECURITY
No external redirect URLs; no plagiarism analysis disclosed to students;
no activation tokens in alerts; all reads and actions user-scoped.

BACKUPS
A dated snapshot of the four modified existing files is saved OUTSIDE the
project at ..\AssignHub_Notification_Backups\<timestamp>. Running the installer
again is safe; it detects already-installed files.
