# -*- coding: utf-8 -*-
"""Opt-in real Chrome Stable input-event comparison.

Default: local HTML fixture in installed Chrome Stable, ZERO marketplace calls.
--live: only owner-approved, robots-checked, TWO bounded public region choices.
Never follows listing links, inspects seller data, uses credentials, modifies
browser fingerprints or authorizes private/OCI records.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
import urllib.robotparser
import urllib.request

import daangn_v4_1_core as core
from app_v5.manual_chrome_region import (
    SEARCH_URL, ManualSearchResponses, is_public_search,
)
from app_v5.region_input_events import (
    RegionInputEventWitness, sample_region_focus, sanitize_region_focus,
)
from app_v5.manual_region_input_events import ManualRegionInputEventWitness
from app_v5.region_lifecycle import RegionLifecycleWitness
from app_v5.region_baseline_contrast import (
    capture_first_load, sanitize_baseline, optional_egress_context,
    safe_machine_class, read_region_header_volatile,
    classify_region_header_transition, sanitize_header_transition,
)
from app_v5.region_picker_phases import (
    RegionPickerPhaseWitness, sanitize_picker_phases,
)
from app_v5.region_header_activation import (
    HeaderActivationWitness, verify_header_click_timeout_without_reclick,
)
from app_v5.region_option_events import (
    RegionOptionEventWitness, verify_single_target_click_after_timeout,
)
from app_v5.region_readiness import RegionReadinessWitness
from app_v5.region_suggestion import RegionSuggestionObserver
from scripts.run_live_checked import (
    AGENT, check_region_picker_robots,
)

_MODES = ("FILL", "SEQUENTIAL_KEYS")
_INPUT_SELECTOR = (
    'input[placeholder*="지역"], input[placeholder*="동네"], '
    '[role="dialog"] input, [role="combobox"]'
)
_APPROVAL = "I_APPROVE_CHROME_INPUT_COMPARISON_V1"
_DECISIONS = frozenset((
    "FIXTURE_COMPLETE", "API_OR_DOM_NOT_READY", "CLICK_NOT_TRUSTED",
    "TARGET_REGION_CONFIRMED_DIAGNOSTIC", "REGION_NOT_COMMITTED",
    "REGION_HEADER_ACTION_EXCEPTION", "REGION_OPTION_ACTION_EXCEPTION",
    "INCONCLUSIVE", "ACCESS_RESTRICTED", "BASELINE_INVALID",
    "UNEXPECTED_EXCEPTION",
))
_REGION = frozenset(("EXPECTED", "OTHER", "MISSING", "UNOBSERVABLE"))
_ROUTES = frozenset((
    "ONE_FRESH", "NONE_FRESH", "MULTIPLE_FRESH", "UNREADABLE_FRESH",
))
_INPUT_MODES = frozenset(_MODES)


def _strict_enum(value, valid, fallback):
    return value if type(value) is str and value in valid else fallback


def _bounded(value, max_value=20):
    return value if type(value) is int and 0 <= value <= max_value else -1


def sanitize_attempt(row) -> dict:
    src = row if type(row) is dict else {}
    observed = src.get("input_events")
    from app_v5.region_input_events import sanitize_input_events
    observed = sanitize_input_events(observed)
    focus = src.get("input_focus") if type(src.get("input_focus")) is dict else {}
    safe = {
        "mode": _strict_enum(src.get("mode"), _INPUT_MODES, "FILL"),
        "status": _strict_enum(src.get("status"), _DECISIONS,
                               "UNEXPECTED_EXCEPTION"),
        "input_events": observed,
        "input_focus": {
            k: sanitize_region_focus(focus.get(k))
            for k in ("BEFORE_SELECT", "AFTER_CLICK", "AFTER_4000MS")
        },
        "input_value_matches_expected": src.get("input_value_matches_expected")
                                        is True,
        "api_ready": src.get("api_ready") is True,
        "api_candidate_matches_expected": src.get("api_candidate_matches_expected")
                                          is True,
        "api_response_count": _bounded(src.get("api_response_count")),
        "native_click": _strict_enum(src.get("native_click"),
                                     ("YES", "NO", "UNKNOWN"), "UNKNOWN"),
        "route_status": _strict_enum(src.get("route_status"), _ROUTES,
                                     "NONE_FRESH"),
        "route_responses": _bounded(src.get("route_responses")),
        "server_search": _strict_enum(src.get("server_search"),
                                      _REGION, "UNOBSERVABLE"),
        "server_filter": _strict_enum(src.get("server_filter"),
                                      _REGION, "UNOBSERVABLE"),
        "selected_ui": _strict_enum(src.get("selected_ui"),
                                    _REGION, "UNOBSERVABLE"),
        "initial_baseline":sanitize_baseline(src.get("initial_baseline")),
        "header_transition":sanitize_header_transition(src.get("header_transition")),
        "picker_phase_diagnostics":sanitize_picker_phases(
            src.get("picker_phase_diagnostics")),
        "authorizes_listings": False,
    }
    if "precollection" in src:
        from app_v5.precollection_filter_gate import sanitize_precollection
        safe["precollection"] = sanitize_precollection(src.get("precollection"))
    return safe


def check_public_robots(*, getter=None):
    """Fail closed for the exact public query AND the suggestion endpoint."""
    getter = getter or urllib.request.urlopen
    try:
        req = urllib.request.Request(
            core.BASE + "/robots.txt", headers={"User-Agent": AGENT})
        with getter(req, timeout=20) as response:
            if response.status != 200:
                return False
            body = response.read(400_001)
        if len(body) > 400_000:
            return False
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(body.decode("utf-8", "replace").splitlines())
        return parser.can_fetch(AGENT, SEARCH_URL)
    except Exception:
        return False


async def one_fixture(browser, mode):
    context = await browser.new_context(locale="ko-KR")
    try:
        page = await context.new_page()
        # No HTTP, file:, external scripts, or non-fixture DOM.
        await page.set_content("<!doctype html><html><body>"
                               '<input type="text" id="region-fixture">'
                               "</body></html>")
        el = page.locator("#region-fixture")
        witness = RegionInputEventWitness()
        try:
            if not await witness.arm(el):
                return sanitize_attempt({"mode": mode, "status": "INCONCLUSIVE"})
            if mode == "FILL":
                await el.fill("불당동")
            else:
                await el.press_sequentially("불당동", delay=80)
            snapshot = await witness.sample(page)
            matches = await el.input_value() == "불당동"
            return sanitize_attempt({
                "mode": mode,
                "status": "FIXTURE_COMPLETE" if matches else "INCONCLUSIVE",
                "input_events": snapshot, "input_value_matches_expected": matches,
            })
        finally:
            await witness.stop(page)
    finally:
        await context.close()


async def delegated_manual_fixture(browser):
    """Offline DOM-only check: document witness survives later dialog creation.

    This is NOT real human IME evidence. It tests delegated listener wiring
    under real Chrome without visiting the marketplace.
    """
    from app_v5.manual_region_input_events import ManualRegionInputEventWitness
    context = await browser.new_context(locale="ko-KR")
    witness = ManualRegionInputEventWitness()
    try:
        page = await context.new_page()
        await page.set_content("<!doctype html><html><body></body></html>")
        armed = await witness.arm(page)
        if not armed:
            return {"armed": False, "observed_input": False,
                    "authorizes_listings": False}
        # The target input intentionally does NOT exist at arm time.
        await page.evaluate("""() => {
            const dialog=document.createElement('div');
            dialog.setAttribute('role','dialog');
            const field=document.createElement('input');
            field.setAttribute('placeholder','지역 검색');
            field.id='synthetic-region';
            dialog.appendChild(field);
            document.body.appendChild(dialog);
        }""")
        field = page.locator("#synthetic-region")
        await field.press_sequentially("불당동", delay=10)
        result = await witness.sample(page)
        matched = result["observed_input"] and result["counts"]["INPUT"] >= 1
        # Remove from DOM: witness should retain the already seen sequence.
        await page.evaluate("""() => {
            document.querySelector('[role="dialog"]').remove();
        }""")
        final = await witness.sample(page)
        return {"armed": armed, "observed_input": matched,
                "preserved_after_dialog_removal":
                    final["counts"]["INPUT"] == result["counts"]["INPUT"],
                "authorizes_listings": False}
    finally:
        try:
            await witness.stop(page)
        except Exception:
            pass
        await context.close()


async def one_public_region(browser, mode, *, timezone_id=None,
                            on_region_confirmed=None):
    region = core.BY_KEY["cheonan"]
    if timezone_id not in (None, "Asia/Seoul"):
        raise ValueError("ONLY_EXPLICIT_SEOUL_TIMEZONE_CONTROL_ALLOWED")
    # An explicit timezone only for a bounded, declared experimental arm.
    # No network/proxy, geolocation, storage, login or UA modification.
    settings = {"locale": "ko-KR", "viewport": {"width": 1280, "height": 850}}
    if timezone_id is not None:
        settings["timezone_id"] = timezone_id
    context = await browser.new_context(**settings)
    page = None
    input_probe = RegionInputEventWitness()
    option_probe = RegionOptionEventWitness(region)
    resolver = RegionSuggestionObserver(region)
    readiness = RegionReadinessWitness(region, resolver)
    network = ManualSearchResponses(region)
    lifecycle = RegionLifecycleWitness(region)
    picker_phase = RegionPickerPhaseWitness(region)
    header_activation = HeaderActivationWitness()
    header_activation_snapshot = None
    picker_phase_armed = False
    observed_input = None
    input_matches = False
    input_focus = {}
    click_epoch = None
    response_armed = False
    request_armed = False
    api_armed = False
    initial_baseline = None
    original_header = None
    header_transition = None
    try:
        page = await context.new_page()
        # Observe the very first search navigation, not only postclick.
        # No extra public request: the same Route witness tracks both phases.
        page.on("request", network.on_request)
        page.on("response", network.on_response)
        request_armed = True
        response_armed = True
        response = await page.goto(
            SEARCH_URL, wait_until="domcontentloaded", timeout=25000)
        if (response is None or response.status != 200
                or not is_public_search(page.url)):
            return sanitize_attempt({"mode": mode, "status": "BASELINE_INVALID"})
        await page.wait_for_timeout(1000)
        await network.drain()
        initial_baseline = await capture_first_load(
            page,region,passive_events=list(network.events))
        original_header=await read_region_header_volatile(page)
        # Attach before picker activation, so zero responses are disambiguated
        # from no input/no request, failed request or an unexpected HTTP code.
        page.on("request", picker_phase.on_request)
        page.on("response", picker_phase.on_response)
        page.on("requestfailed", picker_phase.on_requestfailed)
        picker_phase_armed = True

        async def after_timeout():
            # The original click may have dispatched successfully even when
            # Playwright's action promise timed out. Never issue a second click.
            # Check same-origin public search and independent trusted events,
            # plus one visible empty enabled region input inside the dialog.
            if not is_public_search(page.url):
                return False
            return await verify_header_click_timeout_without_reclick(
                page, header_activation)

        async def after_open():
            picker_phase.picker_opened = True
            await picker_phase.sample(page,"AFTER_PICKER_OPEN_500MS")

        async def before_search():
            nonlocal api_armed, request_armed
            if not api_armed:
                page.on("response", resolver.on_response)
                api_armed = True
            if not request_armed:
                page.on("request", network.on_request)
                request_armed = True
            # Core now awaits this callback, so the input witness is
            # installed on the exact visible text box BEFORE typing.
            if not await input_probe.arm(page.locator(_INPUT_SELECTOR).first):
                raise RuntimeError("INPUT_WITNESS_NOT_ARMED")

        async def after_search_fill():
            nonlocal observed_input, input_matches
            observed_input = await input_probe.sample(page)
            input_focus["BEFORE_SELECT"] = await sample_region_focus(page)
            input_matches = (
                await page.locator(_INPUT_SELECTOR).first.input_value()
                == region["term"])
            return await readiness.await_ready(page)

        def before_select():
            nonlocal response_armed
            if not response_armed:
                page.on("response", network.on_response)
                response_armed = True

        async def after_option_timeout():
            # The target candidate was already checked for unique visible
            # exact city term by core. Only prove the one *existing* browser
            # click. No second click, force, input change, or network request.
            if not is_public_search(page.url):
                return False
            return await verify_single_target_click_after_timeout(
                page, option_probe)

        async def after_select():
            nonlocal click_epoch
            click_epoch = await option_probe.trusted_click_epoch_ms(page)
            input_focus["AFTER_CLICK"] = await sample_region_focus(page)
            await option_probe.checkpoint(page, "AFTER_CLICK")

        await header_activation.arm(page)
        steps = await core.ui_select_region(
            page, region, on_before_search=before_search,
            on_after_open=after_open,
            on_header_click_timeout=after_timeout,
            on_after_search_fill=after_search_fill,
            on_option_witness=option_probe.arm,
            on_option_click_timeout=after_option_timeout,
            on_before_select=before_select,
            on_after_select=after_select,
            first_activation_mode="POINTER_CLICK",
            search_input_mode=mode,
        )
        await picker_phase.sample(page,"AFTER_CORE_RETURN")
        await page.wait_for_timeout(4200)
        await picker_phase.sample(page,"AFTER_SETTLE_4200MS")
        header_activation_snapshot = await header_activation.sample(page)
        input_focus["AFTER_4000MS"] = await sample_region_focus(page)
        header_transition=classify_region_header_transition(
            original_header,await read_region_header_volatile(page),
            target_term=region["term"])
        await option_probe.checkpoint(page, "AFTER_SETTLE")
        await lifecycle.checkpoint(page, "AFTER_DELAYED_SETTLE")
        await resolver.drain()
        await network.drain()
        ui = lifecycle.export()["checkpoints"]["AFTER_DELAYED_SETTLE"]
        ui_region = ui.get("selected_control", "UNOBSERVABLE")
        if ui_region not in ("EXPECTED", "OTHER", "MISSING"):
            ui_region = "UNOBSERVABLE"
        # NEVER read the search text input after the dialog closes.
        valid_click = (
            click_epoch is not None
            and steps.get("selected_suggestion") is True
            and steps.get("option_city_hint") is True
        )
        post = network.after_click(click_epoch) if valid_click else []
        route_status = (
            "NONE_FRESH" if not post else
            "ONE_FRESH" if len(post) == 1 and post[0]["state"] == "OBSERVED"
            else "UNREADABLE_FRESH" if len(post) == 1
            else "MULTIPLE_FRESH"
        )
        model = post[0].get("model", {}) if route_status == "ONE_FRESH" else {}
        model = model if type(model) is dict else {}
        server_search = model.get("search_region", "UNOBSERVABLE")
        server_filter = model.get("filter_region", "UNOBSERVABLE")
        selected = "YES" if valid_click else "NO"
        blocked = resolver.blocked or network.blocked
        api_ok = (
            readiness.export()["state"] == "READY"
            and readiness.export()["api_expected_id"]
            and len(resolver.events) == 1
            and len(resolver.events[0].get("matches", [])) == 1
        )
        if blocked or picker_phase.export()["api"]["state"] == "ACCESS_RESTRICTED":
            status = "ACCESS_RESTRICTED"
        elif (steps.get("progress_stage") == "BEFORE_REGION_BUTTON_CLICK"
              and steps.get("error") is not None):
            # Playwright call did not complete; passive browser event witness
            # separately tells whether a click event was already delivered.
            status = "REGION_HEADER_ACTION_EXCEPTION"
        elif readiness.export()["state"] != "READY":
            status = "API_OR_DOM_NOT_READY"
        elif (steps.get("progress_stage") == "BEFORE_SUGGESTION_CLICK"
              and steps.get("error") is not None):
            # A delivered option click can time out after opening a new
            # region state; this exception must not be mistaken for a
            # failed API or successful server region without a fresh Route.
            status = "REGION_OPTION_ACTION_EXCEPTION"
        elif not valid_click:
            status = "CLICK_NOT_TRUSTED"
        elif (api_ok and route_status == "ONE_FRESH"
              and server_search == "EXPECTED"
              and server_filter == "EXPECTED"
              and ui_region == "EXPECTED"):
            status = "TARGET_REGION_CONFIRMED_DIAGNOSTIC"
        elif (route_status == "ONE_FRESH"
              and server_search == "OTHER"
              and server_filter == "OTHER"
              and ui_region == "OTHER"):
            status = "REGION_NOT_COMMITTED"
        else:
            status = "INCONCLUSIVE"
        row = {
            "mode": mode, "status": status, "input_events": observed_input,
            "input_focus": input_focus,
            "input_value_matches_expected": input_matches,
            "api_ready": readiness.export()["state"] == "READY",
            "api_candidate_matches_expected": api_ok,
            "api_response_count": resolver.responses,
            "native_click": selected, "route_status": route_status,
            "route_responses": len(post),
            "server_search": server_search,
            "server_filter": server_filter, "selected_ui": ui_region,
            "initial_baseline": initial_baseline,
            "header_transition":header_transition,
            "picker_phase_diagnostics":picker_phase.export(
                error=steps.get("error"),
                readiness=readiness.export()["state"],
                core_progress_stage=steps.get("progress_stage"),
                core_header_click_returned=steps.get("clicked_region_button"),
                header_click_verified_after_timeout=steps.get(
                    "header_click_verified_after_timeout"),
                header_click_exception_kind=steps.get(
                    "header_click_exception_kind"),
                header_activation=header_activation_snapshot,
                option_click_returned=steps.get("option_click_returned"),
                option_click_verified_after_timeout=steps.get(
                    "option_click_verified_after_timeout"),
                option_click_exception_kind=steps.get(
                    "option_click_exception_kind")),
        }
        # Only a fully authenticated one-fresh-Route region success can enter
        # an optional, separately approved precollection filter gate. Never
        # interpret picker/URL/UI alone as authorization to inspect listings.
        if on_region_confirmed is not None and (
                status == "TARGET_REGION_CONFIRMED_DIAGNOSTIC"):
            candidate = on_region_confirmed(page, region)
            if asyncio.iscoroutine(candidate):
                candidate = await candidate
            row["precollection"] = candidate
        return sanitize_attempt(row)
    except Exception:
        return sanitize_attempt({"mode": mode, "status": "UNEXPECTED_EXCEPTION",
                                 "input_events": observed_input,
                                 "input_focus": input_focus,
                                 "api_response_count": resolver.responses,
                                 "initial_baseline":initial_baseline,
                                 "header_transition":header_transition,
                                 "picker_phase_diagnostics":picker_phase.export(
                                     error="RuntimeError",
                                     readiness=readiness.export()["state"],
                                     header_activation=header_activation_snapshot)})
    finally:
        if page is not None:
            await header_activation.stop(page)
            if picker_phase_armed:
                page.remove_listener("request", picker_phase.on_request)
                page.remove_listener("response", picker_phase.on_response)
                page.remove_listener("requestfailed", picker_phase.on_requestfailed)
            await input_probe.stop(page)
            await option_probe.stop(page)
            if api_armed:
                page.remove_listener("response", resolver.on_response)
            if request_armed:
                page.remove_listener("request", network.on_request)
            if response_armed:
                page.remove_listener("response", network.on_response)
        await context.close()


async def run(*, live=False, headed=False, egress_context=False):
    from playwright.async_api import async_playwright

    results = {"schema": "chrome_stable_input_comparison_v1",
               "browser": "GOOGLE_CHROME_STABLE",
               "profile": "DISPOSABLE",
               "headless": not headed, "fixture": [], "public_site": [],
               "delegated_manual_fixture": {},
               "machine":safe_machine_class(),
               "egress":optional_egress_context(enabled=False),
               "authorizes_listings": False}
    if live:
        if (not check_public_robots()
                or check_region_picker_robots(
                    core.BY_KEY["cheonan"]["term"]).get("allowed") is not True):
            results["public_site"] = [{"status": "ACCESS_RESTRICTED",
                                       "authorizes_listings": False}]
            return results
    if live and egress_context:
        results["egress"] = await asyncio.to_thread(
            optional_egress_context,enabled=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            channel="chrome", headless=not headed)
        try:
            for mode in _MODES:
                results["fixture"].append(await one_fixture(browser, mode))
            results["delegated_manual_fixture"] = await delegated_manual_fixture(browser)
            if live:
                for mode in _MODES:
                    row = await one_public_region(browser, mode)
                    results["public_site"].append(row)
                    # Never retry, or continue on a rejected/challenged site.
                    if row["status"] in ("ACCESS_RESTRICTED", "BASELINE_INVALID",
                                         "UNEXPECTED_EXCEPTION"):
                        break
        finally:
            await browser.close()
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="One owner-approved, robots-checked comparison")
    parser.add_argument("--headed", action="store_true",
                        help="Run Chrome Stable in a headed virtual display")
    parser.add_argument("--owner-approval", default="")
    parser.add_argument("--egress-context",action="store_true",
        help="Opt-in third-party egress country/provider estimate (no raw IP output)")
    args = parser.parse_args(argv)
    if args.egress_context and not args.live:
        print("EGRESS_CONTEXT_REQUIRES_LIVE_OPT_IN")
        return 2
    if args.live and args.owner_approval != _APPROVAL:
        print("MISSING_EXACT_OWNER_APPROVAL")
        return 2
    try:
        result = asyncio.run(run(live=args.live, headed=args.headed,
                                 egress_context=args.egress_context))
    except Exception:
        print("CHROME_STABLE_COMPARISON_FAILED")
        return 2
    # Contents have passed explicit enum/counter sanitizers.
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if (len(result["fixture"]) != 2 or
            any(x["status"] != "FIXTURE_COMPLETE"
                or not x["input_events"]["armed"]
                for x in result["fixture"])
            or result["delegated_manual_fixture"].get("armed") is not True
            or result["delegated_manual_fixture"].get("observed_input") is not True
            or result["delegated_manual_fixture"].get(
                "preserved_after_dialog_removal") is not True):
        return 2
    if args.live and len(result["public_site"]) != 2:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
