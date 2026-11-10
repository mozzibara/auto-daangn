#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail-closed, read-only Daangn regional search evidence gate (v4.4).

This module has no Playwright dependency and never performs network requests.
Different historical runs are analyzed independently: do not approve a current
sample merely because a weeks-old reference happens to match.

Statuses are observations about returned listing sets, never a guarantee of
real trading radius, completeness, authorization, or seller availability.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from urllib.parse import urlsplit, unquote

EXPECTED = {"sadang": "334", "cheonan": "2292", "asan": "2333"}
REGION_NAMES = {"sadang": "사당제3동", "cheonan": "불당동", "asan": "배방읍"}
# Exploratory, conservative thresholds. Crucially, NOT a fixed product count.
LOW_REPEAT_JACCARD = 0.80
HIGH_REPEAT_JACCARD = 0.98
CROSS_REGION_IDENTICAL_MIN = 20


def stable_article_id(url: str) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "www.daangn.com":
            return None
        path = unquote(parsed.path).rstrip("/")
        if not path.startswith("/kr/buy-sell/"):
            return None
        slug = path.rsplit("/", 1)[-1]
        # Most Daangn public listing URLs terminate in a 12-char ID.
        m = re.search(r"-([a-z0-9]{12})$", slug)
        return m.group(1) if m else None
    except (ValueError, UnicodeError):
        return None


def hashed_listing_ids(urls: list) -> list[str]:
    ids = [stable_article_id(x) for x in (urls or [])]
    return sorted({hashlib.sha256(x.encode("ascii")).hexdigest()[:24] for x in ids if x})


def set_hash(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(ids))).encode()).hexdigest()


def jaccard(left: list[str], right: list[str]) -> float | None:
    a, b = set(left or []), set(right or [])
    return round(len(a & b) / len(a | b), 6) if a or b else None


def _record(*, version, run, context, sequence, step, region, phase, urls, dom, verified,
            collector, region_hist=None, timestamp=None, previous_observed=None,
            expected_region_id=None):
    rid = str(expected_region_id) if expected_region_id is not None else EXPECTED.get(region)
    if not rid or not re.fullmatch(r'[0-9]{1,12}', rid):
        return None
    ids = hashed_listing_ids(urls)
    dom_ids = hashed_listing_ids(dom)
    valid = bool(verified and len(ids) >= 1 and dom_ids and set(dom_ids).issubset(set(ids)))
    return {
        "sample_id": f"{run}:{context}:{step}:{region}",
        "run": run, "version": str(version), "context": str(context),
        "sequence": str(sequence), "step": int(step),
        "region": region, "expected_region_id": rid,
        "phase": phase, "collector": collector, "timestamp_utc": timestamp,
        "valid": valid, "item_count": len(ids), "items": ids,
        "visible_count": len(dom_ids), "visible_coverage": round(len(set(dom_ids)&set(ids))/len(dom_ids),4) if dom_ids else None,
        "set_sha256": set_hash(ids), "area_top": dict(region_hist or {}),
        "client_state": previous_observed or {},
    }


def _infer_stage_verification(stage):
    reg = stage.get("target")
    rid = EXPECTED.get(reg)
    if not rid:
        return False
    ok = (bool(stage.get("verified")) and not stage.get("blocked") and
          stage.get("http_status") == 200 and stage.get("region_id") == rid and
          stage.get("loader_region_id") == rid and stage.get("loader_filter_region_id") == rid and
          not stage.get("errors"))
    doc = stage.get("document")
    if doc is not None:
        ok = bool(ok and doc.get("response_status") == 200 and doc.get("body_sha256"))
    return ok


def normalize(raw: dict, *, run_key: str | None = None) -> dict:
    """Adapt v4.1/4.2/4.3/4.3.1/4.3.2/4.4 raw results to one safe schema."""
    version = str(raw.get("version", ""))
    run = str(run_key or f"v{version.replace('.', '_')}")
    records = []
    if version == "4.1":
        for i, entry in enumerate(raw.get("url_tests", [])):
            key = entry.get("key")
            if key == "control":
                continue  # Implicit default region is not an independent regional control.
            after = entry.get("after") or {}
            region = key
            rid = EXPECTED.get(region)
            valid = (entry.get("http_status") == 200 and not entry.get("blocked") and
                     not entry.get("errors") and after.get("region_id_from_url") == rid and
                     after.get("initial_loader_region_id") == rid and
                     after.get("initial_loader_filter_region_id") == rid)
            sample = _record(version=version, run=run, context="v41_document", sequence="url_tests",
                  step=i+1, region=region, phase="url_document", urls=after.get("initial_loader_urls"),
                  dom=after.get("dom_visible"), verified=valid, collector="boot_loader",
                  timestamp=raw.get("timestamp_utc"))
            if sample: records.append(sample)
        for i, entry in enumerate(raw.get("ui_tests", [])):
            reg = {"사당": "sadang", "천안": "cheonan", "아산": "asan"}.get(entry.get("to"))
            check, fetch = entry.get("check") or {}, entry.get("fetch_json") or {}
            ok = (check.get("verified") is True and check.get("fetch_region_match") and
                  fetch.get("search_region_id") == EXPECTED.get(reg) and
                  fetch.get("filter_region_id") == EXPECTED.get(reg))
            sample = _record(version=version, run=run, context="v41_ui", sequence="ui_tests",
                  step=i+1, region=reg, phase="ui_fetch", urls=fetch.get("article_urls"),
                  dom=(entry.get("after") or {}).get("dom_visible"), verified=ok,
                  collector="spa_fetch", timestamp=raw.get("timestamp_utc"))
            if sample: records.append(sample)
    elif version == "4.2":
        for seq in raw.get("sequences", []):
            for i, st in enumerate(seq.get("stages", [])):
                region = {"사당": "sadang", "천안": "cheonan", "아산": "asan"}.get(st.get("to"), st.get("to"))
                fetch, after = st.get("fetch") or {}, st.get("after") or {}
                check = st.get("check") or {}
                ok = (st.get("stage_verified") and check.get("verified") and
                      fetch.get("search_region_id") == EXPECTED.get(region) and
                      fetch.get("filter_region_id") == EXPECTED.get(region))
                sample = _record(version=version, run=run, context=seq.get("key", ""),
                      sequence=seq.get("key", ""), step=i+1, region=region,
                      phase=("aba_initial" if i == 0 else "aba_return" if i == 2 else "aba_cross"),
                      urls=fetch.get("article_urls"), dom=after.get("dom_visible"),
                      verified=ok, collector="spa_fetch", region_hist=fetch.get("item_region_histogram"),
                      timestamp=st.get("measured_at_utc"))
                if sample: records.append(sample)
    elif version in {"4.3", "4.3.1", "4.3.2", "4.4"}:
        for seq in raw.get("trials", raw.get("plans", [])):
            key = seq.get("key", "unknown")
            kind = seq.get("kind", "four_phase")
            for i, st in enumerate(seq.get("stages", [])):
                phase = ("cold_first" if i == 0 else "same_url_repeat" if i == 1 else
                         "region_switch_first" if i == 2 else "switched_url_repeat")
                if kind == "aaa":
                    phase = "aaa_first" if i == 0 else "aaa_repeat"
                elif kind == "aba":
                    phase = "aba_initial" if i == 0 else "aba_cross" if i == 1 else "aba_return"
                ss = st.get("session_state") or {}
                sample = _record(version=version, run=run, context=key, sequence=key, step=i+1,
                      region=st.get("target"), phase=phase,
                      urls=st.get("loader_urls"), dom=st.get("dom_visible_urls"),
                      verified=_infer_stage_verification(st), collector="boot_loader",
                      region_hist=st.get("loader_area_top12") or st.get("region_histogram_top12"),
                      timestamp=st.get("timestamp_utc"), previous_observed={
                          "cookie_count_before": (ss.get("before") or {}).get("cookie_count"),
                          "cookie_count_after": (ss.get("after") or {}).get("cookie_count"),
                          "cookie_pair_sent": ((ss.get("main_document_cookie_headers") or {})
                                               .get("request_cookie_pair_count")),
                      } if ss else None)
                if sample: records.append(sample)
    else:
        raise ValueError(f"Unsupported version: {version!r}")
    return {"run": run, "version": version, "timestamp_utc": raw.get("timestamp_utc"),
            "keyword": raw.get("keyword"), "samples": records,
            "status": raw.get("status"), "total_samples": len(records)}


def weighted_histogram_jaccard(left: dict, right: dict) -> float | None:
    """Optional locality-distribution drift evidence; never an approval signal."""
    if not isinstance(left, dict) or not isinstance(right, dict) or not left or not right:
        return None
    names = set(left) | set(right)
    try:
        numerator = sum(min(int(left.get(x, 0)), int(right.get(x, 0))) for x in names)
        denominator = sum(max(int(left.get(x, 0)), int(right.get(x, 0))) for x in names)
        return round(numerator / denominator, 6) if denominator else None
    except (TypeError, ValueError):
        return None


def _is_cold(s: dict) -> bool:
    return s["phase"] in {"cold_first", "aaa_first", "aba_initial", "url_document"}


def _is_repeat(s: dict) -> bool:
    return s["phase"] in {"same_url_repeat", "switched_url_repeat", "aaa_repeat", "aba_return"}


def _is_cross_stage(s: dict) -> bool:
    return s["phase"] in {"region_switch_first", "aba_cross", "ui_fetch"}


def apply_gate(run_data: dict, *, repeat_floor=LOW_REPEAT_JACCARD,
               agreement_floor=HIGH_REPEAT_JACCARD, minimum_collision=CROSS_REGION_IDENTICAL_MIN) -> dict:
    """Conservative whole-run gate: isolate bad cold samples, never auto-promote them.

    A repeat can be LIMITED_ACCEPT only with ≥2 independent CONTEXTS matching
    within the same run + credible cross-region difference. No auto-promotion
    from prior runs, no geographic-coverage claim. Results are audit evidence.
    """
    samples = run_data.get("samples") or []
    by_context = defaultdict(list)
    for s in samples:
        by_context[s["context"]].append(s)
    for rows in by_context.values():
        rows.sort(key=lambda x: x["step"])

    # Cross-region identical first sets within one run are strong quarantining
    # evidence only if independent region IDs AND reasonably sized sets.
    by_cold_sha = defaultdict(list)
    for s in samples:
        if s["valid"] and _is_cold(s) and s["item_count"] >= minimum_collision:
            by_cold_sha[s["set_sha256"]].append(s)
    collisions = []
    collided = set()
    near_collided = set()
    for sha, rows in by_cold_sha.items():
        regions = {x["region"] for x in rows}
        if len(regions) >= 2:
            collided.update(x["sample_id"] for x in rows)
            collisions.append({"sha256": sha, "regions": sorted(regions),
                 "sample_ids": sorted(x["sample_id"] for x in rows),
                 "count": rows[0]["item_count"], "different_regions": len(regions)})

    # Near-duplicate first sets are independently suspicious. Do not confuse
    # strongly overlapping neighboring regions (~0.90 in earlier tests) with
    # near-identical (>0.98) fallback results.
    cold_valid = [s for s in samples if s["valid"] and _is_cold(s) and
                  s["item_count"] >= minimum_collision]
    near_collisions = []
    for i, left in enumerate(cold_valid):
        for right in cold_valid[i+1:]:
            if left["region"] == right["region"] or left["set_sha256"] == right["set_sha256"]:
                continue
            score = jaccard(left["items"], right["items"])
            if score is not None and score >= agreement_floor:
                near_collided.add(left["sample_id"])
                near_collided.add(right["sample_id"])
                near_collisions.append({"left":left["sample_id"], "right":right["sample_id"],
                    "jaccard":score, "regions":[left["region"],right["region"]]})
    same_context_pairs = []
    cold_outliers = set()
    for context, rows in by_context.items():
        for a, b in zip(rows, rows[1:]):
            if a["region"] != b["region"] or not a["valid"] or not b["valid"]:
                continue
            # Consecutive visit to same region (cold→repeat / switched→repeat).
            score = jaccard(a["items"], b["items"])
            same_context_pairs.append({"left": a["sample_id"], "right": b["sample_id"],
                  "region": a["region"], "jaccard": score,
                  "area_histogram_similarity": weighted_histogram_jaccard(a.get("area_top"), b.get("area_top"))})
            if score is not None and score < repeat_floor and _is_cold(a):
                cold_outliers.add(a["sample_id"])
            # First switch could be anomalous too; isolate rather than treat as trusted.
            if score is not None and score < repeat_floor and _is_cross_stage(a):
                cold_outliers.add(a["sample_id"])

    verified_repeats = [s for s in samples if s["valid"] and _is_repeat(s) and
                       s["sample_id"] not in collided and s["sample_id"] not in near_collided and
                       s["sample_id"] not in cold_outliers]
    corroboration = {}
    # Context-scoped independent replication within the SAME run only.
    for s in verified_repeats:
        peers = [p for p in verified_repeats if p["region"] == s["region"] and
                 p["context"] != s["context"]]
        best = max(((jaccard(s["items"], p["items"]), p) for p in peers),
                   key=lambda pair: pair[0] if pair[0] is not None else -1,
                   default=(None, None))
        corroboration[s["sample_id"]] = {"best_jaccard": best[0],
               "peer_sample_id": best[1]["sample_id"] if best[1] else None,
               "peer_context": best[1]["context"] if best[1] else None}

    decisions = []
    for s in samples:
        why = []
        corr = corroboration.get(s["sample_id"], {})
        if not s["valid"]:
            verdict = "QUARANTINED_INVALID_EVIDENCE"
            why.append("HTTP/region/loader/DOM validation missing or inconsistent")
        elif s["sample_id"] in collided:
            verdict = "QUARANTINED_CROSS_REGION_IDENTICAL_COLD_SET"
            why.append("Exact same cold listing set in different named regions")
        elif s["sample_id"] in near_collided:
            verdict = "QUARANTINED_CROSS_REGION_NEAR_DUPLICATE_COLD_SET"
            why.append("Near-identical initial listing sets were returned for different regions")
        elif s["sample_id"] in cold_outliers:
            verdict = "QUARANTINED_COLD_OR_SWITCH_OUTLIER"
            why.append("Immediate same-region repeat differs substantially")
        elif _is_cold(s):
            verdict = "UNVERIFIED_COLD_FIRST"
            why.append("First document cannot be promoted without independent regional checks")
        elif not _is_repeat(s):
            verdict = "UNVERIFIED_SINGLE_OBSERVATION"
            why.append("No independent repeat classification for this navigation")
        elif corr.get("best_jaccard") is None or corr["best_jaccard"] < agreement_floor:
            verdict = "UNVERIFIED_INDEPENDENT_CORROBORATION_MISSING"
            why.append("No same-region matching repeat from an independent browser context")
        else:
            # Check if any other region's repeated listing sets are nearly identical;
            # this prevents accepting a global identical fallback as a regional result.
            cross = [p for p in verified_repeats if p["region"] != s["region"]]
            best_cross = max((jaccard(s["items"], p["items"]) for p in cross), default=None)
            if best_cross is None:
                verdict = "UNVERIFIED_CROSS_REGION_CONTROL_MISSING"
                why.append("No different-region repeat control in this run")
            elif best_cross >= 0.98:
                verdict = "QUARANTINED_CROSS_REGION_REPEAT_COLLISION"
                why.append("Independently repeated listings also nearly identical across regions")
            else:
                verdict = "LIMITED_ACCEPT_REGIONAL_LISTING_SET"
                why.append("Matched independent same-region repeat; distinct cross-region repeat exists")
        decisions.append({"sample_id": s["sample_id"], "region": s["region"],
            "context": s["context"], "phase": s["phase"], "count": s["item_count"],
            "set_sha256": s["set_sha256"], "verdict": verdict,
            "allowed_for_price_analysis": verdict == "LIMITED_ACCEPT_REGIONAL_LISTING_SET",
            "verified_geographic_coverage": False, "verified_full_recall": False,
            "why": why, "independent_repeat": corr})
    tally = dict(sorted(Counter(x["verdict"] for x in decisions).items()))
    return {
        "version": "4.4", "run": run_data.get("run"),
        "input_version": run_data.get("version"), "total": len(decisions),
        "counts": tally, "collisions": collisions, "near_collisions": near_collisions,
        "same_context_pairs": same_context_pairs, "decisions": decisions,
        "thresholds": {"cold_repeat_floor": repeat_floor, "independent_agreement": agreement_floor,
                       "cross_region_collision_minimum_size": minimum_collision},
        "limitations": [
            "LIMITED_ACCEPT verifies only repeated query-output consistency and cross-region differentiation.",
            "No claim of nearby trading reach, listing completeness, consent, geographic causality, or seller status.",
            "Historical runs are descriptive and NEVER independently authorize live output.",
            "Never use an unverified/quarantined sample for downstream ranking.",
        ],
    }


def safe_compact_report(run: dict, gate: dict) -> dict:
    """Return a bounded representation with hashed public listing IDs, not full URLs."""
    lookup = {s["sample_id"]: s for s in run.get("samples", [])}
    return {"run": run.get("run"), "version": run.get("version"),
            "timestamp_utc": run.get("timestamp_utc"), "keyword": run.get("keyword"),
            "samples": [{k: v for k, v in s.items() if k != "items"}
                        for s in run.get("samples", [])],
            "gate": gate, "hash_method": "sha256(listing-public-id)[:24]"}
