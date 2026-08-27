# OurSchool - Homeschool Management System
# Copyright (C) 2025 Dustan Ashley
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Pydantic schemas for the copilot surface."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class CopilotConversationCreate(BaseModel):
    title: Optional[str] = None


class CopilotConversationOut(BaseModel):
    id: int
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CopilotMessageOut(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    conversation_id: int
    message: str = ""
    message_min: int = 1
    message_max: int = 8000


class ProposalOut(BaseModel):
    id: int
    tool_name: str
    args: dict[str, Any]
    summary: str
    status: str
    created_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[int] = None
    result: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class ProposalDecision(BaseModel):
    reason: Optional[str] = None
