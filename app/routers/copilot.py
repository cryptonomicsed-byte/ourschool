# OurSchool - Homeschool Management System
# Copyright (C) 2025 Dustan Ashley
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Copilot endpoints: conversations, streaming chat, and the consent ledger.

The chat endpoint streams the household's sovereign agent's reply (hermes
profile `ourschool`, which carries the school MCP tools + its own memory).
Both the parent AND the student can chat with it — conversations are scoped
per-user (a student only ever sees their own), and the agent adapts its
voice depending on who it's talking to (see copilot_service.build_prompt).
The proposal endpoints are the ONLY write path the agent can influence, and
stay parent-only: a proposal the agent created (from either a parent or
student chat) stays pending until the parent approves it, then the matching
executor applies it through the app's own services. A student chatting with
the agent can never approve a write, even one about themselves.
"""

import json
import logging
from typing import Annotated, AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dual_auth import (
    AuthUser,
    get_user_id_from_auth,
    require_admin_or_permission,
    require_user_or_permission,
)
from app.models.user import User, UserRole
from app.models.copilot import CopilotConversation, CopilotMessage, CopilotProposal
from app.schemas.copilot import (
    ChatRequest,
    CopilotConversationCreate,
    CopilotConversationOut,
    CopilotMessageOut,
    ProposalDecision,
    ProposalOut,
)
from app.services.copilot_executors import dispatch_executor
from app.services.copilot_service import (
    CopilotGenerationError,
    build_context,
    build_prompt,
    recent_history,
    run_agent,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["copilot"])

COPILOT_PERMISSION = "ai:copilot"


def _require_owner(db: Session, auth_user: AuthUser, conversation_id: int) -> CopilotConversation:
    user_id = get_user_id_from_auth(auth_user)
    conv = (
        db.query(CopilotConversation)
        .filter(CopilotConversation.id == conversation_id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user_id is not None and conv.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not your conversation")
    return conv


@router.post("/conversations", response_model=CopilotConversationOut)
def create_conversation(
    body: CopilotConversationCreate,
    auth_user: Annotated[AuthUser, Depends(require_user_or_permission(COPILOT_PERMISSION))],
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_auth(auth_user) or 0
    conv = CopilotConversation(
        user_id=user_id,
        title=body.title or f"Copilot chat {date_today_str()}",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def date_today_str() -> str:
    from datetime import date

    return date.today().isoformat()


@router.get("/conversations", response_model=list[CopilotConversationOut])
def list_conversations(
    auth_user: Annotated[AuthUser, Depends(require_user_or_permission(COPILOT_PERMISSION))],
    db: Session = Depends(get_db),
):
    user_id = get_user_id_from_auth(auth_user)
    q = db.query(CopilotConversation).order_by(CopilotConversation.updated_at.desc())
    if user_id is not None:
        q = q.filter(CopilotConversation.user_id == user_id)
    return q.limit(100).all()


@router.get("/conversations/{conversation_id}/messages", response_model=list[CopilotMessageOut])
def list_messages(
    conversation_id: int,
    auth_user: Annotated[AuthUser, Depends(require_user_or_permission(COPILOT_PERMISSION))],
    db: Session = Depends(get_db),
):
    _require_owner(db, auth_user, conversation_id)
    return (
        db.query(CopilotMessage)
        .filter(CopilotMessage.conversation_id == conversation_id)
        .order_by(CopilotMessage.id.asc())
        .limit(500)
        .all()
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


async def _event_stream(reply: str, pending: int) -> AsyncGenerator[str, None]:
    """Chunk the reply as SSE delta events, then a done event with the ledger count."""
    step = 120
    for i in range(0, len(reply), step):
        yield _sse({"type": "delta", "content": reply[i : i + step]})
    yield _sse({"type": "done", "content": reply, "pending_proposals": pending})


@router.post("/chat")
async def copilot_chat(
    body: ChatRequest,
    auth_user: Annotated[AuthUser, Depends(require_user_or_permission(COPILOT_PERMISSION))],
    db: Session = Depends(get_db),
):
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required")

    conv = _require_owner(db, auth_user, body.conversation_id)

    db.add(CopilotMessage(conversation_id=conv.id, role="user", content=message))
    db.commit()

    speaker = None
    if isinstance(auth_user, User):
        speaker = {
            "role": "student" if auth_user.role == UserRole.STUDENT else "parent",
            "name": auth_user.first_name,
        }

    try:
        context = build_context(db)
        history = recent_history(db, conv.id, limit=10)
        prompt = build_prompt(context, history, message, speaker=speaker)
        logger.info("copilot chat: running agent for conversation %s", conv.id)
        reply = await run_agent(prompt)
    except CopilotGenerationError as exc:
        logger.error("copilot chat failed: %s", exc)
        db.add(
            CopilotMessage(
                conversation_id=conv.id,
                role="agent",
                content=f"[Copilot unavailable: {exc}]",
            )
        )
        db.commit()
        return StreamingResponse(
            _event_stream(f"I hit a problem reaching my agent core: {exc}", 0),
            media_type="text/event-stream",
        )

    db.add(CopilotMessage(conversation_id=conv.id, role="agent", content=reply))
    conv.updated_at = _utcnow()
    db.commit()

    pending = (
        db.query(CopilotProposal).filter(CopilotProposal.status == "pending").count()
    )
    return StreamingResponse(_event_stream(reply, pending), media_type="text/event-stream")


def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    auth_user: Annotated[AuthUser, Depends(require_admin_or_permission(COPILOT_PERMISSION))],
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    q = db.query(CopilotProposal)
    if status_filter and status_filter != "all":
        q = q.filter(CopilotProposal.status == status_filter)
    return q.order_by(CopilotProposal.created_at.desc()).limit(100).all()


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
async def approve_proposal(
    proposal_id: int,
    auth_user: Annotated[AuthUser, Depends(require_admin_or_permission(COPILOT_PERMISSION))],
    db: Session = Depends(get_db),
):
    proposal = db.get(CopilotProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=400, detail="Proposal is not pending")

    admin_id = get_user_id_from_auth(auth_user)
    try:
        result = await dispatch_executor(db, proposal.tool_name, proposal.args, admin_id)
    except Exception as exc:
        logger.exception("proposal %s execution failed", proposal_id)
        proposal.status = "failed"
        proposal.result = {"error": str(exc)}
        proposal.decided_at = _utcnow()
        proposal.decided_by = admin_id
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proposal execution failed: {exc}",
        ) from exc

    proposal.status = "approved"
    proposal.result = result
    proposal.decided_at = _utcnow()
    proposal.decided_by = admin_id
    db.commit()
    db.refresh(proposal)
    return proposal


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject_proposal(
    proposal_id: int,
    auth_user: Annotated[AuthUser, Depends(require_admin_or_permission(COPILOT_PERMISSION))],
    db: Session = Depends(get_db),
    body: ProposalDecision = ProposalDecision(),
):
    proposal = db.get(CopilotProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=400, detail="Proposal is not pending")

    admin_id = get_user_id_from_auth(auth_user)
    proposal.status = "rejected"
    proposal.result = {"reason": body.reason} if body.reason else {}
    proposal.decided_at = _utcnow()
    proposal.decided_by = admin_id
    db.commit()
    db.refresh(proposal)
    return proposal
