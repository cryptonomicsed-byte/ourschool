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

"""Schemas for AI-assisted features."""

from typing import Optional

from pydantic import BaseModel


class GradingAssistResponse(BaseModel):
    """Suggested grade/feedback for a student assignment submission."""

    points_earned: Optional[float] = None
    letter_grade: Optional[str] = None
    feedback: str


class WeeklyPlanResponse(BaseModel):
    """Result of running the AI weekly assignment planner for a student."""

    assignments_created: int


class NarrativeResponse(BaseModel):
    """Draft written narrative for a term report card."""

    narrative: str


class JournalDigestResponse(BaseModel):
    """Parent-facing summary of a student's journal entries over a range."""

    digest: str


class TutorTokenResponse(BaseModel):
    """Short-lived DeepTutor JWT + WebSocket URL for the frontend to connect with."""

    token: str
    ws_url: str


class TutorBook(BaseModel):
    """One DeepTutor book/subject the student can chat or be quizzed in."""

    id: str
    title: str


class TutorBooksResponse(BaseModel):
    """Books available to the student's DeepTutor account."""

    books: list[TutorBook]


class TutorSyncRequest(BaseModel):
    """Which DeepTutor book/subject to pull mastery progress from."""

    book_id: str
    subject_id: int
    book_title: Optional[str] = None


class TutorSyncResponse(BaseModel):
    """Result of syncing DeepTutor mastery progress into the gradebook."""

    modules_synced: int
