# OurSchool - Homeschool Management System
# Copyright (C) 2025 Dustan Ashley
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Proposal executors: apply an approved copilot proposal to the school.

Each executor mirrors the write path of the corresponding first-party router
(attendance, journal, assignments, grading, points) so approved proposals
behave exactly like the parent doing it by hand — including grade-history,
term-grade recalculation, and points sync. Only the parent's approval (the
consent gate in app/routers/copilot.py) can reach these.
"""

import logging
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.crud import points as points_crud
from app.crud.settings import get_grade_scale
from app.enums import UserRole
from app.models.assignment import AssignmentTemplate, StudentAssignment
from app.models.attendance import AttendanceRecord
from app.models.journal import JournalEntry
from app.models.term import Term
from app.models.user import User
from app.schemas.points import AdminPointAdjustment
from app.utils.grading import calculate_letter_grade

logger = logging.getLogger(__name__)


def _require_student(db: Session, student_id: int) -> User:
    student = (
        db.query(User)
        .filter(User.id == student_id, User.role == UserRole.STUDENT)
        .first()
    )
    if not student:
        raise ValueError(f"student {student_id} not found")
    return student


def execute_attendance(db: Session, args: dict, admin_id: int | None) -> dict:
    _require_student(db, int(args["student_id"]))
    when = date.fromisoformat(args["date"])
    status = args["status"]
    notes = args.get("notes")

    record = (
        db.query(AttendanceRecord)
        .filter(
            AttendanceRecord.student_id == int(args["student_id"]),
            AttendanceRecord.date == when,
        )
        .first()
    )
    if record:
        record.status = status
        record.notes = notes
        action = "updated"
    else:
        record = AttendanceRecord(
            student_id=int(args["student_id"]), date=when, status=status, notes=notes
        )
        db.add(record)
        action = "created"
    db.commit()
    db.refresh(record)
    # record.status round-trips through SQLAlchemy's Enum type as an
    # AttendanceStatus member (not the plain string that was assigned) —
    # unwrap it, since `result` is a JSONB column.
    status_value = (
        record.status.value if hasattr(record.status, "value") else record.status
    )
    return {
        "applied": f"attendance {action}",
        "student_id": record.student_id,
        "date": str(record.date),
        "status": status_value,
    }


def execute_journal_entry(db: Session, args: dict, admin_id: int | None) -> dict:
    _require_student(db, int(args["student_id"]))
    if admin_id is None:
        raise ValueError("a parent session is required to author journal entries")
    entry = JournalEntry(
        student_id=int(args["student_id"]),
        author_id=admin_id,
        title=args["title"],
        content=args["content"],
        entry_date=datetime.now(timezone.utc),
        mood=args.get("mood"),
        win=args.get("win"),
        needs_response=args.get("needs_response", True),
        reactions=[],
        tags=[],
        goals=[],
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {
        "applied": "journal_entry created",
        "entry_id": entry.id,
        "student_id": entry.student_id,
        "title": entry.title,
    }


def execute_assignments(db: Session, args: dict, admin_id: int | None) -> dict:
    active_term = db.query(Term).filter(Term.is_active).first()
    if not active_term:
        raise ValueError("no active term; set one before assigning work")

    template = (
        db.query(AssignmentTemplate)
        .filter(AssignmentTemplate.id == int(args["template_id"]))
        .first()
    )
    if not template:
        raise ValueError(f"template {args['template_id']} not found")
    if getattr(template, "is_archived", False):
        raise ValueError("cannot assign an archived template")

    student_ids = [int(s) for s in args["student_ids"]]
    students = (
        db.query(User)
        .filter(
            User.id.in_(student_ids), User.role == UserRole.STUDENT, User.is_active
        )
        .all()
    )
    found = {s.id for s in students}
    missing = set(student_ids) - found
    if missing:
        raise ValueError(f"students not found: {sorted(missing)}")

    assigned_date = date.fromisoformat(args["assigned_date"]) if args.get("assigned_date") else date.today()
    due_date = date.fromisoformat(args["due_date"])
    created: list[int] = []
    for sid in student_ids:
        sa = StudentAssignment(
            template_id=int(args["template_id"]),
            student_id=sid,
            assigned_date=assigned_date,
            due_date=due_date,
            custom_instructions=args.get("custom_instructions"),
            assigned_by=admin_id,
        )
        db.add(sa)
        db.flush()
        created.append(sa.id)
    db.commit()
    return {
        "applied": "assignments created",
        "template_id": int(args["template_id"]),
        "student_ids": student_ids,
        "assignment_ids": created,
        "due_date": str(due_date),
    }


def execute_grade(db: Session, args: dict, admin_id: int | None) -> dict:
    assignment = (
        db.query(StudentAssignment)
        .filter(StudentAssignment.id == int(args["assignment_id"]))
        .first()
    )
    if not assignment:
        raise ValueError(f"assignment {args['assignment_id']} not found")
    _require_student(db, assignment.student_id)

    max_points = assignment.max_points
    points_earned = float(args["points_earned"])
    if points_earned > max_points:
        raise ValueError(
            f"points ({points_earned}) exceed max ({max_points}) for this assignment"
        )

    assignment.points_earned = points_earned
    assignment.teacher_feedback = args.get("teacher_feedback")
    assignment.is_graded = True
    assignment.graded_date = date.today()
    assignment.graded_by = admin_id

    percentage = assignment.calculate_percentage_grade()
    assignment.letter_grade = calculate_letter_grade(
        percentage, get_grade_scale(db)
    )
    assignment.backfill_lifecycle_dates_for_grading()
    assignment.update_status()
    assignment.update_term_grade(db)
    db.commit()

    # Points sync (idempotent; mirrors the grading router)
    try:
        if points_crud.is_points_system_enabled(db):
            title = assignment.template.name if assignment.template else f"Assignment {assignment.id}"
            points_crud.set_assignment_points(
                db=db,
                student_id=assignment.student_id,
                assignment_id=assignment.id,
                points_earned=points_earned,
                assignment_title=title,
            )
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("points sync failed during copilot grade approval")

    db.refresh(assignment)
    return {
        "applied": "grade applied",
        "assignment_id": assignment.id,
        "points_earned": assignment.points_earned,
        "percentage_grade": assignment.percentage_grade,
        "letter_grade": assignment.letter_grade,
        "status": assignment.status,
    }


def execute_points(db: Session, args: dict, admin_id: int | None) -> dict:
    _require_student(db, int(args["student_id"]))
    adjustment = AdminPointAdjustment(
        student_id=int(args["student_id"]),
        amount=int(args["amount"]),
        notes=args.get("reason", ""),
    )
    txn = points_crud.admin_adjust_points(
        db, adjustment, admin_id, actor_name="copilot"
    )
    db.commit()
    return {
        "applied": "points adjusted",
        "student_id": txn.student_id,
        "amount": txn.amount,
        "transaction_type": txn.transaction_type,
    }


async def execute_weekly_plan(db: Session, args: dict, admin_id: int | None) -> dict:
    from app.services.ai_weekly_planner import generate_weekly_assignments

    _require_student(db, int(args["student_id"]))
    created = await generate_weekly_assignments(
        db, int(args["student_id"]), admin_id=admin_id
    )
    return {"applied": "weekly plan generated", "assignments_created": len(created)}


# tool_name -> (sync callable | None, async callable | None)
_SYNC_EXECUTORS = {
    "school_propose_attendance": execute_attendance,
    "school_propose_journal_entry": execute_journal_entry,
    "school_propose_assignments": execute_assignments,
    "school_propose_grade": execute_grade,
    "school_propose_points": execute_points,
}
_ASYNC_EXECUTORS = {
    "school_propose_weekly_plan": execute_weekly_plan,
}


async def dispatch_executor(
    db: Session, tool_name: str, args: dict, admin_id: int | None
) -> dict:
    """Run the executor for an approved proposal. Raises on unknown tool."""
    if tool_name in _ASYNC_EXECUTORS:
        return await _ASYNC_EXECUTORS[tool_name](db, args, admin_id)
    fn = _SYNC_EXECUTORS.get(tool_name)
    if fn is None:
        raise ValueError(f"no executor for proposal tool '{tool_name}'")
    return fn(db, args, admin_id)
