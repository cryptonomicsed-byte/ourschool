# OurSchool - Homeschool Management System
# Copyright (C) 2025 Dustan Ashley
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""Copilot chat orchestration.

Runs the household's sovereign agent (hermes profile `ourschool`) as a
non-interactive subprocess per message, exactly like the existing ai_client
pattern — but the copilot profile carries the MCP tool surface
(ourschool-mcp) and its own persistent memory, so each turn is grounded in
real school data and the agent accumulates durable knowledge across chats.

Writes NEVER happen here: the agent may only create proposals (consent
ledger), which the parent approves via app/routers/copilot.py.
"""

import asyncio
import json
import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_engine

logger = logging.getLogger(__name__)

# The copilot's sovereign identity on this box (hermes profile). The existing
# ai_client features keep using HERMES_PROFILE (default); the copilot is its
# own agent with MCP tools + memory, so it pins its own profile.
COPILOT_PROFILE = "ourschool"
COPILOT_TIMEOUT_SECONDS = 240

_CONVERSATIONS_SQL = """
CREATE TABLE IF NOT EXISTS copilot_conversations (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(200) NOT NULL DEFAULT 'Copilot chat',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_copilot_conversations_user
    ON copilot_conversations (user_id, updated_at DESC);
"""

_MESSAGES_SQL = """
CREATE TABLE IF NOT EXISTS copilot_messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL
                    REFERENCES copilot_conversations(id) ON DELETE CASCADE,
    role            VARCHAR(10) NOT NULL,
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_copilot_messages_conversation
    ON copilot_messages (conversation_id, id);
"""

# Matches the schema ourschool-mcp ensures at boot — the two sides must agree.
_PROPOSALS_SQL = """
CREATE TABLE IF NOT EXISTS copilot_proposals (
    id            BIGSERIAL PRIMARY KEY,
    tool_name     TEXT NOT NULL,
    args          JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary       TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','approved','rejected','failed')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at    TIMESTAMPTZ,
    decided_by    INTEGER,
    result        JSONB
);
CREATE INDEX IF NOT EXISTS ix_copilot_proposals_status
    ON copilot_proposals (status, created_at DESC);
"""


def ensure_copilot_tables() -> None:
    """Idempotent table creation, called once from the app lifespan."""
    engine = get_engine()
    with engine.begin() as conn:
        for stmt in (_CONVERSATIONS_SQL, _MESSAGES_SQL, _PROPOSALS_SQL):
            conn.execute(text(stmt))
    logger.info("Copilot tables ensured")


class CopilotGenerationError(RuntimeError):
    """Raised when the copilot agent fails or times out."""


_STDOUT_NOISE_PREFIXES = ("Warning:", "⚠")


def _strip_cli_warnings(raw: str) -> str:
    """Drop leading warning/notice lines hermes prints to stdout even in -Q."""
    lines = raw.splitlines()
    while lines and lines[0].strip().startswith(_STDOUT_NOISE_PREFIXES):
        lines.pop(0)
    return "\n".join(lines)


COPILOT_MODE_SETTING_KEY = "ai.copilot_model"


def _resolve_copilot_mode() -> str:
    """"agent" (default) runs the full MCP-tooled `ourschool` hermes profile;
    "direct" skips tools/memory entirely and just calls the configured LLM,
    for households that want a plain chat assistant instead of the agent.
    Shares the ai.copilot_model setting with ai_client's model/provider
    picker (see app/routers/ai.py's Settings > AI Copilot section)."""
    from app.crud.settings import get_setting_value

    try:
        db = Session(bind=get_engine())
        try:
            raw = get_setting_value(db, COPILOT_MODE_SETTING_KEY, default_value=None)
        finally:
            db.close()
        if raw:
            parsed = json.loads(raw)
            mode = parsed.get("mode", "agent")
            if mode in ("agent", "direct"):
                return mode
    except Exception:
        logger.exception("Failed to resolve copilot mode, defaulting to agent")
    return "agent"


async def run_agent(prompt: str) -> str:
    """Run one non-interactive copilot turn and return its text response.

    Branches on the admin-configured mode: "agent" runs the sovereign
    `ourschool` hermes profile (MCP tools + persistent memory); "direct"
    calls the plain configured LLM with no tools, via the same code path
    as ai_client.generate (grading-assist, weekly planner, etc).
    """
    if _resolve_copilot_mode() == "direct":
        from app.services.ai_client import AIGenerationError, generate

        try:
            return await generate(prompt)
        except AIGenerationError as exc:
            raise CopilotGenerationError(str(exc)) from exc

    try:
        proc = await asyncio.create_subprocess_exec(
            settings.hermes_binary,
            "-p",
            COPILOT_PROFILE,
            "chat",
            "-q",
            prompt,
            "-Q",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise CopilotGenerationError(
            f"hermes binary '{settings.hermes_binary}' not found"
        ) from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=COPILOT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise CopilotGenerationError("copilot agent timed out") from exc

    if proc.returncode != 0:
        logger.error("copilot agent failed: %s", stderr.decode(errors="replace"))
        raise CopilotGenerationError("copilot agent failed")

    text_out = _strip_cli_warnings(stdout.decode(errors="replace")).strip()
    if not text_out:
        raise CopilotGenerationError("copilot agent returned an empty response")
    return text_out


def build_context(db: Session) -> dict:
    """Compact household snapshot injected into every turn so the agent is
    grounded without having to burn tool calls on orientation."""
    today = date.today()
    ctx: dict = {"date": today.isoformat(), "weekday": today.strftime("%A")}

    row = db.execute(
        text(
            "SELECT id, name, academic_year, start_date, end_date, term_type"
            " FROM terms WHERE is_active = true ORDER BY start_date DESC LIMIT 1"
        )
    ).mappings().first()
    ctx["active_term"] = dict(row) if row else None

    students = db.execute(
        text(
            "SELECT id, first_name, last_name, grade_level"
            " FROM users WHERE role = 'student' AND is_active = true ORDER BY id"
        )
    ).mappings().all()
    ctx["students"] = [dict(s) for s in students]

    pending = db.execute(
        text("SELECT count(*) AS n FROM copilot_proposals WHERE status = 'pending'")
    ).scalar()
    ctx["pending_proposals"] = pending or 0
    return ctx


def build_prompt(
    context: dict,
    history: list[dict],
    new_message: str,
    speaker: dict | None = None,
) -> str:
    """Assemble a self-contained prompt: context + recent history + message.

    The agent keeps its own memory; we still pass the last few turns so the
    reply is coherent within the current chat even if memory didn't latch.

    `speaker` identifies who is actually typing this turn — `{"role":
    "parent"|"student", "name": str}`. Same agent, same tools, same consent
    gate either way, but the voice adapts: warm household-ops partner for
    the parent, patient teacher/tutor for the student (this is also the
    household's DeepTutor-integrated agent — it can see her curriculum and
    mastery data via the school_tutor_* tools).
    """
    is_student = bool(speaker and speaker.get("role") == "student")
    speaker_name = (speaker or {}).get("name")

    lines: list[str] = []
    if is_student:
        lines.append(
            "You are the OurSchool copilot, acting right now as "
            f"{speaker_name or 'the student'}'s AI teacher/tutor. You have the "
            "same tools and memory as when you talk to her parent, but your job "
            "here is to teach, encourage, and help her get schoolwork done — not "
            "to run the household."
        )
    else:
        lines.append("You are the OurSchool copilot, the household's sovereign school agent.")
    lines.append("")
    lines.append("TODAY")
    lines.append(f"- Date: {context.get('date')} ({context.get('weekday')})")
    term = context.get("active_term")
    if term:
        lines.append(
            f"- Active term: {term['name']} ({term['academic_year']}, "
            f"{term['term_type']}), {term['start_date']} -> {term['end_date']}"
        )
    else:
        lines.append("- Active term: none set")
    students = context.get("students") or []
    if students:
        lines.append(
            "- Students: "
            + "; ".join(
                f"{s['first_name']} {s['last_name']} (id {s['id']}, "
                f"grade {s['grade_level']})"
                for s in students
            )
        )
    lines.append(f"- Pending proposals awaiting parent approval: {context.get('pending_proposals', 0)}")
    lines.append(
        f"- You are talking directly to: {speaker_name or 'the parent'} "
        f"({'the student' if is_student else 'the parent/admin'})."
    )
    lines.append("")
    lines.append("RULES")
    lines.append("- Ground every answer in real data via the school_* MCP tools. Never invent facts.")
    lines.append(
        "- You may read anything. NEVER write directly, even if the student asks you to grade or log "
        "something for them: use school_propose_* to create a proposal. Only the parent can approve it — "
        "a student's request is never itself approval."
    )
    lines.append("- If you created a proposal, say so and note it awaits the parent's approval on the Copilot page.")
    if is_student:
        lines.append(
            "- Teach like a real tutor: explain concepts step by step, ask guiding questions before "
            "handing over answers, and check her understanding. Use school_tutor_books / "
            "school_tutor_mastery to ground help in her actual DeepTutor curriculum and mastery levels "
            "when relevant, instead of generic material."
        )
        lines.append("- Warm and encouraging. Praise real effort specifically, not generically.")
    else:
        lines.append("- Be warm, concise, and practical. Plain language.")
    lines.append("")
    if history:
        lines.append("RECENT CONVERSATION (oldest first)")
        for h in history:
            who = "them" if h["role"] == "user" else "copilot"
            lines.append(f"{who}: {h['content']}")
        lines.append("")
    lines.append(f"NEW MESSAGE FROM {'THE STUDENT' if is_student else 'THE PARENT'}")
    lines.append(new_message)
    lines.append("")
    lines.append("Respond now.")
    return "\n".join(lines)


def recent_history(db: Session, conversation_id: int, limit: int = 10) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT role, content FROM copilot_messages"
            " WHERE conversation_id = :cid ORDER BY id DESC LIMIT :lim"
        ),
        {"cid": conversation_id, "lim": limit},
    ).mappings().all()
    return list(reversed([dict(r) for r in rows]))
