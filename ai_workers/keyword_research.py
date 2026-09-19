"""Keyword demand vs. competition, via NCP NAVER API HUB.

`seo_optimizer` decides which brand keywords a post should carry, but it
picks them from the draft alone — it can tell that a post is *about* 가발
without knowing whether 가발 is a term anyone searches for, or one that
millions of existing blog posts are already fighting over. This module
supplies the missing half.

Two signals, both from API HUB on one key:

  demand      — 검색어트렌드 ratio. Relative, not absolute: a request
                normalizes its groups so the busiest scores 100.
  competition — 블로그 검색 `total`, the number of posts already ranking
                for the term.

The ranking is therefore *ordinal*: it says 'A is a better bet than B for
this brand', never 'A gets N searches a month'. Absolute volume needs the
검색광고 API (광고주센터), which is a different vendor, a different key and
an HMAC-signed protocol; `estimated_volume` is left as the seam for it.

Unlike the LLM calls in this package, every request here is billed against a
monthly quota, so nothing calls the network directly — see `_request`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import math
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

import requests

from core import repo
from core.crypto_utils import decrypt_api_key

BASE_URL = "https://naverapihub.apigw.ntruss.com"
BLOG_PATH = "/search/v1/blog"
TREND_PATH = "/search-trend/v1/search"

# 검색광고 API — a different host, vendor and auth scheme from API HUB above.
SEARCHAD_URL = "https://api.searchad.naver.com"
KEYWORDSTOOL_PATH = "/keywordstool"

# 검색광고 accepts at most 5 seed keywords per /keywordstool request.
HINT_KEYWORD_LIMIT = 5

# 검색어트렌드 accepts at most 5 keyword groups per request.
TREND_GROUP_LIMIT = 5

# A blog corpus in the millions moves by fractions of a percent per day, and
# search interest by month, so both tolerate a long cache. These numbers are
# the main lever on quota spend — shorten them only with a reason.
#
# Both were shorter (7 and 14) and had to match the operating rhythm instead.
# The Settings screen tells the marketer to run the diagnosis monthly and the
# sweep quarterly, but competition expired after a week — and expiry is not
# inert: `seo_optimizer._opportunity` returns 0 for an unmeasured keyword, so
# target selection silently reverted to "whichever keyword the draft repeated
# most" for three weeks out of every four. The conversion weights were off
# most of the time they were supposed to be working.
#
# 30 days is the documented cadence. A blog document count that drifts 1~2%
# in that window changes no ranking decision; a scoring system that switches
# itself off changes every one of them.
DOCUMENT_CACHE_DAYS = 30
DEMAND_CACHE_DAYS = 3
# Monthly volume is a monthly aggregate; re-asking daily cannot change it.
VOLUME_CACHE_DAYS = 30

_TIMEOUT = 10


class NaverApiError(RuntimeError):
    """Raised for anything the caller must act on: no key, quota, auth, HTTP."""


class QuotaExceeded(NaverApiError):
    """The locally configured daily cap was reached — no request was sent."""


# --- credentials ------------------------------------------------------------

def _credentials() -> tuple[str, str]:
    saved = repo.get_naver_api_settings()
    if not saved:
        raise NaverApiError("네이버 API HUB 키가 등록되지 않았습니다. 설정 화면에서 먼저 등록하세요.")
    return (
        decrypt_api_key(saved["encrypted_client_id"]),
        decrypt_api_key(saved["encrypted_client_secret"]),
    )


def _daily_cap() -> int:
    saved = repo.get_naver_api_settings()
    return int((saved or {}).get("daily_call_cap") or 0)


def remaining_calls_today() -> int:
    cap = _daily_cap()
    return max(cap - repo.naver_calls_today(), 0) if cap else 0


# --- transport --------------------------------------------------------------

def _request(path: str, *, params=None, json_body=None, client=None) -> dict:
    """The only place that reaches the network.

    The cap is checked *before* sending and every attempt is logged after,
    including failures: a 4xx still consumed a request as far as the gateway
    is concerned, so not counting it would let a broken loop run past the
    ceiling the cap exists to enforce.
    """
    cap = _daily_cap()
    if cap and repo.naver_calls_today() >= cap:
        raise QuotaExceeded(
            f"오늘 호출이 상한({cap}회)에 도달했습니다. 설정에서 상한을 올리거나 내일 다시 시도하세요."
        )

    client_id, client_secret = client or _credentials()
    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
    }
    try:
        if json_body is None:
            resp = requests.get(BASE_URL + path, headers=headers, params=params, timeout=_TIMEOUT)
        else:
            headers["Content-Type"] = "application/json"
            resp = requests.post(BASE_URL + path, headers=headers, json=json_body, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        repo.log_naver_call(path, ok=False)
        raise NaverApiError(f"네트워크 오류: {exc}") from exc

    repo.log_naver_call(path, ok=resp.ok)
    if not resp.ok:
        raise NaverApiError(_explain(resp))
    return resp.json()


def _explain(resp) -> str:
    """API HUB's own message, translated where it names a fixable setup step."""
    try:
        payload = resp.json().get("error", {})
        detail = payload.get("details") or payload.get("message") or ""
    except ValueError:
        detail = resp.text[:200]

    if "subscription" in detail.lower():
        return "구독이 필요합니다. NCP 콘솔 > NAVER API HUB > Subscription에서 이용 신청하세요."
    if "활성화되어 있지 않" in detail:
        return "이 Application에 해당 API가 추가되지 않았습니다. 콘솔에서 [Application 수정] > API 선택."
    if resp.status_code == 429:
        return "네이버 쪽 호출 한도를 초과했습니다 (429)."
    return f"HTTP {resp.status_code}: {detail or '알 수 없는 오류'}"


# --- competition: blog document count ---------------------------------------

def blog_document_count(keyword: str, *, use_cache: bool = True) -> int:
    """How many blog posts already exist for `keyword`. Higher = harder to rank."""
    keyword = keyword.strip()
    if not keyword:
        return 0

    if use_cache:
        hit = repo.get_cached_metric(keyword, "blog_total", DOCUMENT_CACHE_DAYS)
        if hit is not None:
            return int(hit)

    # display=1 because only `total` is wanted; the gateway bills per request,
    # not per result, but a smaller body is a faster response.
    payload = _request(BLOG_PATH, params={"query": keyword, "display": 1})
    total = int(payload.get("total", 0))
    repo.put_cached_metric(keyword, "blog_total", str(total))
    return total


# --- demand: search trend ---------------------------------------------------

def _trend_window() -> tuple[str, str]:
    """The last ~90 days, which is recent enough to reflect current interest
    while still smoothing the week-to-week noise a 30-day window shows."""
    today = date.today()
    return (today - timedelta(days=90)).isoformat(), today.isoformat()


def _trend_batch(keywords: List[str], client) -> Dict[str, float]:
    start, end = _trend_window()
    payload = _request(
        TREND_PATH,
        json_body={
            "startDate": start,
            "endDate": end,
            "timeUnit": "month",
            "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords],
        },
        client=client,
    )
    out: Dict[str, float] = {}
    for result in payload.get("results", []):
        points = result.get("data") or []
        # The mean over the window, not the last point: a single quiet month
        # shouldn't demote a keyword that is otherwise consistently searched.
        out[result.get("title", "")] = (
            sum(p.get("ratio", 0) for p in points) / len(points) if points else 0.0
        )
    return out


def search_demand(keywords: List[str], *, use_cache: bool = True) -> Dict[str, float]:
    """Relative search interest per keyword, comparable across the whole list.

    The trend API normalizes each *request* to 100, so two batches are not
    directly comparable — the 5th-ranked keyword of a strong batch would
    outrank the top of a weak one. To make one scale out of many requests,
    the first keyword rides along in every batch as an anchor and each batch
    is rescaled by what the anchor scored in it.
    """
    keywords = [k.strip() for k in keywords if k and k.strip()]
    if not keywords:
        return {}

    cached, pending = {}, []
    for kw in keywords:
        hit = repo.get_cached_metric(kw, "trend_ratio", DEMAND_CACHE_DAYS) if use_cache else None
        (cached.__setitem__(kw, float(hit)) if hit is not None else pending.append(kw))
    if not pending:
        return cached

    client = _credentials()
    if len(pending) <= TREND_GROUP_LIMIT:
        fetched = _trend_batch(pending, client)
    else:
        anchor, rest = pending[0], pending[1:]
        fetched = {}
        anchor_scale: Optional[float] = None
        for i in range(0, len(rest), TREND_GROUP_LIMIT - 1):
            batch = [anchor] + rest[i:i + TREND_GROUP_LIMIT - 1]
            scores = _trend_batch(batch, client)
            anchor_score = scores.get(anchor, 0.0)
            if anchor_scale is None:
                anchor_scale = anchor_score
            # An anchor of 0 means it was unsearched relative to this batch,
            # leaving no common reference — the batch is kept unscaled rather
            # than dropped, which is wrong in degree but not in order.
            factor = (anchor_scale / anchor_score) if anchor_score and anchor_scale else 1.0
            for kw, score in scores.items():
                if kw != anchor or anchor not in fetched:
                    fetched[kw] = score * (1.0 if kw == anchor else factor)

    for kw, score in fetched.items():
        repo.put_cached_metric(kw, "trend_ratio", str(score))
    return {**cached, **fetched}


# --- absolute volume: 검색광고 API ------------------------------------------

def _searchad_credentials() -> tuple[str, str, str]:
    saved = repo.get_searchad_settings()
    if not saved:
        raise NaverApiError("검색광고 API 키가 등록되지 않았습니다. 설정 화면에서 먼저 등록하세요.")
    return (
        decrypt_api_key(saved["encrypted_customer_id"]),
        decrypt_api_key(saved["encrypted_api_key"]),
        decrypt_api_key(saved["encrypted_secret_key"]),
    )


def _searchad_request(path: str, params: dict, client=None) -> dict:
    """Signed GET against 검색광고.

    Every request carries an HMAC-SHA256 of `timestamp.METHOD.path` — note
    the path *without* its query string, which is the detail that silently
    produces 401s if the params are included.

    No daily cap is applied here: this API is free, so throttling it would
    only slow the app down without saving anything.
    """
    customer_id, api_key, secret_key = client or _searchad_credentials()
    timestamp = str(round(time.time() * 1000))
    signature = base64.b64encode(
        hmac.new(secret_key.encode(), f"{timestamp}.GET.{path}".encode(), hashlib.sha256).digest()
    ).decode()

    try:
        resp = requests.get(
            SEARCHAD_URL + path,
            params=params,
            headers={
                "X-Timestamp": timestamp,
                "X-API-KEY": api_key,
                "X-Customer": customer_id,
                "X-Signature": signature,
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise NaverApiError(f"네트워크 오류: {exc}") from exc

    if resp.status_code == 401:
        raise NaverApiError("인증 실패 — CUSTOMER_ID / 액세스라이선스 / 비밀키를 확인하세요.")
    if not resp.ok:
        raise NaverApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def normalize(keyword: str) -> str:
    """The form 검색광고 echoes a keyword back in — spaces stripped, latin
    upper-cased. Volume cache reads must use it or every keyword containing a
    space misses the entry that was just written under Naver's spelling and
    pays for a fresh request. Blog document counts are unaffected: those are
    cached under whatever was searched, because that is what was searched.
    """
    return keyword.replace(" ", "").upper()


def _parse_count(raw) -> int:
    """`monthlyPcQcCnt` is an int, except when it is the string '< 10'.

    Naver masks anything under ten rather than reporting it, so the true
    value is somewhere in 0..9 — the midpoint keeps such a keyword ranked
    below every measured one without collapsing it to the same 0 as a
    keyword that genuinely returned no data.
    """
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    return 5 if text.startswith("<") else (int(text) if text.isdigit() else 0)


def _keywordstool(hints: List[str], client=None) -> List[dict]:
    payload = _searchad_request(
        KEYWORDSTOOL_PATH,
        # Naver matches hints ignoring spaces; sending them unstripped
        # returns rows keyed differently from what was asked for.
        {"hintKeywords": ",".join(k.replace(" ", "") for k in hints), "showDetail": "1"},
        client=client,
    )
    rows = []
    for item in payload.get("keywordList", []):
        pc = _parse_count(item.get("monthlyPcQcCnt"))
        mobile = _parse_count(item.get("monthlyMobileQcCnt"))
        rows.append(
            {
                "keyword": item.get("relKeyword", ""),
                "pc": pc,
                "mobile": mobile,
                "volume": pc + mobile,
                "competition": item.get("compIdx", ""),
            }
        )
    return rows


def keyword_volumes(keywords: List[str], *, use_cache: bool = True) -> Dict[str, int]:
    """Absolute monthly searches (PC + mobile) per keyword.

    /keywordstool answers with the seeds *and* hundreds of related terms, so
    every lookup is also a free discovery pass — the extras are cached here
    even though this call didn't ask for them, which is why a second keyword
    from the same niche usually costs no request at all.
    """
    wanted = [k.strip() for k in keywords if k and k.strip()]
    if not wanted:
        return {}

    found, pending = {}, []
    for kw in wanted:
        hit = repo.get_cached_metric(normalize(kw), "ad_volume", VOLUME_CACHE_DAYS) if use_cache else None
        (found.__setitem__(kw, int(hit)) if hit is not None else pending.append(kw))
    if not pending:
        return found

    client = _searchad_credentials()
    for i in range(0, len(pending), HINT_KEYWORD_LIMIT):
        for row in _keywordstool(pending[i:i + HINT_KEYWORD_LIMIT], client):
            repo.put_cached_metric(row["keyword"], "ad_volume", str(row["volume"]))

    for kw in pending:
        hit = repo.get_cached_metric(normalize(kw), "ad_volume", VOLUME_CACHE_DAYS)
        found[kw] = int(hit) if hit is not None else 0
    return found


def discover_keywords(seeds: List[str]) -> List[dict]:
    """Related keywords the brand hasn't thought of, busiest first.

    This is the half of the ad API that API HUB cannot replace: it answers
    'what else are people typing?', not just 'how busy is the term I already
    had'. Deliberately not filtered against the brand's existing pool — a
    seed reappearing at the top is a useful confirmation, not noise.

    Returns everything Naver sends, unfiltered. A volume floor belongs to the
    caller: applying one here would make an empty result ambiguous between
    'this seed has no related searches' and 'the floor was set too high',
    which is exactly the distinction someone staring at a blank table needs.
    """
    seeds = [k.strip() for k in seeds if k and k.strip()][:HINT_KEYWORD_LIMIT]
    if not seeds:
        return []
    rows = _keywordstool(seeds)
    for row in rows:
        repo.put_cached_metric(row["keyword"], "ad_volume", str(row["volume"]))
    return sorted(rows, key=lambda r: r["volume"], reverse=True)


# --- scoring ----------------------------------------------------------------

def golden_score(demand: float, documents: int) -> float:
    """Demand per unit of competition.

    Document counts span several orders of magnitude (a niche term has
    thousands, a head term has millions), so dividing by the raw count would let the
    denominator swamp every other consideration and rank the list by
    obscurity alone. log10 compresses it back to a comparable range, which is
    the same reason keyword tools quote 'competition' on a log-ish scale.
    """
    return demand / math.log10(max(documents, 10))


def rank_keywords(
    keywords: List[str], *, use_cache: bool = True, include_trend: bool = True
) -> List[dict]:
    """Brand keywords ordered by how winnable they look, best first.

    Scores on absolute monthly volume when the 검색광고 key is registered and
    falls back to the trend ratio when it isn't. The two are not
    interchangeable — one is searches per month, the other a 0-100 figure
    relative to the rest of the list — so `basis` records which was used
    rather than letting a caller compare scores across the two modes.

    `include_trend=False` skips the metered trend request, which is what a
    large sweep wants: trend adds seasonality colour that absolute volume
    already outranks for scoring, and at one request per four keywords it is
    the difference between a 40-keyword sweep costing 40 calls and 50.
    """
    keywords = [k.strip() for k in keywords if k and k.strip()]
    if not keywords:
        return []

    demand = search_demand(keywords, use_cache=use_cache) if include_trend else {}
    try:
        volumes = keyword_volumes(keywords, use_cache=use_cache)
    except NaverApiError:
        volumes = {}  # key not registered yet — trend ratio still ranks the list

    rows = []
    for kw in keywords:
        documents = blog_document_count(kw, use_cache=use_cache)
        volume = volumes.get(kw)
        basis = float(volume) if volume else demand.get(kw, 0.0)
        rows.append(
            {
                "keyword": kw,
                "demand": round(demand.get(kw, 0.0), 2),
                "documents": documents,
                "estimated_volume": volume,
                "basis": "volume" if volume else "trend",
                "score": round(golden_score(basis, documents), 3),
            }
        )
    return sorted(rows, key=lambda r: r["score"], reverse=True)


# --- opportunity sweep ------------------------------------------------------

# The floor is a real limit: a keyword nobody searches ranks first for nobody.
#
# The ceiling is not the same kind of thing. It was originally set low on the
# theory that high volume implies unwinnable competition — but competition is
# measured directly one step later, so guessing at it here only hides the
# candidates worth measuring. At 5,000 it cut 결혼답례품 (18,510 searches
# against 11 competing posts per search) while keeping terms three times more
# crowded. It now sits high enough to exclude only true head terms, and the
# document-per-search ratio does the real filtering.
DEFAULT_MIN_VOLUME = 200
DEFAULT_MAX_VOLUME = 30_000


def pool_freshness(keywords: List[str]) -> dict:
    """Whether the numbers behind keyword targeting are still alive.

    `seo_optimizer._opportunity` reads competition from cache and returns 0
    the moment it expires, which silently reverts target selection to "which
    keyword did the draft happen to repeat most" — the exact behaviour the
    conversion weights were introduced to replace. Nothing in the app said so.
    The Settings screen reported "캐시된 키워드 7,967 · 재조회 시 호출 0" as a
    plain win while the 16 numbers that actually matter were days from
    expiring.

    Only the pool is checked. A sweep measures hundreds of candidates, but
    generation reads none of them: a stale 간호사릴홀더 costs nothing, a stale
    결혼답례품 turns the weights off.
    """
    rows = []
    for kw in keywords:
        rows.append({
            "keyword": kw,
            "volume_age": repo.cached_metric_age_days(normalize(kw), "ad_volume"),
            "document_age": repo.cached_metric_age_days(kw, "blog_total"),
        })

    def expired(row) -> bool:
        return (
            row["volume_age"] is None or row["volume_age"] > VOLUME_CACHE_DAYS
            or row["document_age"] is None or row["document_age"] > DOCUMENT_CACHE_DAYS
        )

    stale = [r["keyword"] for r in rows if expired(r)]
    ages = [r["document_age"] for r in rows if r["document_age"] is not None]
    oldest = max(ages) if ages else None
    return {
        "rows": rows,
        "stale": stale,
        "measured": len(ages),
        "total": len(keywords),
        "oldest_document_age": oldest,
        # 가장 최근 측정. "언제 마지막으로 손봤더라"에 답하기 위한 값이라
        # 별도 기록 테이블을 두지 않고 캐시에서 그대로 읽습니다.
        "newest_document_age": min(ages) if ages else None,
        # 가장 오래된 항목이 만료되기까지 남은 일수. 음수면 이미 만료됐습니다.
        "days_left": (DOCUMENT_CACHE_DAYS - oldest) if oldest is not None else None,
    }


def pool_refresh_cost(keywords: List[str]) -> int:
    """Metered requests `refresh_pool` would actually spend.

    Only the blog document count is metered; 검색광고 volume is free. So the
    bill is the number of keywords whose competition has expired or was never
    measured, which is usually far fewer than the pool.
    """
    return sum(
        1 for kw in keywords
        if repo.get_cached_metric(kw, "blog_total", DOCUMENT_CACHE_DAYS) is None
    )


def refresh_pool(keywords: List[str], *, force: bool = False) -> dict:
    """Bring the pool's numbers back to life. Metered, one request per
    keyword that actually needs one.

    Deliberately not automatic. Generation must never make a metered call
    (see `seo_optimizer._opportunity`), and a background refresher would spend
    the daily quota on a schedule nobody is watching. This is the button that
    the freshness warning points at.

    `force` re-buys everything including what is still fresh. It defaults off
    because the first version did the opposite: it always passed
    use_cache=False, so a button labelled "3회 호출" for three expired
    keywords quietly spent sixteen. A paid action has to cost what the screen
    says it costs.
    """
    billed = len(keywords) if force else pool_refresh_cost(keywords)
    ranked = rank_keywords(keywords, use_cache=not force, include_trend=False)
    return {"refreshed": len(ranked), "billed": billed, "rows": ranked}


def sweep_candidates(
    seeds: List[str], *, min_volume: int = DEFAULT_MIN_VOLUME, max_volume: int = DEFAULT_MAX_VOLUME
) -> List[dict]:
    """Free half of the sweep: everything in the winnable volume band.

    Split from `score_candidates` on purpose. Discovery is free and returns
    hundreds of rows; scoring costs one metered request per row. Handing the
    candidate list back first lets the caller see the bill before agreeing
    to it.
    """
    return [r for r in discover_keywords(seeds) if min_volume <= r["volume"] <= max_volume]


def score_candidates(candidates: List[dict], *, limit: int = 40, use_cache: bool = True) -> List[dict]:
    """Metered half: add competition to `sweep_candidates` output and rank.

    Costs one blog-search request per uncached candidate, so `limit` is the
    real cost control — it caps the bill regardless of how wide the seed net
    was thrown.
    """
    keywords = [r["keyword"] for r in candidates[:limit]]
    return rank_keywords(keywords, use_cache=use_cache, include_trend=False)


def estimate_sweep_cost(candidates: List[dict], *, limit: int = 40) -> int:
    """Metered requests `score_candidates` would spend, after cache hits."""
    return sum(
        1
        for row in candidates[:limit]
        if repo.get_cached_metric(row["keyword"], "blog_total", DOCUMENT_CACHE_DAYS) is None
    )


# --- settings UI support ----------------------------------------------------

def test_connection(client_id: str, client_secret: str) -> tuple[bool, str]:
    """One blog-search call, used by the settings screen to validate a key."""
    try:
        payload = _request(
            BLOG_PATH, params={"query": "가발", "display": 1}, client=(client_id, client_secret)
        )
    except NaverApiError as exc:
        return False, str(exc)
    return True, f"연결 성공 — 블로그 검색 정상 (테스트 결과 {payload.get('total', 0):,}건)"


def test_searchad_connection(customer_id: str, api_key: str, secret_key: str) -> tuple[bool, str]:
    """One /keywordstool call, used by the settings screen to validate a key."""
    try:
        rows = _keywordstool(["가발"], client=(customer_id, api_key, secret_key))
    except NaverApiError as exc:
        return False, str(exc)
    return True, f"연결 성공 — 연관키워드 {len(rows)}개, 검색량 조회 정상"
