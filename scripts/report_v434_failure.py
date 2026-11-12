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
        "FRESH_REGION_PROOF_MISSING", "EARLY_REGION_UNCOMMITTED",
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

    # Diagnostic search adapters are never sources of listing authorization.
    # Values are re-allowlisted even though upstream already sanitizes them.
    probe = first.get("search_surface_probe")
    probe = probe if type(probe) is dict else {}
    surface_rows = probe.get("surfaces")
    surface_rows = surface_rows if type(surface_rows) is dict else {}
    surface_fields = {}
    for name, prefix in (("legacy_ssr", "LEGACY_SSR"),
                         ("legacy_all_data", "LEGACY_DATA"),
                         ("modern_s", "MODERN_S")):
        obj = surface_rows.get(name)
        obj = obj if type(obj) is dict else {}
        allowed = {
            "STATUS": ("status", {"NOT_RUN", "ROBOTS_DENIED", "HTTP_OK",
                                 "HTTP_NON_200", "HTTP_REDIRECT", "ACCESS_BLOCKED",
                                 "REQUEST_ERROR", "BODY_ERROR"}),
            "SHAPE": ("shape", {"UNRECOGNIZED", "BODY_LIMIT", "MODERN_ROUTE",
                               "FLEAMARKET_API", "CHALLENGE",
                               "SSR_ITEMLIST", "HTML_NO_ITEMLIST"}),
            "URL_REGION": ("region", {"EXPECTED", "OTHER", "MISSING", "INVALID"}),
            "SERVER_REGION": ("server_region", {"EXPECTED", "OTHER", "MISSING"}),
            "FILTER_REGION": ("filter_region", {"EXPECTED", "OTHER", "MISSING"}),
            "URL_PATH": ("path", {"EXPECTED", "OTHER"}),
            "URL_KEYWORD": ("keyword", {"EXPECTED", "OTHER", "MISSING"}),
        }
        for suffix, (field, choices) in allowed.items():
            val = obj.get(field)
            surface_fields[f"SURFACE_{prefix}_{suffix}"] = (
                val if type(val) is str and val in choices else "UNKNOWN")
        for field, suffix in (("article_count", "ITEM_COUNT"),
                              ("api_emitted", "API_EMITTED_COUNT")):
            val = obj.get(field)
            surface_fields[f"SURFACE_{prefix}_{suffix}"] = (
                str(val) if type(val) is int and 0 <= val <= 650 else "UNKNOWN")

    # Independent visible UI + navigation evidence around the exact picker
    # click. Every byte exported below is a fixed enum, not an actual URL.
    navigation = picker.get("navigation_trace")
    navigation = navigation if type(navigation) is dict else {}
    nav_stages = navigation.get("checkpoints")
    nav_stages = nav_stages if type(nav_stages) is dict else {}
    nav_classes = {
        "VISIBLE_TARGET_REVERTED_TO_OTHER", "VISIBLE_TARGET_LOST",
        "UI_TARGET_SERVER_OTHER", "UI_TARGET_VISIBLE_DIAGNOSTIC_ONLY",
        "UI_OTHER_AND_SERVER_OTHER", "NO_VISIBLE_COMMIT_SERVER_OTHER",
        "TARGET_CONTROL_NOT_CONFIRMED", "NOT_OBSERVABLE",
    }
    nav_fields = {}
    for stage in ("BEFORE_CLICK", "AFTER_CLICK", "AFTER_FOLLOWUP_CLICK", "AFTER_SETTLE"):
        row = nav_stages.get(stage)
        row = row if type(row) is dict else {}
        for field, valid in (
            ("control", {"TARGET_VISIBLE", "OTHER_VISIBLE", "NOT_VISIBLE",
                         "AMBIGUOUS", "UNOBSERVABLE"}),
            ("dialog", {"OPEN", "CLOSED", "UNOBSERVABLE"}),
            ("listbox", {"OPEN", "CLOSED", "UNOBSERVABLE"}),
            ("confirm_action", {"VISIBLE", "NOT_VISIBLE", "AMBIGUOUS", "UNOBSERVABLE"}),
            ("input", {"EXPECTED", "OTHER", "MISSING", "UNOBSERVABLE"}),
            ("dialog_scope", {"TARGET_CANDIDATE","REGION_SEARCH_INPUT",
                              "MOST_INTERACTIVE","AMBIGUOUS","NONE","UNOBSERVABLE"}),
            ("dialog_heading", {"PICK_NEIGHBORHOOD","PICK_REGION","SEARCH",
                                "TARGET","OTHER","MISSING","UNOBSERVABLE"}),
            ("dialog_focus", {"INPUT","BUTTON","OTHER","OUTSIDE",
                              "NONE","UNOBSERVABLE"}),
            ("dialog_aria_modal", {"TRUE","FALSE","MISSING","OTHER","UNOBSERVABLE"}),
            ("url_region", {"EXPECTED", "OTHER", "MISSING", "INVALID"}),
            ("url_path", {"EXPECTED", "OTHER", "INVALID"}),
            ("url_keyword", {"EXPECTED", "OTHER", "MISSING", "INVALID"}),
        ):
            val = row.get(field)
            nav_fields[f"NAV_{stage}_{field.upper()}"] = (
                val if type(val) is str and val in valid else "UNKNOWN")
        for key in ("dialog_has_labelledby","dialog_has_back_action",
                    "dialog_has_selected_control"):
            val = row.get(key)
            nav_fields[f"NAV_{stage}_{key.upper()}"] = (
                "YES" if val is True else "NO" if val is False else "UNKNOWN")
        for key in ("dialog_buttons","dialog_target_buttons","dialog_search_inputs",
                    "dialog_selectables","dialog_selected_controls"):
            val = row.get(key)
            nav_fields[f"NAV_{stage}_{key.upper()}"] = (
                str(val) if type(val) is int and 0 <= val <= 20 else "UNKNOWN")
    nav_count = navigation.get("event_count")
    nav_raw_events = navigation.get("events")
    nav_raw_events = nav_raw_events if type(nav_raw_events) is list else []
    nav_sequence = []
    for event in nav_raw_events[:12]:
        event = event if type(event) is dict else {}
        kind = event.get("kind")
        region_state = event.get("url_region")
        path_state = event.get("url_path")
        if (type(kind) is str and
            kind in {"SEARCH_FETCH", "DOCUMENT_REQUEST", "MAIN_FRAME_NAVIGATED"}
            and type(region_state) is str
            and region_state in {"EXPECTED", "OTHER", "MISSING", "INVALID"}
            and type(path_state) is str
            and path_state in {"EXPECTED", "OTHER", "INVALID"}):
            nav_sequence.append(kind + ":" + region_state + ":" + path_state)

    # Option event evidence comes from the exact, uniquely clicked candidate.
    # Export ONLY fixed classes/booleans/capped counts; never DOM or event objects.
    option = navigation.get("option_event")
    option = option if type(option) is dict else {}
    option_attrs = option.get("attributes")
    option_attrs = option_attrs if type(option_attrs) is dict else {}
    option_steps = option.get("checkpoints")
    option_steps = option_steps if type(option_steps) is dict else {}
    option_fields = {}
    attr_classes = {
        "TAG": ("tag", {"BUTTON","OTHER","UNOBSERVABLE"}),
        "ROLE": ("role", {"OPTION","BUTTON","MISSING","OTHER","UNOBSERVABLE"}),
        "PARENT": ("parent", {"DIALOG","LISTBOX","OTHER","UNOBSERVABLE"}),
        "HASPOPUP": ("haspopup", {"DIALOG","LISTBOX","MENU","TRUE","FALSE","MISSING","OTHER","UNOBSERVABLE"}),
        "EXPANDED": ("expanded", {"TRUE","FALSE","MISSING","OTHER","UNOBSERVABLE"}),
        "BUTTON_TYPE": ("button_type", {"BUTTON","SUBMIT","RESET","MISSING","OTHER","UNOBSERVABLE"}),
        "DATA_STATE": ("data_state", {"OPEN","CLOSED","ACTIVE","INACTIVE","CHECKED","UNCHECKED","MISSING","OTHER","UNOBSERVABLE"}),
        "ARIA_DISABLED": ("aria_disabled", {"TRUE","FALSE","MISSING","OTHER","UNOBSERVABLE"}),
        "TAB_FOCUS": ("tab_focus", {"FOCUSABLE","NOT_FOCUSABLE","UNOBSERVABLE"}),
        "ARIA_LABEL_RELATION": ("aria_label_relation", {"TARGET","CITY","OTHER","MISSING","UNOBSERVABLE"}),
    }
    for suffix, (field, choices) in attr_classes.items():
        raw = option_attrs.get(field)
        option_fields[f"OPTION_ATTR_{suffix}"] = raw if type(raw) is str and raw in choices else "UNKNOWN"
    for field in ("has_aria_controls","has_aria_describedby","inside_form","native_disabled"):
        option_fields[f"OPTION_ATTR_{field.upper()}"] = (
            "YES" if option_attrs.get(field) is True else "NO")
    enum_fields = {
        "click_trusted": {"YES","NO","UNKNOWN"},
        "default_prevented": {"YES","NO","UNKNOWN"},
        "target_connected": {"YES","NO","UNKNOWN"},
        "dialog_connected": {"YES","NO","UNKNOWN"},
        "dialog_visible": {"YES","NO","UNKNOWN"},
        "focus": {"OPTION","INSIDE_DIALOG","OUTSIDE_DIALOG","NONE","UNKNOWN"},
        "expanded": {"TRUE","FALSE","MISSING","OTHER","UNKNOWN"},
        "event_target": {"BUTTON","DESCENDANT","OTHER","UNKNOWN"},
        "document_bubble": {"YES","NO","UNKNOWN"},
    }
    count_fields = ("child_mutations","attribute_mutations",
                    "added_buttons","added_dialogs","added_inputs")
    for step in ("AFTER_CLICK","AFTER_SETTLE"):
        row = option_steps.get(step)
        row = row if type(row) is dict else {}
        for key, choices in enum_fields.items():
            raw = row.get(key)
            option_fields[f"OPTION_{step}_{key.upper()}"] = (
                raw if type(raw) is str and raw in choices else "UNKNOWN")
        for key in count_fields:
            raw = row.get(key)
            option_fields[f"OPTION_{step}_{key.upper()}"] = (
                str(raw) if type(raw) is int and 0 <= raw <= 20 else "UNKNOWN")
        seq = row.get("events")
        seq = seq if type(seq) is list else []
        option_fields[f"OPTION_{step}_EVENTS"] = ",".join(
            v for v in seq[:8]
            if type(v) is str and v in {
                "POINTER_DOWN","POINTER_UP","CLICK_TARGET","CLICK_DOCUMENT"}) or "NONE"
    status = option.get("purpose")
    purposes = {
        "NOT_OBSERVABLE","CLICK_EVENT_NOT_SEEN",
        "COMMIT_CORROBORATED_DIAGNOSTIC","SECOND_STAGE_SIGNAL",
        "CLICK_DELIVERED_NO_COMMIT","EVENT_OBSERVED_OUTCOME_UNKNOWN",
    }
    option_fields["OPTION_EVENT_PURPOSE"] = (
        status if type(status) is str and status in purposes else "UNKNOWN")
    option_fields["OPTION_EVENT_ARM_STATE"] = (
        option.get("arm_state") if type(option.get("arm_state")) is str
        and option["arm_state"] in {"ARMED","NOT_OBSERVABLE"} else "UNKNOWN")
    option_fields["OPTION_EVENT_AUTHORIZES_LISTINGS"] = "NO"

    # Independent public boundary: never print DOM text, listing links, IDs or
    # unknown labels. Cap every count and permit only fixed enum sample fields.
    inventory = navigation.get("button_inventory")
    inventory = inventory if type(inventory) is dict else {}
    inventory_stages = inventory.get("checkpoints")
    inventory_stages = inventory_stages if type(inventory_stages) is dict else {}
    inv_fields = {}
    class_sets = {
        "role": ("NATIVE_BUTTON", "ARIA_OPTION", "ARIA_BUTTON", "OTHER"),
        "candidate": ("TARGET_WITH_CITY", "TARGET_ONLY", "CITY_ONLY",
                      "OTHER_REGION_LIKE", "NOT_REGION_LIKE"),
        "area": ("HEADER", "FOOTER", "LISTBOX", "NEAR_INPUT", "BODY", "OTHER"),
        "vertical": ("TOP", "MIDDLE", "BOTTOM", "UNKNOWN"),
        "action": ("BACK", "CONFIRM", "CLOSE", "SEARCH", "OTHER"),
        "origin": ("ORIGINAL_DIALOG", "OTHER_DIALOG"),
        "freshness": ("PRESENT_AT_ARM", "NEW_DOM_NODE"),
    }
    safe_scope = {"ORIGINAL_AND_OTHER", "ORIGINAL_ONLY", "OTHER_ONLY",
                  "NO_VISIBLE_DIALOG", "UNOBSERVABLE"}
    count_keys = ("visible_buttons", "new_dom_buttons", "new_target_buttons",
                  "new_region_like_buttons", "visible_target_buttons",
                  "region_like_buttons", "active_dialogs")
    for stage in ("BASELINE", "AFTER_CLICK", "AFTER_FOLLOWUP_CLICK", "AFTER_SETTLE"):
        snap = (inventory.get("baseline") if stage == "BASELINE"
                else inventory_stages.get(stage))
        snap = snap if type(snap) is dict else {}
        prefix = f"BUTTONS_{stage}"
        scope = snap.get("scope")
        inv_fields[f"{prefix}_SCOPE"] = (
            scope if type(scope) is str and scope in safe_scope else "UNKNOWN")
        inv_fields[f"{prefix}_OVERFLOW"] = "YES" if snap.get("overflow") is True else "NO"
        for key in count_keys:
            value = snap.get(key)
            inv_fields[f"{prefix}_{key.upper()}"] = (
                str(value) if type(value) is int and 0 <= value <= 100 else "UNKNOWN")
        groups = snap.get("groups")
        groups = groups if type(groups) is dict else {}
        for field, allowed in class_sets.items():
            group = groups.get(field)
            group = group if type(group) is dict else {}
            for value in allowed:
                raw = group.get(value)
                inv_fields[f"{prefix}_{field.upper()}_{value}"] = (
                    str(raw) if type(raw) is int and 0 <= raw <= 100 else "UNKNOWN")
        raw_samples = snap.get("samples")
        raw_samples = raw_samples if type(raw_samples) is list else []
        samples = []
        for obj in raw_samples[:8]:
            if type(obj) is not dict:
                continue
            if any(type(obj.get(key)) is not str or
                   obj[key] not in allowed for key,allowed in class_sets.items()):
                continue
            samples.append(":".join(obj[k] for k in class_sets))
        inv_fields[f"{prefix}_CATEGORICAL_SAMPLES"] = (
            "|".join(samples) if samples else "NONE")
    states = {
        "NOT_OBSERVABLE", "TARGET_MATCHING_NEW_DOM_NODES",
        "REGION_LIKE_NEW_DOM_NODES", "GENERIC_DOM_REPLACEMENTS_ONLY",
        "NO_NEW_BUTTON_NODES", "DIALOG_SCOPE_UNRESOLVED",
    }
    interpretation = inventory.get("interpretation")
    inv_fields["BUTTONS_INTERPRETATION"] = (
        interpretation if type(interpretation) is str
        and interpretation in states else "UNKNOWN")
    inv_fields["BUTTONS_ARMED"] = (
        inventory.get("armed") if inventory.get("armed") in
        ("ARMED","NOT_OBSERVABLE") else "UNKNOWN")
    inv_fields["BUTTONS_AUTHORIZES_LISTINGS"] = "NO"

    # API completion and visible DOM stability before the existing single
    # region candidate click. Fixed enums/counts only, independent of approval.
    ready = navigation.get("pre_click_readiness")
    ready = ready if type(ready) is dict else {}
    readiness_fields = {}
    ready_states = {
        "NOT_RUN", "READY", "API_TIMEOUT", "API_BLOCKED",
        "API_NOT_UNIQUE", "API_ID_MISMATCH", "API_SCHEMA_UNKNOWN",
        "DOM_NOT_FOUND", "DOM_NOT_STABLE", "DOM_AMBIGUOUS",
        "DOM_PROBE_ERROR",
    }
    state = ready.get("state")
    readiness_fields["READINESS_STATE"] = (
        state if type(state) is str and state in ready_states else "UNKNOWN")
    for flag in ("api_unique_candidate", "api_expected_id", "dom_stable"):
        val = ready.get(flag)
        readiness_fields[f"READINESS_{flag.upper()}"] = (
            "YES" if val is True else "NO" if val is False else "UNKNOWN")
    for key, upper, cap in (
        ("api_response_count", "API_RESPONSE_COUNT", 20),
        ("stable_samples", "STABLE_SAMPLES", 10)):
        raw = ready.get(key)
        readiness_fields[f"READINESS_{upper}"] = (
            str(raw) if type(raw) is int and 0 <= raw <= cap else "UNKNOWN")
    snap_stages = ready.get("snapshots")
    snap_stages = snap_stages if type(snap_stages) is dict else {}
    for stage in ("INITIAL", "FINAL"):
        snap = snap_stages.get(stage)
        snap = snap if type(snap) is dict else {}
        for key in ("candidate_buttons", "target_buttons",
                    "target_city_buttons", "dom_mutations"):
            raw = snap.get(key)
            readiness_fields[f"READINESS_{stage}_{key.upper()}"] = (
                str(raw) if type(raw) is int and 0 <= raw <= 100 else "UNKNOWN")
    readiness_fields["READINESS_AUTHORIZES_LISTINGS"] = "NO"

    # Only the exact new target-city UI node may have been clicked once.
    # This report never equates click receipt with server locality authority.
    second = navigation.get("second_choice")
    second = second if type(second) is dict else {}
    second_states = {"NOT_ATTEMPTED","CLICKED","KEYBOARD_ACTIVATED",
                     "KEY_SENT_NO_NATIVE_CLICK","CANDIDATE_NOT_UNIQUE",
                     "GUARD_REJECTED","INVENTORY_NOT_ARMED",
                     "ELEMENT_MISSING","CLICK_FAILED","FOLLOWUP_NOT_STABLE"}
    guard_states = {"READY","DETACHED","WRONG_DIALOG","WRONG_TAG",
                    "ORIGINAL_NODE","NOT_INTERACTABLE",
                    "NOT_EXACT_TARGET_CITY","NOT_UNIQUE",
                    "NO_NEW_CANDIDATE_LIST","UNOBSERVABLE"}
    second_fields = {
        "SECOND_CHOICE_STATE": (
            second.get("state") if type(second.get("state")) is str
            and second["state"] in second_states else "UNKNOWN"),
        "SECOND_CHOICE_GUARD": (
            second.get("guard") if type(second.get("guard")) is str
            and second["guard"] in guard_states else "UNKNOWN"),
        "SECOND_CHOICE_CLICK_ATTEMPTED": (
            "YES" if second.get("click_attempted") is True
            else "NO" if second.get("click_attempted") is False
            else "UNKNOWN"),
        "SECOND_CHOICE_CLICK_COMPLETED": (
            "YES" if second.get("click_completed") is True
            else "NO" if second.get("click_completed") is False
            else "UNKNOWN"),
        "SECOND_CHOICE_ACTIVATION_MODE": (
            "KEYBOARD_ENTER" if second.get("activation_mode") == "KEYBOARD_ENTER"
            else "NONE" if second.get("activation_mode") == "NONE" else "UNKNOWN"),
        "SECOND_CHOICE_NATIVE_CLICK_RECEIVED": (
            second.get("native_click_received")
            if second.get("native_click_received") in ("YES","NO","UNKNOWN")
            else "UNKNOWN"),
        "SECOND_CHOICE_NATIVE_CLICK_TRUSTED": (
            second.get("native_click_trusted")
            if second.get("native_click_trusted") in ("YES","NO","UNKNOWN")
            else "UNKNOWN"),
        "SECOND_CHOICE_ERROR_TYPE": (
            second.get("error_type")
            if second.get("error_type") in ("NONE","TIMEOUT","PLAYWRIGHT_ERROR","OTHER")
            else "UNKNOWN"),
        "SECOND_CHOICE_STABILITY_STATE": (
            second.get("stability_state")
            if type(second.get("stability_state")) is str
            and second["stability_state"] in {
                "NOT_RUN","STABLE","GUARD_CHANGED","DOM_UNSTABLE",
                "SNAPSHOT_MISSING","MUTATION_OVERFLOW","UNKNOWN"}
            else "UNKNOWN"),
        "SECOND_CHOICE_STABILITY_SAMPLES": (
            str(second.get("stability_samples"))
            if type(second.get("stability_samples")) is int
            and 0 <= second["stability_samples"] <= 6 else "UNKNOWN"),
        "SECOND_CHOICE_AUTHORIZES_LISTINGS": "NO",
    }
    # Request-start chronology: responses which arrive after a click may
    # have been requested before it. Never emit raw request URLs/timestamps.
    chronology = navigation.get("request_chronology")
    chronology = chronology if type(chronology) is dict else {}
    chron_states = {"NO_TRUSTED_CLICK_EPOCH","NO_POSTCLICK_REQUEST",
                    "POSTCLICK_REQUEST_OBSERVED"}
    chron_state = chronology.get("state")
    chron_fields = {
        "CHRONOLOGY_STATE": (
            chron_state if type(chron_state) is str
            and chron_state in chron_states else "UNKNOWN"),
    }
    for k in ("requests_started_before","requests_started_after",
              "responses_without_matching_request","eligible_response_count"):
        value = chronology.get(k)
        chron_fields["CHRONOLOGY_"+k.upper()] = (
            str(value) if type(value) is int and 0 <= value <= 20
            else "UNKNOWN")
    chron_fields["CHRONOLOGY_AUTHORIZES_LISTINGS"] = "NO"
    # Privacy-bounded UI lifecycle: no DOM text, URLs or unknown attributes.
    lifecycle = navigation.get("region_lifecycle")
    lifecycle = lifecycle if type(lifecycle) is dict else {}
    lifecycle_steps = lifecycle.get("checkpoints")
    lifecycle_steps = lifecycle_steps if type(lifecycle_steps) is dict else {}
    lifecycle_fields = {}
    allowed_states = {
        "TARGET_DIALOG_CHOICE","OTHER_DIALOG_CHOICES","REGION_INPUT_ONLY",
        "POSSIBLE_LOGIN_GATE","DIALOG_WITHOUT_CONTROLS","NO_DIALOG",
        "UNOBSERVABLE",
    }
    allowed_controls = {"EXPECTED","OTHER","MISSING","UNOBSERVABLE"}
    lifecycle_counts = (
        "visible_dialogs","visible_dialog_buttons","target_dialog_buttons",
        "target_city_dialog_buttons","target_outside_buttons",
        "other_region_dialog_buttons","confirm_dialog_buttons",
        "login_dialog_signals","region_dialog_inputs","busy_signals",
    )
    for stage in ("AFTER_FIRST","AFTER_FOLLOWUP_GATE",
                  "AFTER_CORE_SETTLE","AFTER_SETTLE",
                  "AFTER_DELAYED_SETTLE"):
        row = lifecycle_steps.get(stage)
        row = row if type(row) is dict else {}
        pre = f"LIFECYCLE_{stage}"
        state = row.get("state")
        control = row.get("selected_control")
        lifecycle_fields[f"{pre}_STATE"] = (
            state if type(state) is str and state in allowed_states
            else "UNKNOWN")
        lifecycle_fields[f"{pre}_SELECTED_CONTROL"] = (
            control if type(control) is str and control in allowed_controls
            else "UNKNOWN")
        for key in lifecycle_counts:
            value = row.get(key)
            lifecycle_fields[f"{pre}_{key.upper()}"] = (
                str(value) if type(value) is int and 0 <= value <= 60
                else "UNKNOWN")
    lifecycle_fields["LIFECYCLE_AUTHORIZES_LISTINGS"] = "NO"
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
        "REGION_PICKER_EARLY_GATE": picker_label(
            "early_gate", {"OBSERVED_WRONG_REGION",
                           "LOCALITY_CORROBORATED_DIAGNOSTIC",
                           "MIXED_OR_UNKNOWN","NOT_OBSERVABLE"}),
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
        "PICKER_FIRST_ACTIVATION_MODE": transition_enum(
            "first_activation_mode", {"POINTER_CLICK","KEYBOARD_ENTER",
                                      "UNOBSERVABLE"}),
        "PICKER_OPTION_SEMANTICS": transition_enum(
            "option_metadata", {"OBSERVED","UNAVAILABLE"}),
        "PICKER_OPTION_CITY_HINT": transition_flag("option_city_hint"),
        "PICKER_OPTION_EXACT_TERM": transition_flag("option_exact_term"),
        "PICKER_OPTION_DATA_ID": transition_enum(
            "option_data_id", {"EXPECTED","OTHER","MISSING"}),
        "PICKER_OPTION_STILL_VISIBLE": transition_flag("option_still_visible"),
        "PICKER_OPTION_TAG": transition_enum(
            "option_tag", {"BUTTON","OTHER","UNOBSERVABLE"}),
        "PICKER_OPTION_ROLE": transition_enum(
            "option_role", {"OPTION","BUTTON","MISSING","OTHER","UNOBSERVABLE"}),
        "PICKER_OPTION_PARENT": transition_enum(
            "option_parent", {"LISTBOX","DIALOG","OTHER","UNOBSERVABLE"}),
        "PICKER_OPTION_ARIA_SELECTED": transition_enum(
            "option_aria_selected", {"TRUE","FALSE","MISSING","OTHER","UNOBSERVABLE"}),
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
        "SEARCH_SURFACE_ROBOTS": (
            probe.get("robots") if probe.get("robots") in
            ("CHECKED", "ROBOTS_UNAVAILABLE", "NOT_ATTEMPTED") else "UNKNOWN"),
        "SEARCH_SURFACE_BLOCKED": "YES" if probe.get("blocked") is True else "NO",
        "SEARCH_SURFACE_AUTHORIZES_LISTINGS": "NO",
        "NAV_TRACE_DIALOG_TRANSITION": (
            navigation.get("dialog_transition")
            if type(navigation.get("dialog_transition")) is str
            and navigation["dialog_transition"] in {
                "NEW_DIALOG_WITH_CHANGED_CONTROLS","REPLACED_DIALOG_UNCLASSIFIED",
                "SAME_DIALOG_REMAINS","DIALOG_CLOSED","NOT_OBSERVABLE"}
            else "UNKNOWN"),
        "NAV_TRACE_COMMIT_CLASS": (
            navigation.get("commit_class")
            if type(navigation.get("commit_class")) is str
            and navigation["commit_class"] in nav_classes else "UNKNOWN"),
        "NAV_TRACE_EVENT_COUNT": (
            str(nav_count) if type(nav_count) is int
            and 0 <= nav_count <= 12 else "UNKNOWN"),
        "NAV_TRACE_EVENT_SEQUENCE": ",".join(nav_sequence) or "NONE",
        "NAV_TRACE_OVERFLOW": (
            "YES" if navigation.get("overflow") is True else "NO"),
        "NAV_TRACE_AUTHORIZES_LISTINGS": "NO",
        **nav_fields,
        **option_fields,
        **inv_fields,
        **readiness_fields,
        **second_fields,
        **lifecycle_fields,
        **chron_fields,
        **surface_fields,
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
