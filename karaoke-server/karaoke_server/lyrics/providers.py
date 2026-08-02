"""Lyrics providers and candidate scoring.

Chain: LRCLIB (open API, no key) -> syncedlyrics aggregator (NetEase enabled
by default for Chinese coverage; scraping-based providers opt-in) -> manual
paste via the API.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx
from rapidfuzz import fuzz

from ..config import get_settings
from .language import detect_language, latin_ratio

log = logging.getLogger(__name__)

LRCLIB_BASE = "https://lrclib.net/api"
USER_AGENT = "karaoke-server/0.1 (https://github.com/boringfy/karaoke)"

# Reject candidates whose duration differs from the song by more than this.
MAX_DURATION_DELTA = 4.0


@dataclass
class Candidate:
    provider: str
    title: str | None = None
    artist: str | None = None
    provider_track_id: str | None = None
    duration_sec: float | None = None
    plain: str | None = None
    lrc: str | None = None
    score: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def is_synced(self) -> bool:
        return bool(self.lrc)

    @property
    def best_text(self) -> str:
        return self.plain or self.lrc or ""


def score_candidate(
    cand: Candidate,
    title: str,
    artist: str | None,
    duration_sec: float | None,
    expected_lang: str | None,
) -> float:
    """0..1 composite: fuzzy title/artist match + duration + synced bonus,
    with a penalty for romanized results on CJK songs."""
    title_score = fuzz.token_set_ratio((cand.title or ""), title) / 100.0
    artist_score = (
        fuzz.token_set_ratio((cand.artist or ""), artist) / 100.0 if artist else 0.6
    )
    dur_score = 0.5
    if duration_sec and cand.duration_sec:
        delta = abs(duration_sec - cand.duration_sec)
        if delta > MAX_DURATION_DELTA:
            cand.notes.append(f"duration off by {delta:.1f}s")
            return 0.0
        dur_score = 1.0 - delta / MAX_DURATION_DELTA

    score = 0.35 * title_score + 0.2 * artist_score + 0.3 * dur_score
    if cand.is_synced:
        score += 0.15

    text = cand.best_text
    if expected_lang in ("zh", "ja") and text and latin_ratio(text) > 0.8:
        cand.notes.append("looks romanized")
        score *= 0.4
    return round(min(score, 1.0), 4)


async def _lrclib_get(
    client: httpx.AsyncClient, title: str, artist: str | None, duration: float | None
) -> Candidate | None:
    """Exact-signature lookup; the fastest, most reliable path."""
    params = {"track_name": title, "artist_name": artist or ""}
    if duration:
        params["duration"] = str(round(duration))
    try:
        r = await client.get(f"{LRCLIB_BASE}/get", params=params)
    except httpx.HTTPError as e:
        log.warning("lrclib /get failed: %s", e)
        return None
    if r.status_code != 200:
        return None
    d = r.json()
    if d.get("instrumental"):
        return None
    return Candidate(
        provider="lrclib",
        provider_track_id=str(d.get("id")),
        title=d.get("trackName"),
        artist=d.get("artistName"),
        duration_sec=d.get("duration"),
        plain=d.get("plainLyrics") or None,
        lrc=d.get("syncedLyrics") or None,
    )


async def _lrclib_search(
    client: httpx.AsyncClient, title: str, artist: str | None
) -> list[Candidate]:
    params = {"track_name": title}
    if artist:
        params["artist_name"] = artist
    try:
        r = await client.get(f"{LRCLIB_BASE}/search", params=params)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("lrclib /search failed: %s", e)
        return []
    out = []
    for d in r.json()[:10]:
        if d.get("instrumental"):
            continue
        out.append(
            Candidate(
                provider="lrclib",
                provider_track_id=str(d.get("id")),
                title=d.get("trackName"),
                artist=d.get("artistName"),
                duration_sec=d.get("duration"),
                plain=d.get("plainLyrics") or None,
                lrc=d.get("syncedLyrics") or None,
            )
        )
    return out


def _syncedlyrics_search(title: str, artist: str | None, allow_scraping: bool) -> Candidate | None:
    """Fallback aggregator (sync, run in a thread). NetEase gives the best
    Chinese coverage; Musixmatch/Genius are scraping-based and opt-in."""
    import syncedlyrics  # local import: optional-ish, slow to import

    providers = ["NetEase"]
    if allow_scraping:
        providers = ["NetEase", "Musixmatch", "Lrclib", "Genius"]
    term = f"{title} {artist}" if artist else title
    try:
        lrc = syncedlyrics.search(term, providers=providers)
    except Exception as e:  # noqa: BLE001 - third-party scrapers raise anything
        log.warning("syncedlyrics failed: %s", e)
        return None
    if not lrc:
        return None
    synced = "[" in lrc and "]" in lrc
    return Candidate(
        provider="syncedlyrics",
        title=title,
        artist=artist,
        lrc=lrc if synced else None,
        plain=None if synced else lrc,
    )


async def fetch_candidates(
    title: str,
    artist: str | None,
    duration_sec: float | None,
    expected_lang: str | None = None,
) -> list[Candidate]:
    """Query all providers, score, and return the top candidates (best first)."""
    settings = get_settings()
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(headers=headers, timeout=15) as client:
        exact, searched = await asyncio.gather(
            _lrclib_get(client, title, artist, duration_sec),
            _lrclib_search(client, title, artist),
        )
    candidates: list[Candidate] = [c for c in [exact, *searched] if c]

    # Dedupe by provider track id.
    seen: set[str] = set()
    deduped = []
    for c in candidates:
        key = f"{c.provider}:{c.provider_track_id}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    for c in deduped:
        c.score = score_candidate(c, title, artist, duration_sec, expected_lang)
    deduped = [c for c in deduped if c.score > 0]
    deduped.sort(key=lambda c: c.score, reverse=True)

    if not deduped:
        fallback = await asyncio.to_thread(
            _syncedlyrics_search, title, artist, settings.enable_scraping_providers
        )
        if fallback:
            fallback.score = score_candidate(
                fallback, title, artist, duration_sec, expected_lang
            )
            deduped = [fallback]

    return deduped[: settings.lyrics_search_limit]


def candidate_language(cand: Candidate) -> str:
    return detect_language(cand.best_text)
