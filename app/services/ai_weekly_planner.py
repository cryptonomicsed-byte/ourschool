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

"""AI weekly assignment planner.

Generates a week's worth of assignments for a student, one per active
subject, using the same configurable copilot model as the AI Tutor and
grading-assist (see app/services/ai_client.py). Each generated assignment is
a full AssignmentTemplate (is_ai_generated=True) with everything the student
needs baked into `instructions` — no separate content-fetch step — plus a
StudentAssignment instance due in 7 days. Submissions against these are
auto-graded (see app/services/ai_autograde.py) instead of waiting on manual
parent review.
"""

import json
import re
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.enums import AssignmentType
from app.models.assignment import AssignmentTemplate, StudentAssignment
from app.models.subject import Subject
from app.services.ai_client import AIGenerationError, generate

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

_VALID_TYPES = {t.value for t in AssignmentType}


def _build_prompt(subject_name: str, grade_level: Optional[int]) -> str:
    grade = f"{grade_level}th grade" if grade_level else "6th grade"
    return (
        "You are a homeschool teacher planning one week of work for a "
        f"{grade} student in {subject_name}. Generate exactly 3 assignments "
        "covering a range of difficulty and format, appropriate for "
        "independent at-home study.\n\n"
        "Respond with ONLY a JSON array (no prose, no markdown fences) of "
        "3 objects, each with keys:\n"
        '- "name": short title (string)\n'
        '- "assignment_type": one of '
        f"{sorted(_VALID_TYPES)}\n"
        '- "instructions": the FULL self-contained assignment text the '
        "student will read to do the work — include the actual questions/"
        "problems/prompts, not just a topic description. This is the only "
        "thing the student sees, so it must be complete.\n"
        '- "max_points": integer 10-100\n'
        '- "estimated_duration_minutes": integer 10-60\n'
    )


def _parse_assignments(raw: str) -> List[Dict]:
    match = _JSON_ARRAY_RE.search(raw)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    parsed = []
    for item in data:
        if not isinstance(item, dict) or not item.get("name") or not item.get(
            "instructions"
        ):
            continue
        assignment_type = item.get("assignment_type")
        if assignment_type not in _VALID_TYPES:
            assignment_type = AssignmentType.HOMEWORK.value
        try:
            max_points = int(item.get("max_points") or 100)
        except (TypeError, ValueError):
            max_points = 100
        try:
            duration = int(item.get("estimated_duration_minutes") or 30)
        except (TypeError, ValueError):
            duration = 30
        parsed.append(
            {
                "name": str(item["name"])[:200],
                "assignment_type": assignment_type,
                "instructions": str(item["instructions"]),
                "max_points": max(10, min(max_points, 1000)),
                "estimated_duration_minutes": max(5, min(duration, 240)),
            }
        )
    return parsed


async def generate_weekly_assignments(
    db: Session, student_id: int, admin_id: Optional[int]
) -> List[StudentAssignment]:
    """Generate and persist one week of AI assignments across every subject.

    Returns the created StudentAssignment rows (templates are created
    alongside them, one template per generated assignment).
    """
    subjects = db.query(Subject).all()
    due = date.today() + timedelta(days=7)
    created: List[StudentAssignment] = []

    for subject in subjects:
        prompt = _build_prompt(subject.name, grade_level=6)
        try:
            raw = await generate(prompt)
        except AIGenerationError:
            continue

        for spec in _parse_assignments(raw):
            template = AssignmentTemplate(
                name=spec["name"],
                instructions=spec["instructions"],
                assignment_type=spec["assignment_type"],
                subject_id=subject.id,
                max_points=spec["max_points"],
                estimated_duration_minutes=spec["estimated_duration_minutes"],
                is_ai_generated=True,
                is_exportable=False,
                created_by=admin_id,
            )
            db.add(template)
            db.flush()  # populate template.id for the FK below

            student_assignment = StudentAssignment(
                template_id=template.id,
                student_id=student_id,
                due_date=due,
                assigned_by=admin_id,
            )
            db.add(student_assignment)
            created.append(student_assignment)

    db.commit()
    for sa in created:
        db.refresh(sa)
    return created
