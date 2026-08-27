# OurSchool - Homeschool Management System
# Copyright (C) 2025 Dustan Ashley
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Copilot persistence: conversations, messages, and consent-gated proposals.

The proposal table mirrors the schema the MCP server ensures on boot
(`copilot_proposals` in ourschool-mcp/src/db.ts) so both sides agree on the
consent ledger. Proposals are drafts the agent writes; only the approval
endpoint in app/routers/copilot.py executes them.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CopilotConversation(Base):
    __tablename__ = "copilot_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="Copilot chat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    messages: Mapped[list["CopilotMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="CopilotMessage.id",
    )


class CopilotMessage(Base):
    __tablename__ = "copilot_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("copilot_conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(10))  # user | agent
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )

    conversation: Mapped[CopilotConversation] = relationship(
        back_populates="messages"
    )


class CopilotProposal(Base):
    __tablename__ = "copilot_proposals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(120))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
