"""AssignHub course/section assignment-workspace redesign installer.

USAGE (PowerShell):
    cd D:\\assignhub-portal
    python .\\AssignHub_Assignments_Redesign_Package\\apply_assignment_redesign.py --check
    python .\\AssignHub_Assignments_Redesign_Package\\apply_assignment_redesign.py

Changes only the GET assignment list view, its template, and adds new
view/template CSS and focused regression tests. No migrations or database writes.
Backups live OUTSIDE the repository, alongside its project directory.
"""

import argparse
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path


EXPECTED_GITHUB_COMMIT = "27333e16fb25d5b5c66fac76a18b583e3e11e5a1"
EXPECTED_BLOBS = {
    "assignments/views.py": "315f7df2f848ea457c790d9b0efb4bd3222d370c",
    "templates/assignments/assignment_list.html": "ffaad069c213508590f642ece590182c5258fc6b",
}

PAYLOAD_FILES = [
    "assignments/assignment_directory.py",
    "assignments/test_assignment_directory.py",
    "templates/assignments/assignment_list.html",
    "static/css/assignment_directory.css",
]


class PreflightError(Exception):
    pass


def git_blob_sha(contents):
    # GitHub stores normalized LF text; normalize Windows CRLF to compare fairly.
    raw = contents.replace(b"\r\n", b"\n")
    prefix = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(prefix + raw).hexdigest()


def replace_list_view(source):
    """Replace only assignment_list() while preserving all other assignment views."""
    sentinel = "def assignment_list(request):"
    if source.count(sentinel) != 1:
        raise PreflightError("Expected exactly one assignment_list(request) in views.py")
    start = source.index(sentinel)
    next_view_marker = "\n\n@login_required\n@require_http_methods([\"GET\"])\ndef assignment_detail(request, pk):"
    if source.count(next_view_marker) != 1:
        raise PreflightError("Could not locate the exact assignment_detail boundary")
    end = source.index(next_view_marker, start)
    previous_function = source[start:end]
    if "from .assignment_directory import assignment_directory" in previous_function:
        return source  # Already installed.
    if "assignments/assignment_list.html" not in previous_function:
        raise PreflightError("assignment_list body differs from the committed version")
    replacement = (
        "def assignment_list(request):\n"
        "    # Course/section-aware read-only directory.\n"
        "    # The original URL, login and GET decorators are preserved.\n"
        "    from .assignment_directory import assignment_directory\n"
        "    return assignment_directory(request)\n"
    )
    return source[:start] + replacement + source[end:]


def project_root():
    root = Path.cwd().resolve()
    if not (root / "manage.py").is_file() or not (root / "assignments" / "views.py").is_file():
        raise PreflightError(
            "Run this script from the Django project root (D:\\assignhub-portal)."
        )
    return root


def prepare(root, package, allow_modified):
    current_view_path = root / "assignments/views.py"
    current_template_path = root / "templates/assignments/assignment_list.html"
    if not current_template_path.is_file():
        raise PreflightError("Existing assignment_list.html is missing")

    old_view_bytes = current_view_path.read_bytes()
    old_template_bytes = current_template_path.read_bytes()
    old_view = old_view_bytes.decode("utf-8-sig").replace("\r\n", "\n")
    old_template = old_template_bytes.decode("utf-8-sig").replace("\r\n", "\n")

    is_installed = "from .assignment_directory import assignment_directory" in old_view
    if not is_installed and not allow_modified:
        for name, contents in (
            ("assignments/views.py", old_view_bytes),
            ("templates/assignments/assignment_list.html", old_template_bytes),
        ):
            got = git_blob_sha(contents)
            if got != EXPECTED_BLOBS[name]:
                raise PreflightError(
                    f"{name} differs from reviewed GitHub commit {EXPECTED_GITHUB_COMMIT[:7]} "
                    f"(expected blob {EXPECTED_BLOBS[name][:10]}, got {got[:10]}). "
                    "Commit/review your local changes first, or use --allow-modified "
                    "after inspecting them. No files were changed."
                )

    if not is_installed and not allow_modified:
        if "Submission Progress" not in old_template or "Edit" not in old_template:
            raise PreflightError("Existing assignment template does not look like the reviewed version")

    file_changes = {}
    new_view = replace_list_view(old_view)
    if new_view != old_view:
        file_changes["assignments/views.py"] = new_view.encode("utf-8")

    for path in PAYLOAD_FILES:
        payload_path = package / "payload" / path
        if not payload_path.is_file():
            raise PreflightError("Missing installer payload: " + str(payload_path))
        destination = root / path
        desired = payload_path.read_bytes()
        if not destination.exists():
            file_changes[path] = desired
            continue
        existing = destination.read_bytes()
        if existing.replace(b"\r\n", b"\n") == desired.replace(b"\r\n", b"\n"):
            continue
        if path == "templates/assignments/assignment_list.html" and not is_installed:
            file_changes[path] = desired
            continue
        if allow_modified:
            file_changes[path] = desired
        else:
            raise PreflightError(
                f"{path} exists with different content. No files were changed. "
                "Use --allow-modified only after reviewing the existing file."
            )

    # Conservative validation before a single file is written.
    for name, contents in file_changes.items():
        if name.endswith(".py"):
            try:
                compile(contents.decode("utf-8"), name, "exec")
            except SyntaxError as exc:
                raise PreflightError(f"Payload has invalid Python syntax: {name}: {exc}")
    return file_changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Preflight only, do not change files")
    parser.add_argument("--allow-modified", action="store_true", help="Permit replacing reviewed-but-locally-modified files")
    args = parser.parse_args()

    try:
        root = project_root()
        package = Path(__file__).resolve().parent
        changes = prepare(root, package, args.allow_modified)
        print("REVIEWED GITHUB COMMIT:", EXPECTED_GITHUB_COMMIT)
        print("PROJECT:", root)
        if not changes:
            print("All redesign files already installed. Nothing to do.")
            return 0
        print("CHANGES:")
        for name in changes:
            print("  ", "MODIFY" if (root / name).exists() else "CREATE", name)
        if args.check:
            print("Preflight passed. Run without --check to install.")
            return 0

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_root = root.parent / "AssignHub_AssignmentRedesign_Backups" / timestamp
        backed_up = []
        for name in changes:
            source = root / name
            if source.exists():
                destination = backup_root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                backed_up.append(name)

        created = []
        try:
            for name, desired in changes.items():
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    created.append(name)
                tmp = destination.with_name(destination.name + ".new-tmp")
                tmp.write_bytes(desired)
                tmp.replace(destination)
                print("INSTALLED:", name)
        except Exception:
            print("Installation failed. Restoring prior files...")
            for name in backed_up:
                source = backup_root / name
                destination = root / name
                shutil.copy2(source, destination)
            for name in created:
                (root / name).unlink(missing_ok=True)
            raise

        print("\nSUCCESS: Assignment Workspace redesign installed.")
        print("Backups:", backup_root)
        print("\nNext commands:")
        print("  python manage.py check")
        print("  python manage.py test assignments.test_assignment_directory assignments.tests.AssignmentListTests")
        print("  python manage.py test assignments.test_auto_plagiarism")
        print("  python manage.py runserver")
        print("\nNo migrations required; original assignment routes are preserved.")
        return 0
    except (PreflightError, UnicodeError) as exc:
        print("PRECHECK FAILED:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
