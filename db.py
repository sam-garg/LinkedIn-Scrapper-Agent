"""Supabase persistence layer."""

from __future__ import annotations

from supabase import Client, create_client

from config import SUPABASE_SERVICE_KEY, SUPABASE_URL

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    return _client


def upsert_universities(rows: list[dict]) -> list[dict]:
    """Insert universities (ignoring duplicates) and return all matching rows."""
    if not rows:
        return []
    payload = [
        {"name": r["name"], "country": r.get("country"), "source_ref": r.get("source_ref")}
        for r in rows
    ]
    client().table("universities").upsert(payload, on_conflict="name").execute()

    names = [r["name"] for r in rows]
    stored: list[dict] = []
    for i in range(0, len(names), 100):
        chunk = names[i : i + 100]
        res = client().table("universities").select("*").in_("name", chunk).execute()
        stored.extend(res.data or [])
    return stored


def pending_universities() -> list[dict]:
    res = (
        client()
        .table("universities")
        .select("*")
        .neq("status", "done")
        .order("created_at")
        .execute()
    )
    return res.data or []


def set_status(university_id: str, status: str, error: str | None = None) -> None:
    client().table("universities").update(
        {"status": status, "last_error": error}
    ).eq("id", university_id).execute()


def save_students(university_id: str, students: list[dict]) -> int:
    """Upsert students on profile_url; returns rows sent."""
    payload = []
    for s in students:
        url = (s.get("profile_url") or "").strip()
        if not url:
            continue
        payload.append(
            {
                "university_id": university_id,
                "full_name": s.get("full_name"),
                "headline": s.get("headline"),
                "location": s.get("location"),
                "profile_url": url,
            }
        )
    if not payload:
        return 0
    client().table("students").upsert(payload, on_conflict="profile_url").execute()
    return len(payload)
