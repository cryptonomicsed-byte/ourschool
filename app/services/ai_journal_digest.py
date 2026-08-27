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

"""AI journal-digest service.

Summarizes a student's journal entries over a date range into a short,
parent-facing digest.
"""

from datetime import date, datetime, time, timezone
from typing import Dict

from sqlalchemy.orm import Session

from app.models.journal import JournalEntry
from app.models.user import User
from app.services.ai_client import generate


class AIJournalDigestService:
    """Summarizes a student's journal entries into a parent-facing digest."""

    @staticmethod
    async def generate_digest(
        db: Session, student_id: int, date_from: date, date_to: date
    ) -> Dict:
        student = db.query(User).filter(User.id == student_id).first()
        if not student:
            return {"error": "Student not found"}

        start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        end = datetime.combine(date_to, time.max, tzinfo=timezone.utc)

        entries = (
            db.query(JournalEntry)
            .filter(
                JournalEntry.student_id == student_id,
                JournalEntry.entry_date >= start,
                JournalEntry.entry_date <= end,
            )
            .order_by(JournalEntry.entry_date.asc())
            .all()
        )

        if not entries:
            return {"digest": "No journal entries in this date range."}

        prompt = AIJournalDigestService._build_prompt(
            student_name=f"{student.first_name} {student.last_name}", entries=entries
        )
        digest = await generate(prompt)
        return {"digest": digest}

    @staticmethod
    def _build_prompt(student_name: str, entries) -> str:
        entry_lines = "\n".join(
            f"- [{e.entry_date.date().isoformat()}]"
            f"{f' ({e.mood})' if e.mood else ''}: {e.content}"
            for e in entries
        )
        return (
            "You are a homeschool teaching assistant. Summarize the "
            f"following week of {student_name}'s journal entries into a "
            "short (3-5 sentence) parent-facing digest — highlight notable "
            "wins, moods/patterns, and anything that might need a parent's "
            "attention. Respond with plain text only, no headers or "
            "markdown.\n\n"
            f"Entries:\n{entry_lines}\n"
        )
