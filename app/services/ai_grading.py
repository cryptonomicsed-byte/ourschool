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

"""AI grading-assist service.

Suggests a grade and feedback for a submitted assignment. Never writes to the
database — the parent reviews and applies the suggestion via the existing
grading endpoint.
"""

import json
import re
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.assignment import StudentAssignment
from app.services.ai_client import generate

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class AIGradingService:
    """Suggests a grade/feedback for a student assignment submission."""

    @staticmethod
    async def suggest_grade(db: Session, student_assignment_id: int) -> Dict:
        assignment = (
            db.query(StudentAssignment)
            .filter(StudentAssignment.id == student_assignment_id)
            .first()
        )
        if not assignment:
            return {"error": "Assignment not found"}

        template = assignment.template
        max_points = assignment.max_points

        prompt = AIGradingService._build_prompt(
            name=template.name if template else "Assignment",
            instructions=(template.instructions if template else None)
            or (template.description if template else None)
            or "No rubric provided.",
            submission_notes=assignment.submission_notes or "No submission notes.",
            max_points=max_points,
        )

        raw = await generate(prompt)
        return AIGradingService._parse_response(raw, max_points)

    @staticmethod
    def _build_prompt(
        name: str, instructions: str, submission_notes: str, max_points: int
    ) -> str:
        return (
            "You are a homeschool teaching assistant helping a parent grade an "
            "assignment. Respond with ONLY a JSON object (no prose, no markdown "
            "fences) with keys: points_earned (number, 0 to "
            f"{max_points}), letter_grade (string), feedback (string, 2-4 "
            "sentences, encouraging but specific).\n\n"
            f"Assignment: {name}\n"
            f"Rubric/instructions: {instructions}\n"
            f"Max points: {max_points}\n"
            f"Student submission notes: {submission_notes}\n"
        )

    @staticmethod
    def _parse_response(raw: str, max_points: int) -> Dict:
        match = _JSON_BLOCK_RE.search(raw)
        if not match:
            return {"points_earned": None, "letter_grade": None, "feedback": raw}

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"points_earned": None, "letter_grade": None, "feedback": raw}

        points_earned: Optional[float] = data.get("points_earned")
        if isinstance(points_earned, (int, float)):
            points_earned = max(0.0, min(float(points_earned), float(max_points)))
        else:
            points_earned = None

        return {
            "points_earned": points_earned,
            "letter_grade": data.get("letter_grade"),
            "feedback": data.get("feedback") or raw,
        }
