from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from normalization.canonical import VenueMarket, deterministic_event_id
from normalization.fuzzy import token_set_similarity
from normalization.soccer_competitions import SUPPORTED_SOCCER_COMPETITIONS


@dataclass(slots=True)
class ResolvedPair:
    event_id: str
    sport: str
    competition: str | None
    start_time_utc: datetime
    home_team: str
    away_team: str
    title_canonical: str
    poly: VenueMarket
    kalshi: VenueMarket
    status: str
    confidence: float
    evidence_json: str


def load_overrides(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}

    overrides: dict[tuple[str, str], dict[str, Any]] = {}
    for row in payload.get("overrides", []):
        poly = str(row.get("poly_market_id") or row.get("poly") or "").strip()
        kalshi = str(row.get("kalshi_market_id") or row.get("kalshi") or "").strip()
        if not poly or not kalshi:
            continue
        overrides[(poly, kalshi)] = {
            "status": row.get("status", "OVERRIDE"),
            "confidence": float(row.get("confidence", 1.0)),
            "notes": row.get("notes", ""),
        }
    return overrides


def _team_similarity(poly: VenueMarket, kalshi: VenueMarket) -> tuple[float, bool]:
    if not all([poly.home_team, poly.away_team, kalshi.home_team, kalshi.away_team]):
        return 0.0, False

    aligned = 0.5 * (
        token_set_similarity(poly.home_team or "", kalshi.home_team or "")
        + token_set_similarity(poly.away_team or "", kalshi.away_team or "")
    )
    flipped = 0.5 * (
        token_set_similarity(poly.home_team or "", kalshi.away_team or "")
        + token_set_similarity(poly.away_team or "", kalshi.home_team or "")
    )

    is_flipped = flipped > aligned + 0.05
    return max(aligned, flipped), is_flipped


def _time_score(poly: VenueMarket, kalshi: VenueMarket) -> float:
    if not poly.start_time_utc or not kalshi.start_time_utc:
        return 0.0
    delta_hours = abs((poly.start_time_utc - kalshi.start_time_utc).total_seconds()) / 3600.0
    max_window = 6.0 if poly.sport == "NBA" else 12.0
    return max(0.0, 1.0 - (delta_hours / max_window))


def _title_score(poly: VenueMarket, kalshi: VenueMarket) -> float:
    return token_set_similarity(poly.title, kalshi.title)


def _within_time_window(poly: VenueMarket, kalshi: VenueMarket) -> bool:
    if not poly.start_time_utc or not kalshi.start_time_utc:
        return True
    delta_hours = abs((poly.start_time_utc - kalshi.start_time_utc).total_seconds()) / 3600.0
    limit = 6.0 if poly.sport == "NBA" else 12.0
    return delta_hours <= limit


def _is_supported_competition(market: VenueMarket) -> bool:
    if market.sport == "NBA":
        return market.competition == "NBA"
    if market.sport == "SOCCER":
        return market.competition in SUPPORTED_SOCCER_COMPETITIONS
    return False


def _decision(
    score: float,
    poly: VenueMarket,
    kalshi: VenueMarket,
    orientation_flipped: bool,
    override: dict[str, Any] | None,
) -> str:
    if override:
        return str(override.get("status", "OVERRIDE"))

    if poly.market_type == "WINNER_3WAY" or kalshi.market_type == "WINNER_3WAY":
        return "REVIEW"

    if poly.market_type != "WINNER_BINARY" or kalshi.market_type != "WINNER_BINARY":
        return "REVIEW"

    if orientation_flipped:
        return "REVIEW"

    if poly.start_time_utc is None or kalshi.start_time_utc is None:
        return "REVIEW"

    if score >= 0.86:
        return "AUTO"
    if score >= 0.80:
        return "REVIEW"
    return "REJECTED"


def resolve_markets(
    polymarket_markets: list[VenueMarket],
    kalshi_markets: list[VenueMarket],
    *,
    overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> list[ResolvedPair]:
    overrides = overrides or {}

    now = datetime.now(timezone.utc)
    pairs: list[ResolvedPair] = []

    for poly in polymarket_markets:
        if poly.sport not in {"NBA", "SOCCER"}:
            continue
        if not _is_supported_competition(poly):
            continue

        candidate_rows: list[tuple[float, VenueMarket, bool, dict[str, float]]] = []
        for kalshi in kalshi_markets:
            if poly.sport != kalshi.sport:
                continue
            if not _is_supported_competition(kalshi):
                continue
            if poly.sport == "SOCCER" and poly.competition != kalshi.competition:
                continue
            if not _within_time_window(poly, kalshi):
                continue

            team_score, orientation_flipped = _team_similarity(poly, kalshi)
            time_score = _time_score(poly, kalshi)
            title_score = _title_score(poly, kalshi)

            total_score = 0.5 * team_score + 0.3 * time_score + 0.2 * title_score
            candidate_rows.append(
                (
                    total_score,
                    kalshi,
                    orientation_flipped,
                    {
                        "team": round(team_score, 4),
                        "time": round(time_score, 4),
                        "title": round(title_score, 4),
                    },
                )
            )

        if not candidate_rows:
            continue

        best_score, best_kalshi, orientation_flipped, score_details = max(candidate_rows, key=lambda row: row[0])

        if poly.start_time_utc and best_kalshi.start_time_utc:
            start_time = poly.start_time_utc if poly.start_time_utc <= best_kalshi.start_time_utc else best_kalshi.start_time_utc
        else:
            start_time = poly.start_time_utc or best_kalshi.start_time_utc or now

        home_team = poly.home_team or best_kalshi.home_team or "unknown-home"
        away_team = poly.away_team or best_kalshi.away_team or "unknown-away"
        event_id = deterministic_event_id(
            sport=poly.sport,
            competition=poly.competition,
            start_time_utc=start_time,
            home_team=home_team,
            away_team=away_team,
        )

        override = overrides.get((poly.venue_market_id, best_kalshi.venue_market_id))
        decision = _decision(best_score, poly, best_kalshi, orientation_flipped, override)
        confidence = float(override.get("confidence", best_score)) if override else best_score

        evidence = {
            "poly_title": poly.title,
            "kalshi_title": best_kalshi.title,
            "poly_start": poly.start_time_utc.isoformat() if poly.start_time_utc else None,
            "kalshi_start": best_kalshi.start_time_utc.isoformat() if best_kalshi.start_time_utc else None,
            "score": round(best_score, 4),
            "score_parts": score_details,
            "orientation_flipped": orientation_flipped,
            "override": override,
            "unsupported_reason": (
                "WINNER_3WAY currently unsupported"
                if poly.market_type == "WINNER_3WAY" or best_kalshi.market_type == "WINNER_3WAY"
                else None
            ),
        }

        pairs.append(
            ResolvedPair(
                event_id=event_id,
                sport=poly.sport,
                competition=poly.competition,
                start_time_utc=start_time,
                home_team=home_team,
                away_team=away_team,
                title_canonical=f"{home_team} vs {away_team}",
                poly=poly,
                kalshi=best_kalshi,
                status=decision,
                confidence=round(float(confidence), 4),
                evidence_json=json.dumps(evidence),
            )
        )

    return pairs
