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
WORD_RE = re.compile(r"[a-z0-9]+")


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
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
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

    # Fallback alias match with word boundaries (avoids short-code false positives like "den" in "golden").
    for alias, canonical in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"(^|\s){re.escape(alias)}($|\s)"
        if re.search(pattern, normalized):
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


def _text_chunks(title: str, category: str | None, tags: list[str] | None) -> list[str]:
    chunks = [title.lower()]
    if category:
        chunks.append(category.lower())
    if tags:
        chunks.extend(tag.lower() for tag in tags if tag)
    return chunks


def _token_set(chunks: list[str]) -> set[str]:
    tokens: set[str] = set()
    for chunk in chunks:
        tokens.update(WORD_RE.findall(chunk))
    return tokens


def detect_sport(title: str, category: str | None = None, tags: list[str] | None = None) -> str:
    chunks = _text_chunks(title, category, tags)
    joined = " ".join(chunks)
    tokens = _token_set(chunks)

    if "nba" in tokens or "basketball" in tokens:
        return "NBA"
    if any(chunk.startswith("nba-") for chunk in chunks):
        return "NBA"

    soccer_tokens = {"soccer", "football", "epl", "ucl", "uel", "laliga", "mls"}
    if tokens & soccer_tokens:
        return "SOCCER"
    if "premier league" in joined or "champions league" in joined or "europa league" in joined or "la liga" in joined:
        return "SOCCER"
    if any(chunk.startswith(prefix) for chunk in chunks for prefix in ("epl-", "ucl-", "uel-", "lal-", "laliga-")):
        return "SOCCER"

    return "UNKNOWN"


def detect_competition(sport: str, title: str, tags: list[str] | None = None, explicit: str | None = None) -> str | None:
    if explicit:
        normalized = explicit.upper().strip()
        if normalized == "NBA":
            return "NBA"
        if normalized in SUPPORTED_SOCCER_COMPETITIONS:
            return normalized

    if sport == "NBA":
        return "NBA"
    if sport != "SOCCER":
        return None

    chunks = _text_chunks(title, None, tags)
    joined = " ".join(chunks)
    tokens = _token_set(chunks)

    if "epl" in tokens or "premier league" in joined:
        return "EPL"
    if "ucl" in tokens or "champions league" in joined:
        return "UCL"
    if "uel" in tokens or "europa league" in joined:
        return "UEL"
    if "laliga" in tokens or "la liga" in joined or any(chunk.startswith("lal-") for chunk in chunks):
        return "LALIGA"

    # Fallback to configured keyword table.
    for keyword, competition in SOCCER_COMPETITION_KEYWORDS.items():
        pattern = rf"\b{re.escape(keyword)}\b"
        if re.search(pattern, joined):
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
