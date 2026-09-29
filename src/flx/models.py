"""Plain data parsed from API responses. Parsing never raises: a missing or malformed field is None."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

PROJECT_URL = "https://www.freelancer.com/projects/{seo_url}"


@dataclass(frozen=True)
class Project:
    id: int | None
    title: str | None
    url: str | None
    type: str | None
    budget_min: float | None
    budget_max: float | None
    currency: str | None
    bid_count: int | None
    bid_avg: float | None
    time_submitted: int | None  # Unix seconds
    client_country: str | None
    payment_verified: bool | None
    description: str | None


def parse_search(result: Any) -> list[Project]:
    """Projects from a `result` holding a `projects` list (search and multi-project calls)."""
    projects = _get(result, "projects")
    if not isinstance(projects, list):
        return []
    return [parse_project(raw) for raw in projects if isinstance(raw, dict)]


def parse_project(raw: Any) -> Project:
    owner = _get(raw, "owner_info")  # only sent when asked for with owner_info=true
    seo_url = _str(_get(raw, "seo_url"))
    return Project(
        id=_int(_get(raw, "id")),
        title=_str(_get(raw, "title")),
        url=PROJECT_URL.format(seo_url=seo_url) if seo_url else None,
        type=_str(_get(raw, "type")),
        budget_min=_num(_get(raw, "budget", "minimum")),
        budget_max=_num(_get(raw, "budget", "maximum")),
        currency=_str(_get(raw, "currency", "code")),
        bid_count=_int(_get(raw, "bid_stats", "bid_count")),
        bid_avg=_num(_get(raw, "bid_stats", "bid_avg")),
        time_submitted=_int(_get(raw, "time_submitted")),
        client_country=_str(_get(owner, "country", "name")),
        payment_verified=_bool(_get(owner, "status", "payment_verified")),
        description=_str(_get(raw, "description")) or _str(_get(raw, "preview_description")),
    )


def parse_username(result: Any) -> str | None:
    return _str(_get(result, "username"))


def merge_projects(batches: Iterable[Iterable[Project]]) -> list[Project]:
    """One list from many searches: first copy of each id kept, newest first, undated last."""
    seen: set[int] = set()
    merged = []
    for batch in batches:
        for project in batch:
            if project.id is not None:
                if project.id in seen:
                    continue
                seen.add(project.id)
            merged.append(project)
    return sorted(merged, key=lambda p: (p.time_submitted is None, -(p.time_submitted or 0)))


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
