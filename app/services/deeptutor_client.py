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

"""Thin REST client for the local DeepTutor instance (AI tutor backend).

ourschool never sends DeepTutor credentials to the frontend: the backend
logs in as the student's own DeepTutor account server-side (DeepTutor has
no admin login-as-user endpoint) and hands the frontend a short-lived JWT
to open its own WebSocket chat connection directly to DeepTutor.
"""

import json

import httpx

from app.core.config import settings


class DeepTutorError(RuntimeError):
    """Raised when a DeepTutor API call fails."""


def _student_credentials(student_id: int) -> dict:
    try:
        mapping = json.loads(settings.deeptutor_student_credentials_map)
    except (json.JSONDecodeError, TypeError):
        mapping = {}
    creds = mapping.get(str(student_id))
    if not isinstance(creds, dict) or not creds.get("username") or not creds.get("password"):
        raise DeepTutorError(f"No DeepTutor account configured for student {student_id}")
    return creds


async def login(username: str, password: str) -> str:
    """Log in to DeepTutor and return the JWT."""
    async with httpx.AsyncClient(base_url=settings.deeptutor_base_url, timeout=15.0) as client:
        resp = await client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        if resp.status_code != 200:
            raise DeepTutorError(f"DeepTutor login failed for '{username}'")
        token = resp.cookies.get("dt_token")
        if not token:
            raise DeepTutorError("DeepTutor login did not return a token")
        return token


async def mint_student_token(student_id: int) -> tuple[str, str]:
    """Log in as the student's DeepTutor account. Returns (jwt, ws_url).

    The WebSocket URL is built from deeptutor_public_base_url (what the
    student's browser can actually reach), not deeptutor_base_url (which is
    the internal address ourschool's backend uses for server-to-server REST
    calls — the two differ whenever DeepTutor and ourschool's backend share
    a host that the browser can't address directly, e.g. both on a VPS).
    """
    creds = _student_credentials(student_id)
    jwt = await login(creds["username"], creds["password"])
    public_base = settings.deeptutor_public_base_url or settings.deeptutor_base_url
    ws_base = public_base.replace("http://", "ws://").replace("https://", "wss://")
    return jwt, f"{ws_base}/api/v1/ws"


async def get_books(jwt: str) -> list[dict]:
    """List the books available to the logged-in DeepTutor account (used to
    let a student pick which subject to chat/quiz in)."""
    async with httpx.AsyncClient(base_url=settings.deeptutor_base_url, timeout=15.0) as client:
        resp = await client.get(
            "/api/v1/book/books",
            headers={"Authorization": f"Bearer {jwt}"},
        )
        if resp.status_code != 200:
            raise DeepTutorError("Failed to fetch DeepTutor book list")
        return resp.json().get("books", [])


async def get_mastery_map(jwt: str, book_id: str) -> dict:
    async with httpx.AsyncClient(base_url=settings.deeptutor_base_url, timeout=30.0) as client:
        resp = await client.get(
            f"/api/v1/learning/progress/{book_id}/map",
            headers={"Authorization": f"Bearer {jwt}"},
        )
        if resp.status_code != 200:
            raise DeepTutorError(f"Failed to fetch mastery map for book {book_id}")
        return resp.json()
