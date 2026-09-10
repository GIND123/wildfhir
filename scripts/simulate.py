#!/usr/bin/env python3
"""Drive the incident catalogue through a running AquaFHIR Bridge.

`tests/test_incidents.py` proves the pipeline logic offline. This script proves
the *deployed* system: it talks to the real HTTP surface, so it exercises
FastAPI validation, the SQLite repository, the hash chain, FHIR publication (or
dry-run), and -- when a key is present -- the Gemini co-pilot and the terminology
crosswalk, none of which the offline suite touches end to end.

    uvicorn aquafhir.main:app --reload          # in another terminal
    python scripts/simulate.py                  # every scenario
    python scripts/simulate.py oder-2022 seine-2024
    python scripts/simulate.py --list
    python scripts/simulate.py --propose-only   # fill the review queue, decide by hand
    python scripts/simulate.py --brief          # also draft one advisory per alert

Exit status is 0 only when every scenario matched its documented outcome, so
this is usable as a release gate.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "incidents" / "scenarios.yaml"
REVIEWER = "simulation@aquafhir.example"

BOLD, DIM, RED, GREEN, YELLOW, CYAN, RESET = (
    "\033[1m",
    "\033[2m",
    "\033[31m",
    "\033[32m",
    "\033[33m",
    "\033[36m",
    "\033[0m",
)


def paint(text: str, colour: str) -> str:
    return text if not sys.stdout.isatty() else f"{colour}{text}{RESET}"


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    coded: int = 0
    blocked_qty: int = 0
    no_code: int = 0
    approved: int = 0
    refused: int = 0
    alerts: list[dict[str, Any]] = field(default_factory=list)
    briefings: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


# -- helpers ----------------------------------------------------------------


def load_scenarios() -> list[dict[str, Any]]:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))["scenarios"]


def read_rows(dataset: str) -> list[dict[str, str]]:
    with (ROOT / dataset).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def to_reading(row: dict[str, str], dataset: str) -> dict[str, Any]:
    """One fixture row as the API body. A row carries a value+unit or a coded_value."""
    evidence = (row.get("evidence_url") or "").strip()
    coded = (row.get("coded_value") or "").strip()
    raw_value = (row.get("value") or "").strip()
    return {
        "source_id": row["source_id"],
        "source_type": row["source_type"],
        "parameter": row["parameter"],
        **({"coded_value": coded} if coded else {"value": float(raw_value), "unit": row["unit"]}),
        "observed_at": row["observed_at"],
        "site_code": row["site_code"],
        "site_name": row["site_name"],
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        **({"evidence_url": evidence} if evidence else {}),
        "raw_payload": {"incident_fixture": dataset, "synthetic": True},
    }


def classify(proposal: dict[str, Any]) -> str:
    if not proposal.get("coding"):
        return "no_code"
    quantity = proposal.get("normalized_value") is not None and proposal.get("normalized_unit")
    if not quantity and not proposal.get("normalized_coding"):
        return "blocked_qty"
    return "coded"


# -- one scenario -----------------------------------------------------------


def run_scenario(
    client: httpx.Client,
    scenario: dict[str, Any],
    *,
    propose_only: bool,
    brief: bool,
    verbose: bool,
) -> ScenarioResult:
    result = ScenarioResult(scenario["id"], scenario["title"])
    expected = scenario["expect"]
    rows = read_rows(scenario["dataset"])

    approvable: list[dict[str, Any]] = []
    for row in rows:
        response = client.post("/api/v1/proposals", json=to_reading(row, scenario["dataset"]))
        if response.status_code != 201:
            result.problems.append(
                f"ingest of {row['parameter']!r} returned {response.status_code}: "
                f"{response.text[:160]}"
            )
            continue
        proposal = response.json()
        state = classify(proposal)
        setattr(result, state, getattr(result, state) + 1)
        if state == "coded":
            approvable.append(proposal)
        if verbose:
            mark = {"coded": GREEN, "blocked_qty": YELLOW, "no_code": RED}[state]
            code = (proposal.get("coding") or {}).get("code", "-")
            proposer = proposal["proposer"]
            label = f"{state:11}"
            shown_value = row.get("coded_value") or row.get("value") or ""
            shown_unit = "coded" if row.get("coded_value") else (row.get("unit") or "")
            print(
                f"      {paint(label, mark)} {row['parameter'][:32]:32} "
                f"{shown_value:>10} {shown_unit[:12]:12} -> {code:24} "
                f"{paint(proposer, DIM)}"
            )

    if propose_only:
        return _check(result, expected, skip_alerts=True)

    for proposal in approvable:
        approval = client.post(
            f"/api/v1/proposals/{proposal['id']}/approve", json={"reviewer": REVIEWER}
        )
        if approval.status_code != 200:
            result.problems.append(
                f"approve of {proposal['id'][:8]} returned {approval.status_code}: "
                f"{approval.text[:160]}"
            )
            continue
        result.approved += 1
        result.alerts.extend(approval.json()["alerts"])

    # Anything the pipeline refused is rejected with a reason, so the queue ends
    # empty and the refusal itself lands in the hash chain.
    pending = client.get("/api/v1/proposals", params={"limit": 500}).json()
    for proposal in pending:
        if proposal["status"] != "pending":
            continue
        reason = (
            "No OAH code: concept absent from the temporary code system."
            if not proposal.get("coding")
            else "Quantity withheld: unresolvable unit or implausible value. "
            "Needs source correction."
        )
        rejection = client.post(
            f"/api/v1/proposals/{proposal['id']}/reject",
            json={"reviewer": REVIEWER, "reason": reason},
        )
        if rejection.status_code == 200:
            result.refused += 1

    if brief:
        seen: set[str] = set()
        for alert in result.alerts:
            if alert["id"] in seen:
                continue
            seen.add(alert["id"])
            audience = alert["audiences"][0]
            drafted = client.post(
                f"/api/v1/alerts/{alert['id']}/briefings", params={"audience": audience}
            )
            if drafted.status_code == 201:
                result.briefings += 1
            elif drafted.status_code == 503:
                result.problems.append("advisory drafting needs GEMINI_API_KEY (--brief)")
                break

    return _check(result, expected, skip_alerts=False)


def _check(
    result: ScenarioResult, expected: dict[str, Any], *, skip_alerts: bool
) -> ScenarioResult:
    for key in ("coded", "blocked_qty", "no_code"):
        actual = getattr(result, key)
        if actual != expected[key]:
            result.problems.append(f"{key}: expected {expected[key]}, got {actual}")

    if skip_alerts:
        return result

    fired = {(alert["rule_code"], alert["severity"]) for alert in result.alerts}
    documented = {(rule["code"], rule["severity"]) for rule in expected["alerts"]}
    if fired != documented:
        missing = sorted(documented - fired)
        extra = sorted(fired - documented)
        if missing:
            result.problems.append(f"alerts not raised: {missing}")
        if extra:
            result.problems.append(f"unexpected alerts: {extra}")

    routed = sorted({a for alert in result.alerts for a in alert["audiences"]})
    if routed != sorted(expected["audiences"]):
        result.problems.append(
            f"audiences: expected {sorted(expected['audiences'])}, got {routed}"
        )
    return result


# -- entry point ------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("scenarios", nargs="*", help="scenario ids (default: all)")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument(
        "--propose-only",
        action="store_true",
        help="fill the review queue and stop, so a person can decide in the console",
    )
    parser.add_argument(
        "--brief", action="store_true", help="draft one advisory per alert (needs GEMINI_API_KEY)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print every reading")
    args = parser.parse_args()

    catalogue = load_scenarios()
    if args.list:
        for scenario in catalogue:
            print(f"  {scenario['id']:22} {scenario['title']}")
        return 0

    wanted = args.scenarios or [scenario["id"] for scenario in catalogue]
    unknown = set(wanted) - {scenario["id"] for scenario in catalogue}
    if unknown:
        print(f"unknown scenario(s): {sorted(unknown)}", file=sys.stderr)
        return 2
    selected = [scenario for scenario in catalogue if scenario["id"] in wanted]

    with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
        try:
            health = client.get("/api/v1/health").json()
        except httpx.HTTPError as error:
            print(
                f"{paint('cannot reach the bridge', RED)} at {args.base_url}: {error}\n"
                "Start it with:  uvicorn aquafhir.main:app --reload",
                file=sys.stderr,
            )
            return 2

        print(paint("\nAquaFHIR Bridge — incident simulation", BOLD))
        print(
            f"  {DIM}bridge{RESET}      {args.base_url}\n"
            f"  {DIM}fhir write{RESET}  {health['fhir_write_mode']}\n"
            f"  {DIM}ai mode{RESET}     {health['ai_mode']}"
            f"{' · ' + str(health['ai_model']) if health.get('ai_model') else ''}\n"
            f"  {DIM}crosswalk{RESET}   {health['terminology_crosswalk']}\n"
            f"  {DIM}policy{RESET}      {health['threshold_policy']} "
            f"({health['threshold_policy_status']})\n"
        )

        results: list[ScenarioResult] = []
        for scenario in selected:
            print(
                f"{paint('>', CYAN)} {paint(scenario['id'], BOLD)}  "
                f"{DIM}{scenario['title']}{RESET}"
            )
            result = run_scenario(
                client,
                scenario,
                propose_only=args.propose_only,
                brief=args.brief,
                verbose=args.verbose,
            )
            results.append(result)
            status = paint("PASS", GREEN) if result.ok else paint("FAIL", RED)
            print(
                f"      {status}  coded {result.coded}  blocked {result.blocked_qty}  "
                f"no-code {result.no_code}  approved {result.approved}  "
                f"refused {result.refused}  alerts {len(result.alerts)}"
                + (f"  advisories {result.briefings}" if args.brief else "")
            )
            summary = {
                (a["rule_code"], a["severity"], tuple(a["audiences"])) for a in result.alerts
            }
            for code, severity, audiences in sorted(summary):
                print(f"         {DIM}-{RESET} {severity:8} {code:24} -> {', '.join(audiences)}")
            for problem in result.problems:
                print(f"         {paint('✗', RED)} {problem}")
            print()

        chain = client.get("/api/v1/provenance/verify").json()
        events = client.get("/api/v1/provenance", params={"limit": 500}).json()

    passed = sum(1 for item in results if item.ok)
    print(paint("Summary", BOLD))
    print(f"  scenarios      {passed}/{len(results)} matched the documented outcome")
    print(f"  alerts raised  {sum(len(item.alerts) for item in results)}")
    built = sum(item.approved for item in results)
    sent = health["fhir_write_mode"] == "enabled"
    print(
        f"  approved       {built}"
        f" ({'published to FHIR' if sent else 'built locally, not sent: dry run'})"
    )
    print(f"  refused        {sum(item.refused for item in results)}")
    print(
        f"  audit chain    {paint('VALID', GREEN) if chain['valid'] else paint('INVALID', RED)}"
        f" over {chain['entries_checked']} entries"
    )
    kinds: dict[str, int] = {}
    for event in events:
        kinds[event["event_type"]] = kinds.get(event["event_type"], 0) + 1
    print(f"  chain events   {', '.join(f'{k}×{v}' for k, v in sorted(kinds.items()))}\n")

    if passed != len(results) or not chain["valid"]:
        print(paint("Some scenarios did not match docs/incidents.md.", RED))
        return 1
    print(paint("Every scenario matched docs/incidents.md.", GREEN))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
