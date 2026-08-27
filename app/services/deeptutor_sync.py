# OurSchool - Homeschool Management System
# Copyright (C) 2025 Dustan Ashley
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Syncs DeepTutor mastery-path progress into real graded StudentAssignment
rows, so AI-tutor quizzing/grading shows up in the ourschool gradebook
alongside parent-graded work."""

from datetime import date

from sqlalchemy.orm import Session

from app.enums import AssignmentStatus
from app.models.assignment import AssignmentTemplate, StudentAssignment
from app.models.assignment_type import AssignmentTypeConfig
from app.services.deeptutor_client import get_mastery_map, mint_student_token
from app.utils.grading import calculate_letter_grade

TUTOR_QUIZ_TYPE_KEY = "tutor_quiz"


def _ensure_tutor_quiz_type(db: Session) -> None:
    if db.query(AssignmentTypeConfig).filter_by(key=TUTOR_QUIZ_TYPE_KEY).first():
        return
    db.add(
        AssignmentTypeConfig(
            key=TUTOR_QUIZ_TYPE_KEY,
            name="AI Tutor",
            color="#0EA5E9",
            icon="bot",
            weight=0.0,
            is_active=True,
        )
    )
    db.commit()


def _ensure_module_template(
    db: Session, subject_id: int, book_title: str, module_name: str
) -> AssignmentTemplate:
    # One template per module/chapter — this doubles as the correlation key
    # for upserting a student's StudentAssignment for that module, so no
    # hidden tag field is needed (custom_instructions/submission_artifacts
    # are both rendered to the student, so can't be used for that).
    name = f"AI Tutor — {book_title}: {module_name}"
    existing = (
        db.query(AssignmentTemplate)
        .filter_by(subject_id=subject_id, assignment_type=TUTOR_QUIZ_TYPE_KEY, name=name)
        .first()
    )
    if existing:
        return existing
    template = AssignmentTemplate(
        name=name,
        description=f"AI tutor mastery tracking for {book_title} — {module_name}.",
        instructions="Auto-generated from DeepTutor mastery-path quizzing and grading.",
        assignment_type=TUTOR_QUIZ_TYPE_KEY,
        subject_id=subject_id,
        max_points=100,
    )
    db.add(template)
    db.flush()
    return template


async def sync_mastery_progress(
    db: Session,
    student_id: int,
    book_id: str,
    subject_id: int,
    admin_id: int,
    book_title: str | None = None,
) -> dict:
    """Pull DeepTutor's mastery map for a student and upsert one graded
    StudentAssignment per module (chapter), reflecting current mastery."""
    jwt, _ = await mint_student_token(student_id)
    data = await get_mastery_map(jwt, book_id)
    book_title = book_title or data.get("book_id", book_id)
    modules = data.get("map", {}).get("modules", [])

    _ensure_tutor_quiz_type(db)

    updated = 0
    for module in modules:
        kps = module.get("knowledge_points", [])
        if not kps:
            continue
        template = _ensure_module_template(db, subject_id, book_title, module.get("name", "Module"))

        assignment = (
            db.query(StudentAssignment)
            .filter_by(template_id=template.id, student_id=student_id)
            .first()
        )
        if not assignment:
            assignment = StudentAssignment(
                template_id=template.id,
                student_id=student_id,
                assigned_date=date.today(),
                due_date=None,
                assigned_by=admin_id,
                status=AssignmentStatus.NOT_STARTED,
            )
            db.add(assignment)

        # A module is only "attempted" once at least one knowledge point has
        # moved off its untouched "new" state — an untouched module is real
        # assigned work waiting to be done with the tutor, not a 0/F failure.
        attempted_kps = [kp for kp in kps if kp.get("status") != "new" or kp.get("mastery", 0) > 0]
        if not attempted_kps:
            assignment.teacher_feedback = None
            assignment.is_graded = False
            assignment.points_earned = None
            assignment.percentage_grade = None
            assignment.letter_grade = None
            assignment.graded_date = None
            assignment.graded_by = None
            assignment.started_date = None
            assignment.submitted_date = None
            assignment.completed_date = None
            assignment.status = AssignmentStatus.NOT_STARTED
            updated += 1
            continue

        avg_mastery = sum(kp.get("mastery", 0.0) for kp in kps) / len(kps)
        pct = round(avg_mastery * 100, 1)
        points_earned = round(template.max_points * avg_mastery, 1)
        statuses = ", ".join(f"{kp['name']} ({kp['status']})" for kp in kps)

        assignment.points_earned = points_earned
        assignment.percentage_grade = pct
        assignment.letter_grade = calculate_letter_grade(pct)
        assignment.is_graded = True
        assignment.graded_date = date.today()
        assignment.graded_by = admin_id
        assignment.teacher_feedback = (
            f"AI Tutor — {module.get('name')}: {module.get('mastered', 0)}/"
            f"{module.get('total', len(kps))} knowledge points mastered. {statuses}"
        )
        assignment.backfill_lifecycle_dates_for_grading()
        assignment.update_status()
        updated += 1

    db.commit()
    return {"modules_synced": updated}
