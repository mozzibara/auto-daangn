#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daangn v4.4: bounded public read-only regional search quarantine gate.

Use --mode audit for packaged historical evidence, or --mode live for three
fresh anonymous Chromium contexts with four full-document navigations each.
No credentials, authorization bypass, cookie injection, cache busting, endless
retry, or background monitoring. Not a geographic coverage attestation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import daangn_browser_v4_3_2 as legacy
import daangn_v4_1_core as core
import daangn_v4_4_gate as gate

VERSION = "4.4"
ROOT = Path(__file__).resolve().parent


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def gate_with_known(run: dict, known_bad: set[str]) -> dict:
    result = gate.apply_gate(run)
    for decision in result["decisions"]:
        if decision["set_sha256"] in known_bad and decision["count"] >= 20:
            decision["verdict"] = "QUARANTINED_HISTORICAL_CROSS_REGION_SIGNATURE"
            decision["allowed_for_price_analysis"] = False
            decision["why"].append("Fingerprint matches a historical same-set/different-region cold collision")
    result["counts"] = dict(sorted(Counter(d["verdict"] for d in result["decisions"]).items()))
    result["historical_signatures_checked"] = len(known_bad)
    return result


def evidence_reference(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or not isinstance(obj.get("runs"), list):
        raise ValueError("Reference evidence file is malformed")
    return obj["runs"]


def historical_collision_signatures(runs: list[dict]) -> set[str]:
    signatures = set()
    for run in runs:
        findings = gate.apply_gate(run)
        signatures.update(x["sha256"] for x in findings["collisions"])
    return signatures


def report_for_run(data: dict, compact: dict) -> str:
    outcome = compact["gate"]
    lines = [
        "# 당근 v4.4 지역별 검색 신뢰성 검증 게이트", "",
        f"- 실행 시각(UTC): {data.get('timestamp_utc')}",
        f"- 키워드: {data.get('keyword')}",
        f"- 모드: {data.get('mode')}",
        f"- 실행 상태: **{data.get('status')}**",
        "- 데이터 승인 의미: **관측된 상품 집합의 제한적 재현성만 확인** (실제 거래 지역·전체 수집률 미보증)", "",
        "## 판정 분포", "",
        "| 판정 | 샘플 수 |", "|---|---:|",
    ]
    for name, count in outcome["counts"].items():
        lines.append(f"| `{name}` | {count} |")
    lines += ["", "## 지역별 단계", "",
              "| 컨텍스트 | 단계 | 지역 | 단계 유형 | 상품 수 | 판정 |",
              "|---|---:|---|---|---:|---|"]
    decision_by_id = {x["sample_id"]: x for x in outcome["decisions"]}
    for s in data.get("run", {}).get("samples", []):
        decision = decision_by_id[s["sample_id"]]
        lines.append("| {} | {} | {} | {} | {} | `{}` |".format(
            s["context"], s["step"], s["region"], s["phase"], s["item_count"], decision["verdict"]))
    lines.extend(["", "## 다른 지역의 첫 요청에서 동일한 상품 집합", ""])
    if outcome["collisions"]:
        for item in outcome["collisions"]:
            lines.append("- {}: {}개, 지역 {}, 지문 {}...".format(
                len(item["sample_ids"]), item["count"], ", ".join(item["regions"]), item["sha256"][:16]))
    else:
        lines.append("- 이번 실행의 서로 다른 지역 첫 요청 간 완전 동일 목록은 감지되지 않았습니다.")
    lines.extend(["", "## 동일 컨텍스트 내 연속된 같은 지역 재방문", ""])
    for row in outcome["same_context_pairs"]:
        lines.append("- {}: Jaccard {:.4f}, {} → {}".format(row["region"],
             row["jaccard"], row["left"], row["right"]))
    if not outcome["same_context_pairs"]:
        lines.append("- 비교 가능한 쌍이 없습니다.")
    lines.extend(["", "## 해석 및 운영 제한", ""])
    lines += ["- 최초 문서에서 예상 지역 ID가 맞거나 249/250/256개 상품이 있다는 것만으로 정확하다고 판단하지 않습니다.",
              "- 과거 로그의 동일 상품 집합 지문은 위험 신호이지, 시차가 있는 결과를 지역별 사실로 보증하는 근거가 아닙니다.",
              "- 최초 응답·지역 간 동일 목록·재방문 큰 변화·검증 누락은 수집 결과에서 격리하거나 확인 대기로 유지합니다.",
              "- `LIMITED_ACCEPT_REGIONAL_LISTING_SET`은 동일 실행 내 독립 컨텍스트 대조와 지역 간 차이 확인을 뜻합니다. 거래 가능 거리, 매물 최신성, 가격, 재고, 전체 검색 재현율 검증을 의미하지 않습니다.",
              "- 실제 구매 판단 전 판매 게시물과 지역·상태·SMART 등을 수동 확인해야 합니다.",
              "- 브라우저 로그인·쿠키 내용·저장소 값·인증 토큰은 파일에 보관하지 않습니다.",
              "- 접근 제한을 우회하지 않으며, 자동화 가능 여부는 이용약관과 별도로 확인해야 합니다.", ""]
    return "\n".join(lines)


def emit_outputs(args, run: dict, *, mode: str, status: str, historical: list | None = None,
                 public_urls_by_sample: dict | None = None):
    bad = historical_collision_signatures(historical or [])
    gated = gate_with_known(run, bad)
    # A partially failed live run cannot approve any sample, even with a match.
    if mode == "live" and status != "CAPTURED_COMPLETE":
        for decision in gated["decisions"]:
            if decision["allowed_for_price_analysis"]:
                decision["allowed_for_price_analysis"] = False
                decision["verdict"] = "UNVERIFIED_INCOMPLETE_RUN"
                decision["why"].append("The live capture ended early; fail-closed")
        gated["counts"] = dict(sorted(Counter(d["verdict"] for d in gated["decisions"]).items()))
    data = {"version": VERSION, "timestamp_utc": utc_now(), "mode": mode,
            "keyword": run.get("keyword"), "status": status, "run": run}
    compact = gate.safe_compact_report(run, gated)
    out = args.output_dir
    report_name = out / "daangn_browser_v4_4_report.md"
    safe_json(out / "daangn_browser_v4_4_results.json", {
        "version": VERSION, "timestamp_utc": data["timestamp_utc"],
        "mode": mode, "keyword": data["keyword"], "status": status,
        "run": {k: v for k, v in compact.items() if k != "gate"},
        "gate": gated, "historical_reference_runs": len(historical or []),
        "historical_collision_signature_count": len(bad),
        "raw_cookie_values_saved": False,
    })
    report_name.write_text(report_for_run(data, compact), encoding="utf-8")

    lookup = {s["sample_id"]: s for s in run.get("samples", [])}
    quarantine = [dict(d) for d in gated["decisions"] if d["verdict"].startswith("QUARANTINED")]
    unverified = [dict(d) for d in gated["decisions"] if d["verdict"].startswith("UNVERIFIED")]
    accepted = [d for d in gated["decisions"] if d["allowed_for_price_analysis"]]
    safe_json(out / "daangn_browser_v4_4_quarantine.json", {
        "version": VERSION, "run": run["run"], "quarantined": quarantine,
        "unverified": unverified, "count_quarantined": len(quarantine),
        "count_unverified": len(unverified), "blocked_for_downstream": True,
    })
    # Only current, gated, first-party public listing URLs can leave the raw
    # capture. Historical runs never release old listing URLs as current.
    urls_by_sample = public_urls_by_sample or {}
    safe_json(out / "daangn_browser_v4_4_limited_accept.json", {
        "version": VERSION, "run": run["run"], "status": "REPEAT_CONSISTENCY_ONLY",
        "approved_for_automated_purchase": False, "approved_for_geographic_assertions": False,
        "samples": [{"region": lookup[d["sample_id"]]["region"],
             "item_count": d["count"], "sample_id": d["sample_id"],
             "set_sha256": d["set_sha256"], "listing_id_sha256_prefixes": lookup[d["sample_id"]]["items"],
             "public_listing_urls": sorted({u for u in urls_by_sample.get(d["sample_id"], [])
                   if gate.stable_article_id(u) is not None})}
             for d in accepted],
        "note": "Hashed public IDs only. Does not verify listing availability, distance, or completeness."
    })
    print("v4.4 status:", status)
    print("Samples:", len(gated["decisions"]), "quarantined:", len(quarantine),
          "unverified:", len(unverified), "limited-accept:", len(accepted))
    for f in ("daangn_browser_v4_4_results.json", "daangn_browser_v4_4_report.md",
              "daangn_browser_v4_4_quarantine.json", "daangn_browser_v4_4_limited_accept.json"):
        print("Saved:", out / f)
    return gated


async def live_run(args, historical: list):
    robots = core.public_robots_check(args.keyword)
    if not robots.get("allowed"):
        empty = {"run": "v44_live", "version": "4.4", "keyword": args.keyword, "samples": []}
        emit_outputs(args, empty, mode="live", status="STOP_ROBOTS_UNVERIFIED_OR_DISALLOWED", historical=historical)
        return 2
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        empty = {"run": "v44_live", "version": "4.4", "keyword": args.keyword, "samples": []}
        emit_outputs(args, empty, mode="live", status="PLAYWRIGHT_NOT_INSTALLED", historical=historical)
        return 2
    # Read-only bounded original v4.3.2 capture. Three contexts x four page navigations.
    raw = {"version": "4.3.2", "keyword": args.keyword, "timestamp_utc": utc_now(), "plans": [],
           "status": "INCOMPLETE"}
    status = "CAPTURED_COMPLETE"
    selected = list(legacy.PLANS)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=not args.headed)
            try:
                for i, (key, targets) in enumerate(selected):
                    plan = await legacy.run_plan(browser, args, key, targets)
                    raw["plans"].append(plan)
                    if plan.get("status") != "CAPTURED_FOUR_PHASES":
                        status = "STOP_" + str(plan.get("status", "INCOMPLETE"))
                        break
                    if i != len(selected) - 1:
                        await asyncio.sleep(args.pause_ms / 1000)
            finally:
                await browser.close()
    except Exception as exc:
        status = "STOP_BROWSER_" + type(exc).__name__
    if len(raw["plans"]) != len(selected):
        status = status if status != "CAPTURED_COMPLETE" else "STOP_INCOMPLETE_CAPTURE"
    raw["status"] = "CAPTURED_SESSION_STATE_DIAGNOSTIC" if status == "CAPTURED_COMPLETE" else status
    normalized = gate.normalize(raw, run_key="v44_live")
    public_urls = {}
    for plan in raw["plans"]:
        for i, stage in enumerate(plan.get("stages", [])):
            sid = "v44_live:{}:{}:{}".format(plan["key"], i+1, stage.get("target"))
            public_urls[sid] = stage.get("loader_urls", [])
    emit_outputs(args, normalized, mode="live", status=status,
                 historical=historical, public_urls_by_sample=public_urls)
    return 0 if status == "CAPTURED_COMPLETE" else 2


def audit_mode(args, history: list):
    if not history:
        print("No historical reference evidence; use --reference or inspect README.")
        return 2
    summary = []
    total = Counter()
    for run in history:
        outcome = gate.apply_gate(run)
        counts = outcome["counts"]
        total.update(counts)
        summary.append({"run": run["run"], "version": run["version"],
                        "samples": len(run["samples"]), "counts": counts,
                        "collision_count": len(outcome["collisions"]),
                        "collision_regions": [x["regions"] for x in outcome["collisions"]],
                        "cold_repeat_outliers": len([x for x in outcome["decisions"] if x["verdict"] ==
                                "QUARANTINED_COLD_OR_SWITCH_OUTLIER"]),
                        "limited_accept": counts.get("LIMITED_ACCEPT_REGIONAL_LISTING_SET", 0)})
    print("Audited", len(summary), "archived historical runs, separately (no cross-date promotion).")
    for row in summary:
        print(row["run"], row["version"], "collision_groups=", row["collision_count"],
              "quarantined_outliers=", row["cold_repeat_outliers"],
              "limited_accept=", row["limited_accept"])
    output = {"version": VERSION, "mode": "audit", "timestamp_utc": utc_now(),
              "historical_runs": summary, "overall_counts": dict(sorted(total.items())),
              "note": "Historical runs are analyzed independently and cannot approve new live data."}
    safe_json(args.output_dir / "daangn_browser_v4_4_audit.json", output)
    lines = ["# v4.4 과거 진단 로그 검증", "",
             "- 과거 버전별 실행을 각각 독립적으로 분석했으며 다른 날짜의 매물을 자동 승인하지 않습니다.", "",
             "| 실험 | 버전 | 샘플 수 | 서로 다른 지역 최초 동일 목록 | 첫 요청 이상 격리 | 제한적 승인 |",
             "|---|---|---:|---:|---:|---:|"]
    for row in summary:
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            row["run"], row["version"], row["samples"], row["collision_count"],
            row["cold_repeat_outliers"], row["limited_accept"]))
    lines += ["", "다른 지역 최초 응답에서 동일한 상품 집합이 나왔다는 신호는 격리 조건입니다.",
              "지역 정확성 및 전체 매물 수집률은 어느 단계에서도 입증되지 않았습니다.", ""]
    (args.output_dir / "daangn_browser_v4_4_audit.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


def parser():
    p = argparse.ArgumentParser(description="Daangn v4.4 fail-closed regional search evidence gate")
    p.add_argument("--mode", choices=("live", "audit"), default="live")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--keyword", default="HDD")
    p.add_argument("--reference", type=Path, default=ROOT / "evidence" / "reference_runs.json")
    p.add_argument("--output-dir", type=Path, default=ROOT)
    p.add_argument("--timeout", type=int, default=22)
    p.add_argument("--settle-ms", type=int, default=1300)
    p.add_argument("--pause-ms", type=int, default=1500)
    p.add_argument("--min-dom-overlap", type=float, default=.8)
    return p


def main():
    args = parser().parse_args()
    if not (1 <= len(args.keyword.strip()) <= 60):
        raise SystemExit("--keyword length must be 1..60")
    if not 0 <= args.min_dom_overlap <= 1:
        raise SystemExit("--min-dom-overlap must be within 0..1")
    args.timeout = max(10, min(45, args.timeout))
    args.settle_ms = max(500, min(4000, args.settle_ms))
    args.pause_ms = max(800, min(15000, args.pause_ms))
    args.scroll = False
    args.output_dir = args.output_dir.resolve()
    # Exposes historical SHA/listing-id hashes only, not historical full raw pages.
    history = evidence_reference(args.reference)
    if args.mode == "audit":
        return audit_mode(args, history)
    return asyncio.run(live_run(args, history))


if __name__ == "__main__":
    sys.exit(main())
