from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_DNS, uuid5

from dateutil import parser as dt_parser

from normalization.soccer_competitions import SOCCER_COMPETITION_KEYWORDS, SUPPORTED_SOCCER_COMPETITIONS
from normalization.team_aliases import STOPWORDS, aliases_for_sport


TEAM_SPLIT_PATTERNS = [
    re.compile(r"(?P<home>.+?)\s+(?:vs\.?|v|@|at)\s+(?P<away>.+)", re.IGNORECASE),
    re.compile(r"(?P<home>.+?)\s+-\s+(?P<away>.+)", re.IGNORECASE),
]


@dataclass(slots=True)
class VenueMarket:
    venue: str
    venue_market_id: str
    title: str
    sport: str
    competition: str | None
    start_time_utc: datetime | None
    home_team: str | None
    away_team: str | None
    market_type: str
    outcomes: list[str]
    raw: dict[str, Any]


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = dt_parser.parse(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (ValueError, TypeError, OverflowError):
            return None
    return None


def normalize_text(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s]", " ", value.lower())
    tokens = [token for token in text.split() if token and token not in STOPWORDS]
    return " ".join(tokens)


def canonicalize_team(sport: str, raw_team: str | None) -> str | None:
    if not raw_team:
        return None
    normalized = normalize_text(raw_team)
    aliases = aliases_for_sport(sport)
    if normalized in aliases:
        return aliases[normalized]

    # Try alias match by substring against known keys.
    for alias, canonical in aliases.items():
        if alias in normalized:
            return canonical
    return normalized


def parse_teams_from_title(title: str) -> tuple[str | None, str | None]:
    compact = re.sub(r"\s+", " ", title).strip()
    for pattern in TEAM_SPLIT_PATTERNS:
        match = pattern.search(compact)
        if match:
            home = match.group("home").strip(" -:|")
            away = match.group("away").strip(" -:|")
            return home, away
    return None, None


def detect_sport(title: str, category: str | None = None, tags: list[str] | None = None) -> str:
    haystacks = [title.lower()]
    if category:
        haystacks.append(category.lower())
    if tags:
        haystacks.extend(tag.lower() for tag in tags)
    joined = " ".join(haystacks)

    nba_keywords = {"nba", "basketball"}
    soccer_keywords = {"soccer", "football", "epl", "ucl", "uel", "laliga", "la liga"}

    if any(keyword in joined for keyword in nba_keywords):
        return "NBA"
    if any(keyword in joined for keyword in soccer_keywords):
        return "SOCCER"
    return "UNKNOWN"


def detect_competition(sport: str, title: str, tags: list[str] | None = None, explicit: str | None = None) -> str | None:
    if sport == "NBA":
        return "NBA"
    if sport != "SOCCER":
        return None

    candidates: list[str] = []
    if explicit:
        candidates.append(explicit.lower())
    candidates.append(title.lower())
    if tags:
        candidates.extend(tag.lower() for tag in tags)

    joined = " ".join(candidates)
    for keyword, competition in SOCCER_COMPETITION_KEYWORDS.items():
        if keyword in joined:
            if competition in SUPPORTED_SOCCER_COMPETITIONS:
                return competition
            return None
    return None


def detect_market_type(outcomes: list[str]) -> str:
    lowered = [outcome.lower() for outcome in outcomes]
    if len(outcomes) == 2 and {"yes", "no"}.issubset(set(lowered)):
        return "WINNER_BINARY"
    if len(outcomes) == 3:
        return "WINNER_3WAY"
    return "OTHER"


def deterministic_event_id(
    sport: str,
    competition: str | None,
    start_time_utc: datetime,
    home_team: str,
    away_team: str,
) -> str:
    payload = f"{sport}|{competition or ''}|{start_time_utc.isoformat()}|{home_team}|{away_team}".lower()
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return str(uuid5(NAMESPACE_DNS, digest))


def build_venue_market(
    *,
    venue: str,
    venue_market_id: str,
    title: str,
    outcomes: list[str],
    start_time: Any,
    sport_hint: str | None = None,
    competition_hint: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    raw: dict[str, Any] | None = None,
) -> VenueMarket:
    sport = sport_hint or detect_sport(title, category=category, tags=tags)
    competition = detect_competition(sport, title, tags=tags, explicit=competition_hint)
    start_time_utc = parse_time(start_time)

    raw_home, raw_away = parse_teams_from_title(title)
    home = canonicalize_team(sport, raw_home)
    away = canonicalize_team(sport, raw_away)

    market_type = detect_market_type(outcomes)

    return VenueMarket(
        venue=venue,
        venue_market_id=venue_market_id,
        title=title,
        sport=sport,
        competition=competition,
        start_time_utc=start_time_utc,
        home_team=home,
        away_team=away,
        market_type=market_type,
        outcomes=outcomes,
        raw=raw or {},
    )
