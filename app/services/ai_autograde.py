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

"""Auto-grading for AI-generated assignments.

Unlike app/services/ai_grading.py (a suggestion the parent reviews and
applies), this writes the grade directly — used only for
AssignmentTemplate.is_ai_generated=True submissions, where the copilot that
assigned the work also grades it, same as a real tutor would.
"""

import logging

from sqlalchemy.orm import Session

from app.models.assignment import StudentAssignment
from app.services.ai_client import AIGenerationError
from app.services.ai_grading import AIGradingService
from app.utils.grading import calculate_letter_grade

logger = logging.getLogger(__name__)


async def autograde_submission(db: Session, assignment: StudentAssignment) -> bool:
    """Grade `assignment` in place (does not commit — caller manages the
    transaction). Returns True if grading succeeded."""
    try:
        result = await AIGradingService.suggest_grade(db, assignment.id)
    except AIGenerationError:
        logger.exception("Auto-grade generation failed for assignment %s", assignment.id)
        return False

    if result.get("points_earned") is None:
        logger.warning(
            "Auto-grade returned no usable score for assignment %s", assignment.id
        )
        return False

    assignment.points_earned = result["points_earned"]
    assignment.calculate_percentage_grade()
    assignment.letter_grade = result.get("letter_grade") or (
        calculate_letter_grade(assignment.percentage_grade)
        if assignment.percentage_grade is not None
        else None
    )
    assignment.teacher_feedback = f"AI Tutor: {result['feedback']}"
    assignment.is_graded = True
    from datetime import date

    assignment.graded_date = date.today()
    assignment.graded_by = assignment.assigned_by
    assignment.backfill_lifecycle_dates_for_grading()
    assignment.update_status()
    assignment.update_term_grade(db)
    return True
