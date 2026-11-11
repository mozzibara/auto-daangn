# -*- coding: utf-8 -*-
"""Public-safe failure classification for explicitly approved v4.34 runs.

Never print untrusted website text, paths, URL/title, raw runner logs, encrypted
payloads, token material, or the recipient public key. The original capture
gate stays fail-closed. This diagnostic does not access the marketplace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OUTER_STATUSES = frozenset({
    "STOP_PREFLIGHT", "STOP_RUNTIME_LIMIT",
    "SEALED_CAPTURE_COMPLETE", "INCONCLUSIVE_SECURE_CAPTURE",
    "INCONCLUSIVE_INCOMPLETE_SECURE_CAPTURE",
})
INNER_STATUSES = frozenset({
    "PUBLIC_STATUS_SIGNAL_SURVEY_COMPLETE_NO_DIRECT_FOR_SALE_PROOF",
    "PUBLIC_DIRECT_FOR_SALE_UI_CONFIRMED",
    "INCONCLUSIVE_MISSING_PIPELINE_EVIDENCE",
    "INCONCLUSIVE_LEGACY_OR_INVALID_EVIDENCE",
    "INCONCLUSIVE_CONTEXT_IDENTITY",
    "QUARANTINED_OR_INCOMPLETE_PUBLIC_SIGNAL_SURVEY",
    "INCONCLUSIVE_INCOMPLETE_BOUNDED_CAPTURE",
    "INCONCLUSIVE_CAPTURE_ARTIFACTS_UNAVAILABLE",
    "INCONCLUSIVE_UPSTREAM_CAPTURE_FAILURE",
})
ROBOTS_REASONS = frozenset({
    "NOT_CHECKED", "ALLOWED", "DISALLOWED", "ROBOTS_NON_200",
    "ROBOTS_TOO_LARGE", "ROBOTS_UNAVAILABLE_HTTPError",
    "ROBOTS_UNAVAILABLE_URLError", "ROBOTS_UNAVAILABLE_TimeoutError",
})
# All emitted strings are fixed constants; never echo unrecognized values.


def _read(folder: Path, filename: str, *, max_bytes: int = 16000) -> dict:
    path = folder / filename
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError, OSError):
        return {}
    return doc if type(doc) is dict else {}


def classify(folder: Path) -> dict[str, str]:
    outer = _read(folder, "v434_run_status.json")
    robots = _read(folder, "v434_robots_decision.json")
    inner = _read(folder, "v429_run_status.json")
    study = _read(folder, "v429_public_status_results.json")
    # v4.23 reports can contain nested per-item summaries. Read only from
    # the fixed local file and emit *only* count and allowlisted enum fields.
    upstream = _read(folder, "v423_public_controls_results.json",
                     max_bytes=2 * 1024 * 1024)
    evaluation = upstream.get("evaluation")
    evaluation = evaluation if type(evaluation) is dict else {}
    contexts = evaluation.get("contexts")
    contexts = contexts if type(contexts) is list else []
    safe_contexts = {"cheonan_a", "asan_control", "cheonan_b", "browser"}
    expected_contexts = ["cheonan_a", "asan_control", "cheonan_b"]
    safe_failures = {
        "NONE", "BASELINE_HTTP_INVALID", "REGION_MISMATCH",
        "FRESH_REGION_PROOF_MISSING", "ACCESS_RESTRICTION",
        "CORRELATED_ROUTE_MISSING",
        "ROUTE_LENGTH_MISMATCH", "LOCAL_EXTRACTION_TRUNCATED",
        "BROWSER_EXCEPTION", "OTHER_STOP",
    }
    safe_upstream_statuses = {
        "STOP_ACCESS_RESTRICTION", "INCONCLUSIVE_CONTROL_STUDY_INCOMPLETE",
        "INCONCLUSIVE_CANONICAL_CONTROL_RECORDS",
        "PUBLIC_CONTROL_WITNESSES_CONFLICT",
        "BOTH_SOLD_AND_RESERVED_CONTROL_UI_CORROBORATED",
        "PARTIAL_CONTROL_CLASSES_AVAILABLE",
        "CONTROL_UI_NOT_OBSERVABLE", "PARTIAL_CONTROL_UI_CORROBORATED",
    }
    raw_upstream_status = evaluation.get("status")
    upstream_status = (raw_upstream_status if type(raw_upstream_status) is str
                       and raw_upstream_status in safe_upstream_statuses
                       else "UNAVAILABLE_OR_UNKNOWN")
    safe_rows = []
    for item in contexts[:3]:
        item = item if type(item) is dict else {}
        name = item.get("context")
        code = item.get("capture_failure_code")
        safe_rows.append((
            name if type(name) is str and name in safe_contexts else "UNKNOWN",
            code if type(code) is str and code in safe_failures else "UNKNOWN",
        ))
    safe_sequence = ",".join(x[0] for x in safe_rows) or "NONE"
    first_failure = next((code for _, code in safe_rows
                          if code not in ("NONE", "UNKNOWN")), "NONE")
    matched_contexts = ([x[0] for x in safe_rows] == expected_contexts)
    source_visits = evaluation.get("source_detail_visits")
    safe_visits = (str(source_visits) if type(source_visits) is int
                   and 0 <= source_visits <= 9 else "UNKNOWN")
    raw_browser_exceptions = evaluation.get("browser_capture_exception_types")
    safe_browser_exception = ("YES" if type(raw_browser_exceptions) is dict
                              and bool(raw_browser_exceptions) else "NO")
    first = contexts[0] if contexts and type(contexts[0]) is dict else {}
    region_proof = first.get("baseline_region_url_evidence")
    region_proof = region_proof if type(region_proof) is dict else {}
    statuses = {"EXPECTED", "MISSING", "OTHER", "INVALID"}
    params = {"PRESENT", "MISSING", "INVALID"}
    def classified(stage, field, choices):
        source = region_proof.get(stage)
        val = source.get(field) if type(source) is dict else None
        return val if type(val) is str and val in choices else "UNKNOWN"
    def changed(field):
        value = region_proof.get(field)
        return ("YES" if value is True else "NO" if value is False
                else "UNKNOWN")
    picker = first.get("region_picker")
    picker = picker if type(picker) is dict else {}
    picker_outcomes = {
        "NOT_NEEDED", "NOT_ELIGIBLE", "ACCESS_BLOCKED",
        "ROBOTS_DENIED", "VERIFIED", "UNVERIFIED",
        "PENDING_FRESH_ROUTE", "VERIFIED_FRESH_ROUTE",
        "FRESH_REGION_PROOF_MISSING",
    }
    region_authorities = {
        "LEGACY_REGION_URL_WITNESS", "UI_FRESH_ROUTE_REGION_VERIFIED",
        "REGION_URL_INVALID", "REGION_UI_NOT_VERIFIED",
        "FRESH_ROUTE_NOT_VERIFIED", "ROUTE_REGION_CONFLICT",
        "ROUTE_REGION_METADATA_MISSING",
        "REGION_URL_RESPONSE_DISAGREEMENT",
        "REGION_OMISSION_WITHOUT_UI_SELECTION",
    }
    raw_authority = first.get("fresh_region_authority_status")
    authority_status = (
        raw_authority if type(raw_authority) is str
        and raw_authority in region_authorities else "UNKNOWN"
    )
    raw_ui_source = first.get("fresh_region_ui_source")
    ui_source = (
        raw_ui_source if type(raw_ui_source) is str and raw_ui_source in
        {"VISIBLE_REGION_CONTROL", "UNIQUE_REGION_OPTION", "NONE"}
        else "UNKNOWN"
    )
    region_ids_match = first.get("fresh_region_route_ids_match")
    route_diag = first.get("region_route_observation")
    route_diag = route_diag if type(route_diag) is dict else {}
    def route_count(key):
        value = route_diag.get(key)
        return str(value) if type(value) is int and 0 <= value <= 20 else "UNKNOWN"
    def route_flag(key):
        value = route_diag.get(key)
        return "YES" if value is True else "NO" if value is False else "UNKNOWN"
    picker_robots = {
        "NOT_NEEDED", "ALLOWED", "DISALLOWED", "INVALID_REGION",
        "ROBOTS_NON_200", "ROBOTS_TOO_LARGE", "ROBOTS_UNAVAILABLE",
    }
    def picker_label(field, allowed):
        value = picker.get(field)
        return value if type(value) is str and value in allowed else "UNKNOWN"
    def picker_flag(field):
        value = picker.get(field)
        return "YES" if value is True else "NO" if value is False else "UNKNOWN"
    picker_url = picker.get("after_url_proof")
    picker_url = picker_url if type(picker_url) is dict else {}
    def picker_url_value(field, choices):
        value = picker_url.get(field)
        return value if type(value) is str and value in choices else "UNKNOWN"

    transition = picker.get("transition")
    transition = transition if type(transition) is dict else {}
    def transition_enum(field, choices):
        v = transition.get(field)
        return v if type(v) is str and v in choices else "UNKNOWN"
    def transition_flag(field):
        v = transition.get(field)
        return "YES" if v is True else "NO" if v is False else "UNKNOWN"
    def transition_count(field):
        v = transition.get(field)
        return str(v) if type(v) is int and 0 <= v <= 20 else "UNKNOWN"

    suggestion = transition.get("suggestion")
    suggestion = suggestion if type(suggestion) is dict else {}
    suggestion_states = {
        "NO_RESOLVER_RESPONSE", "AMBIGUOUS_RESOLVER_RESPONSES",
        "RESOLVER_SCHEMA_UNKNOWN", "NO_EXACT_CITY_TERM_MATCH",
        "AMBIGUOUS_CITY_TERM_MATCH", "POST_CLICK_SEARCH_NOT_UNIQUE",
        "UNIQUE_API_CANDIDATE_CORRELATED",
    }
    def suggestion_status():
        value = suggestion.get("state")
        return value if type(value) is str and value in suggestion_states else "UNKNOWN"
    def suggestion_count(field):
        value = suggestion.get(field)
        return str(value) if type(value) is int and 0 <= value <= 20 else "UNKNOWN"
    def suggestion_flag(field):
        value = suggestion.get(field)
        return "YES" if value is True else "NO" if value is False else "UNKNOWN"

    raw_outer = outer.get("status")
    if type(raw_outer) is str and raw_outer in OUTER_STATUSES:
        outer_code = raw_outer
    elif type(raw_outer) is str and raw_outer.startswith("STOP_ROBOTS_"):
        outer_code = "STOP_ROBOTS"
    elif type(raw_outer) is str and raw_outer.startswith("STOP_"):
        outer_code = "STOP_EXCEPTION_REDACTED"
    else:
        outer_code = "UNAVAILABLE_OR_UNKNOWN"

    raw_reason = robots.get("reason")
    robots_reason = (raw_reason if type(raw_reason) is str
                     and raw_reason in ROBOTS_REASONS else "UNKNOWN")
    if (type(raw_reason) is str
            and raw_reason.startswith("ROBOTS_UNAVAILABLE_")
            and robots_reason == "UNKNOWN"):
        robots_reason = "ROBOTS_UNAVAILABLE_OTHER"

    raw_inner = inner.get("status")
    inner_code = (raw_inner if type(raw_inner) is str
                  and raw_inner in INNER_STATUSES else "UNAVAILABLE_OR_UNKNOWN")
    status = study.get("evaluation")
    survey = status.get("status") if type(status) is dict else None
    survey_code = (survey if type(survey) is str
                   and survey in INNER_STATUSES else "UNAVAILABLE_OR_UNKNOWN")

    http_status = robots.get("http_status")
    safe_http = (str(http_status) if type(http_status) is int
                 and 100 <= http_status <= 599 else "UNKNOWN")

    return {
        "CAPTURE_STATUS": outer_code,
        "CAPTURE_ATTEMPTED_LIVE": (
            "YES" if outer.get("attempted_live") is True else "NO"
        ),
        "ROBOTS_ALLOWED": (
            "YES" if robots.get("allowed") is True
            else "NO" if robots.get("allowed") is False else "UNKNOWN"
        ),
        "ROBOTS_REASON": robots_reason,
        "ROBOTS_HTTP_STATUS": safe_http,
        "INNER_CAPTURE_STATUS": inner_code,
        "SURVEY_STATUS": survey_code,
        "PUBLIC_SUMMARY_PRESENT": (
            "YES" if (folder / "v434_secure_links_summary.json").is_file()
            else "NO"
        ),
        "UPSTREAM_CAPTURE_STATUS": upstream_status,
        "UPSTREAM_CONTEXT_COUNT": (str(len(contexts)) if len(contexts) <= 20
                                   else "OVER_LIMIT"),
        "UPSTREAM_CONTEXT_SEQUENCE": safe_sequence,
        "UPSTREAM_EXPECTED_CONTEXTS_COMPLETE": (
            "YES" if matched_contexts else "NO"
        ),
        "UPSTREAM_FIRST_FAILURE_CODE": first_failure,
        "UPSTREAM_SOURCE_VISITS": safe_visits,
        "UPSTREAM_BROWSER_EXCEPTION_PRESENT": safe_browser_exception,
        "BASELINE_REQUEST_REGION": classified("requested", "region", statuses),
        "BASELINE_HTTP_REGION": classified("response", "region", statuses),
        "BASELINE_RENDERED_REGION": classified("rendered", "region", statuses),
        "BASELINE_RENDERED_HOST": classified("rendered", "host", statuses),
        "BASELINE_RENDERED_PATH": classified("rendered", "path", statuses),
        "BASELINE_RENDERED_REGION_PARAMETER": classified(
            "rendered", "region_parameter", params),
        "BASELINE_RENDERED_KEYWORD": classified("rendered", "keyword", statuses),
        "BASELINE_HTTP_URL_CHANGED": changed("response_changed_from_request"),
        "BASELINE_RENDERED_URL_CHANGED": changed("rendered_changed_from_response"),
        "ROUTE_FIRST_PARTY_FETCH_COUNT": route_count("search_fetch_responses"),
        "ROUTE_LEGACY_DATA_COUNT": route_count("legacy_data_responses"),
        "ROUTE_ALTERNATE_JSON_COUNT": route_count("other_search_json_responses"),
        "ROUTE_PARSED_MODEL_COUNT": route_count("parsed_route_models"),
        "ROUTE_FILTER_MATCH_COUNT": route_count("matched_filter_routes"),
        "ROUTE_KEYWORD_MATCH": route_flag("last_request_keyword_matches"),
        "ROUTE_CATEGORY_QUERY_MATCH": route_flag("last_request_category_matches"),
        "ROUTE_AVAILABLE_QUERY_MATCH": route_flag(
            "last_request_availability_matches"),
        "ROUTE_PRICE_QUERY_MATCH": route_flag("last_request_price_matches"),
        "ROUTE_SERVER_SEARCH_REGION_MATCH": route_flag(
            "last_route_search_region_matches"),
        "ROUTE_SERVER_FILTER_REGION_MATCH": route_flag(
            "last_route_filter_region_matches"),
        "ROUTE_SERVER_REGION_NAME": (
            route_diag.get("server_region_name_state")
            if route_diag.get("server_region_name_state")
            in ("MISSING","EXACT","CONTAINS","OTHER") else "UNKNOWN"
        ),
        "ROUTE_SERVER_REGION_IDS_AGREE": (
            route_diag.get("server_region_ids_agree")
            if route_diag.get("server_region_ids_agree")
            in ("YES","NO","MISSING") else "UNKNOWN"
        ),
        "ROUTE_HISTORICAL_REGION_ID_DRIFT_CANDIDATE": route_flag(
            "historical_id_drift_candidate"),
        "ROUTE_SEARCH_REGION_FIELD": (
            route_diag.get("last_route_search_region_state")
            if route_diag.get("last_route_search_region_state")
               in ("EXPECTED","MISSING","OTHER") else "UNKNOWN"
        ),
        "ROUTE_FILTER_REGION_FIELD": (
            route_diag.get("last_route_filter_region_state")
            if route_diag.get("last_route_filter_region_state")
               in ("EXPECTED","MISSING","OTHER") else "UNKNOWN"
        ),
        "ROUTE_RESPONSE_REGION_QUERY_MISSING": route_flag(
            "last_request_region_missing"),
        "FRESH_REGION_AUTHORITY_STATUS": authority_status,
        "FRESH_REGION_UI_SOURCE": ui_source,
        "FRESH_REGION_ROUTE_IDS_MATCH": (
            "YES" if region_ids_match is True
            else "NO" if region_ids_match is False else "UNKNOWN"
        ),
        "REGION_PICKER_OUTCOME": picker_label("outcome", picker_outcomes),
        "REGION_PICKER_ROBOTS_PERMISSION": picker_label(
            "robots_permission", picker_robots),
        "REGION_PICKER_ATTEMPTED": picker_flag("attempted"),
        "REGION_PICKER_BUTTON_CLICKED": picker_flag("button_clicked"),
        "REGION_PICKER_OPTION_SELECTED": picker_flag("suggestion_selected"),
        "REGION_PICKER_UNIQUE_OPTION": picker_flag("unique_region_option"),
        "REGION_PICKER_VERIFIED": picker_flag("verified_region_and_keyword"),
        "REGION_PICKER_FINAL_URL_REGION": picker_url_value("region", statuses),
        "REGION_PICKER_FINAL_URL_HOST": picker_url_value("host", statuses),
        "REGION_PICKER_FINAL_URL_PATH": picker_url_value("path", statuses),
        "REGION_PICKER_FINAL_URL_KEYWORD": picker_url_value("keyword", statuses),
        "REGION_PICKER_FINAL_URL_REGION_PARAMETER": picker_url_value(
            "region_parameter", params),
        "REGION_PICKER_VISIBLE_REGION_BUTTON": picker_flag(
            "selected_region_button_visible"),
        "PICKER_OPTION_SEMANTICS": transition_enum(
            "option_metadata", {"OBSERVED","UNAVAILABLE"}),
        "PICKER_OPTION_CITY_HINT": transition_flag("option_city_hint"),
        "PICKER_OPTION_EXACT_TERM": transition_flag("option_exact_term"),
        "PICKER_OPTION_DATA_ID": transition_enum(
            "option_data_id", {"EXPECTED","OTHER","MISSING"}),
        "PICKER_OPTION_STILL_VISIBLE": transition_flag("option_still_visible"),
        "PICKER_POST_CLICK_FETCH_COUNT": transition_count(
            "post_click_search_fetch_count"),
        "PICKER_POST_CLICK_MODEL_COUNT": transition_count(
            "post_click_model_count"),
        "PICKER_POST_CLICK_ROUTE_STATUS": transition_enum(
            "post_click_route_status",
            {"SELECTION_NOT_CONFIRMED","NO_FRESH_ROUTE",
             "AMBIGUOUS_FRESH_ROUTES","FRESH_ROUTE_OBSERVED",
             "UNPARSED_POST_CLICK_ROUTE",
             "POST_CLICK_QUERY_OR_ROUTE_INVALID"}),
        "PICKER_POST_CLICK_SEARCH_REGION": transition_enum(
            "search_region_state", {"EXPECTED","OTHER","MISSING"}),
        "PICKER_POST_CLICK_FILTER_REGION": transition_enum(
            "filter_region_state", {"EXPECTED","OTHER","MISSING"}),
        "PICKER_POST_CLICK_REGION_NAME": transition_enum(
            "server_name_state", {"EXACT","CONTAINS","OTHER","MISSING"}),
        "PICKER_POST_CLICK_IDS_AGREE": transition_enum(
            "server_ids_agree", {"YES","NO","MISSING"}),
        "PICKER_POST_CLICK_KEYWORD": transition_flag(
            "request_keyword_matches"),
        "PICKER_POST_CLICK_REGION_QUERY_MISSING": transition_flag(
            "request_region_missing"),
        "PICKER_FILTER_APPLY_TRANSITION": transition_enum(
            "filter_apply_relation",
            {"POST_CLICK_ROUTE_NOT_OBSERVABLE","EXPECTED_REGION_PERSISTED",
             "REGION_LOST_AT_FILTER_APPLY",
             "REGION_NOT_VERIFIED_AFTER_CLICK",
             "FILTER_APPLY_ROUTE_NOT_OBSERVABLE","NOT_OBSERVABLE"}),
        "SUGGESTION_RESOLVER_STATUS": suggestion_status(),
        "SUGGESTION_API_LOCATION_COUNT": suggestion_count("api_location_count"),
        "SUGGESTION_EXACT_CITY_TERM_COUNT": suggestion_count(
            "exact_city_term_candidate_count"),
        "SUGGESTION_PRESET_ID_MATCH": suggestion_flag(
            "preset_id_matches_candidate"),
        "SUGGESTION_POST_CLICK_SERVER_ID_MATCH": suggestion_flag(
            "candidate_matches_post_click_search_ids"),
        "SUGGESTION_POST_CLICK_REGION_NAME_MATCH": suggestion_flag(
            "post_click_name_matches_target"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print public-safe capture failure classification")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print("V434_REDACTED_FAILURE_DIAGNOSTIC_BEGIN")
    for key, value in classify(args.output_dir).items():
        print(f"{key}={value}")
    print("V434_REDACTED_FAILURE_DIAGNOSTIC_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
