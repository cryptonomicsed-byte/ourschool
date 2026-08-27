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

"""AI report-card narrative generation service."""

from typing import Dict

from sqlalchemy.orm import Session

from app.crud.reports import grades as crud_reports
from app.services.ai_client import generate


class AINarrativeService:
    """Drafts the written summary section of a term report card."""

    @staticmethod
    async def generate_report_narrative(
        db: Session, student_id: int, term_id: int
    ) -> Dict:
        try:
            report_card = crud_reports.get_report_card(db, student_id, term_id)
        except ValueError as exc:
            return {"error": str(exc)}

        prompt = AINarrativeService._build_prompt(report_card)
        narrative = await generate(prompt)
        return {"narrative": narrative}

    @staticmethod
    def _build_prompt(report_card) -> str:
        subject_lines = "\n".join(
            (
                f"- {sg.subject_name}: {sg.letter_grade or 'N/A'} "
                f"({sg.percentage_grade:.0f}%)"
                if sg.percentage_grade is not None
                else f"- {sg.subject_name}: {sg.letter_grade or 'N/A'}"
            )
            for sg in report_card.subject_grades
        ) or "No graded subjects this term."

        return (
            "You are a homeschool teaching assistant drafting the written "
            "summary section of a parent-facing term report card. Write 3-5 "
            "warm, specific sentences covering overall progress, strengths, "
            "and one area to focus on next term. Respond with plain text "
            "only, no headers or markdown.\n\n"
            f"Student: {report_card.student_name}\n"
            f"Term: {report_card.term_name} ({report_card.academic_year})\n"
            f"Overall: {report_card.summary.overall_percentage:.0f}% "
            f"({report_card.summary.overall_letter_grade or 'N/A'})\n"
            f"Subject grades:\n{subject_lines}\n"
        )
