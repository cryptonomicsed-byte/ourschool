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

"""AI-assisted features: grading assist, report narratives, journal digests.

Generation runs through the local hermes agent (DeepSeek direct) — see
app/services/ai_client.py. All endpoints are admin/parent-scoped: these
are drafting aids for the parent to review, not automated writes.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dual_auth import (
    AuthUser,
    can_access_student_data,
    get_user_id_from_auth,
    require_admin_or_permission,
    require_admin_or_student_self_or_permission,
)
from app.schemas.ai import (
    GradingAssistResponse,
    JournalDigestResponse,
    NarrativeResponse,
    TutorBook,
    TutorBooksResponse,
    TutorSyncRequest,
    TutorSyncResponse,
    TutorTokenResponse,
    WeeklyPlanResponse,
)
from app.services.ai_client import AIGenerationError
from app.services.ai_grading import AIGradingService
from app.services.ai_journal_digest import AIJournalDigestService
from app.services.ai_narrative import AINarrativeService
from app.services.ai_weekly_planner import generate_weekly_assignments
from app.services.deeptutor_client import DeepTutorError, get_books, mint_student_token
from app.services.deeptutor_sync import sync_mastery_progress

router = APIRouter(tags=["ai"])


@router.post(
    "/assignments/{student_assignment_id}/grading-assist",
    response_model=GradingAssistResponse,
)
async def grading_assist(
    student_assignment_id: int,
    auth_user: Annotated[AuthUser, Depends(require_admin_or_permission("ai:grading"))],
    db: Session = Depends(get_db),
):
    try:
        result = await AIGradingService.suggest_grade(db, student_assignment_id)
    except AIGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return result


@router.post(
    "/reports/{student_id}/{term_id}/narrative",
    response_model=NarrativeResponse,
)
async def report_narrative(
    student_id: int,
    term_id: int,
    auth_user: Annotated[AuthUser, Depends(require_admin_or_permission("ai:reports"))],
    db: Session = Depends(get_db),
):
    try:
        result = await AINarrativeService.generate_report_narrative(
            db, student_id, term_id
        )
    except AIGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return result


@router.post(
    "/tutor/{student_id}/token",
    response_model=TutorTokenResponse,
)
async def tutor_token(
    student_id: int,
    auth_user: Annotated[
        AuthUser, Depends(require_admin_or_student_self_or_permission("ai:tutor"))
    ],
):
    if not can_access_student_data(auth_user, student_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only start a tutor session for yourself",
        )
    try:
        jwt, ws_url = await mint_student_token(student_id)
    except DeepTutorError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return TutorTokenResponse(token=jwt, ws_url=ws_url)


@router.get(
    "/tutor/{student_id}/books",
    response_model=TutorBooksResponse,
)
async def tutor_books(
    student_id: int,
    auth_user: Annotated[
        AuthUser, Depends(require_admin_or_student_self_or_permission("ai:tutor"))
    ],
):
    if not can_access_student_data(auth_user, student_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only list tutor subjects for yourself",
        )
    try:
        jwt, _ws_url = await mint_student_token(student_id)
        books = await get_books(jwt)
    except DeepTutorError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return TutorBooksResponse(
        books=[TutorBook(id=b["id"], title=b.get("title", b["id"])) for b in books]
    )


@router.post(
    "/tutor/{student_id}/weekly-plan",
    response_model=WeeklyPlanResponse,
)
async def weekly_plan(
    student_id: int,
    auth_user: Annotated[AuthUser, Depends(require_admin_or_permission("ai:tutor"))],
    db: Session = Depends(get_db),
):
    """Generate a week of AI assignments for the student, one template+
    instance per subject. Admin-triggered for now (not yet on a schedule)."""
    created = await generate_weekly_assignments(
        db, student_id, admin_id=get_user_id_from_auth(auth_user)
    )
    return WeeklyPlanResponse(assignments_created=len(created))


@router.post(
    "/tutor/{student_id}/sync",
    response_model=TutorSyncResponse,
)
async def tutor_sync(
    student_id: int,
    body: TutorSyncRequest,
    auth_user: Annotated[AuthUser, Depends(require_admin_or_permission("ai:tutor"))],
    db: Session = Depends(get_db),
):
    try:
        result = await sync_mastery_progress(
            db,
            student_id,
            body.book_id,
            body.subject_id,
            admin_id=get_user_id_from_auth(auth_user),
            book_title=body.book_title,
        )
    except DeepTutorError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    return result


@router.post(
    "/journal/{student_id}/digest",
    response_model=JournalDigestResponse,
)
async def journal_digest(
    student_id: int,
    auth_user: Annotated[AuthUser, Depends(require_admin_or_permission("ai:journal"))],
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
    db: Session = Depends(get_db),
):
    try:
        result = await AIJournalDigestService.generate_digest(
            db, student_id, date_from, date_to
        )
    except AIGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return result
