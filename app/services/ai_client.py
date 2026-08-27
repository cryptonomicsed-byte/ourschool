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

"""Text generation via the local hermes agent (DeepSeek direct).

Each call shells out to ``hermes -p <profile> chat -q <prompt> -Q`` as a
non-interactive subprocess, run under hermes's default profile (selected via
the ``-p`` global flag — NOT the HERMES_PROFILE env var, which only sets
kanban authorship, not the active profile), with reasoning-panel display off
(which would otherwise pollute stdout for models that return
reasoning_content). Uses hermes's built-in "deepseek" provider directly;
ourschool only ever talks to the hermes CLI.
"""

import asyncio
import logging

from app.core.config import settings
from app.core.database import get_engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class AIGenerationError(RuntimeError):
    """Raised when the hermes CLI fails or times out."""


AI_MODEL_SETTING_KEY = "ai.copilot_model"


def _resolve_model_and_provider() -> tuple[str, str]:
    """Look up the admin-configured copilot model (Settings > AI Copilot),
    falling back to the .env defaults when unset. Uses a short-lived session
    directly (rather than threading `db` through every ai_client caller)
    since this is a cheap single-row lookup."""
    from app.crud.settings import get_setting_value

    try:
        db = Session(bind=get_engine())
        try:
            raw = get_setting_value(db, AI_MODEL_SETTING_KEY, default_value=None)
        finally:
            db.close()
        if raw:
            import json

            parsed = json.loads(raw)
            return parsed.get("model", settings.hermes_model), parsed.get(
                "provider", settings.hermes_provider
            )
    except Exception:
        logger.exception("Failed to resolve configured AI model, using defaults")
    return settings.hermes_model, settings.hermes_provider


async def generate(prompt: str) -> str:
    """Run a single non-interactive hermes query and return its text response."""
    model, provider = _resolve_model_and_provider()
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.hermes_binary,
            "-p",
            settings.hermes_profile,
            "chat",
            "-q",
            prompt,
            "-Q",
            "--provider",
            provider,
            "-m",
            model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise AIGenerationError(
            f"hermes binary '{settings.hermes_binary}' not found"
        ) from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.hermes_timeout_seconds
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise AIGenerationError("hermes generation timed out") from exc

    if proc.returncode != 0:
        logger.error("hermes chat failed: %s", stderr.decode(errors="replace"))
        raise AIGenerationError("hermes generation failed")

    text = _strip_cli_warnings(stdout.decode(errors="replace")).strip()
    if not text:
        raise AIGenerationError("hermes returned an empty response")
    return text


_STDOUT_NOISE_PREFIXES = ("Warning:", "⚠")


def _strip_cli_warnings(raw: str) -> str:
    """Drop leading warning/notice lines hermes prints to stdout even in -Q
    quiet mode (e.g. unrecognized-toolset notices, first-run scanner
    notices on a fresh profile) — quiet mode only suppresses the
    banner/spinner/tool-previews, not these."""
    lines = raw.splitlines()
    while lines and lines[0].strip().startswith(_STDOUT_NOISE_PREFIXES):
        lines.pop(0)
    return "\n".join(lines)
