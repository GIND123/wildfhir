import logging
import math
import operator
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import yaml

from aquafhir.models import Alert

logger = logging.getLogger(__name__)

OPERATORS: dict[str, Callable[[float, float], bool]] = {
    "gte": operator.ge,
    "gt": operator.gt,
    "lte": operator.le,
    "lt": operator.lt,
}
# Operators for coded values. A rule with one lists `values`, not `value`/`unit`.
CODED_OPERATORS = {"in", "not-in"}


class ThresholdPolicy:
    def __init__(self, path: Path | str) -> None:
        document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        self.policy_id: str = document["policy_id"]
        self.status: str = document["policy_status"]
        self.rules: list[dict[str, Any]] = document["rules"]

    def evaluate(self, observation: dict[str, Any]) -> list[Alert]:
        """Evaluate one Observation against the policy.

        Observations arrive here from two places: our own approval pipeline,
        where the shape is guaranteed, and a FHIR rest-hook Subscription,
        where the server decides the shape. A resource we cannot read is not
        an alert and must never be a 500 -- it is skipped with a log line.

        A quantity rule only ever compares against `valueQuantity`; a coded
        rule only ever looks at `valueCodeableConcept`. Neither can be fooled
        into firing by the other value type.
        """
        header = _readable_header(observation)
        if header is None:
            return []
        code, observation_id, site_code, effective = header
        quantity = _readable_quantity(observation)
        coded = _readable_coded_value(observation)
        if quantity is None and coded is None:
            return []

        alerts: list[Alert] = []
        for rule in self.rules:
            if rule["code"] != code:
                continue
            fired = False
            value: float | None = None
            unit = ""
            value_code: str | None = None
            if rule["operator"] in CODED_OPERATORS:
                if coded is None:
                    continue
                wanted = {str(item) for item in rule.get("values", [])}
                hit = coded in wanted
                fired = hit if rule["operator"] == "in" else not hit
                value_code = coded
            else:
                if quantity is None or rule["unit"] != quantity[0]:
                    continue
                unit, value = quantity
                fired = OPERATORS[rule["operator"]](value, float(rule["value"]))
            if not fired:
                continue
            # A policy may carry more than one rule for the same code (a
            # low and a high bound, say). `id` disambiguates them so two
            # rules that fire together cannot collide onto one alert id.
            # Rules without an explicit `id` keep their historical id.
            rule_key = rule.get("id", rule["code"])
            stable_key = f"{observation_id}|{self.policy_id}|{rule_key}"
            alerts.append(
                Alert(
                    id=str(uuid5(NAMESPACE_URL, stable_key)),
                    observation_id=observation_id,
                    policy_id=self.policy_id,
                    rule_code=rule["code"],
                    severity=rule["severity"],
                    message=rule["message"],
                    audiences=rule["audiences"],
                    value=value,
                    unit=unit,
                    value_code=value_code,
                    site_code=site_code,
                    observed_at=effective,
                )
            )
        return alerts


def _readable_header(
    observation: dict[str, Any],
) -> tuple[str, str, str, datetime] | None:
    """The code, id, site and time every rule needs, or None if unusable.

    Every lookup tolerates a missing key, an explicit JSON null, and a wrong
    type, because none of those are under this service's control.
    """
    code_block = observation.get("code") or {}
    if not isinstance(code_block, dict):
        return None
    coding = code_block.get("coding") or []
    if not isinstance(coding, list) or not coding or not isinstance(coding[0], dict):
        return None
    code = coding[0].get("code")
    if not isinstance(code, str) or not code:
        return None

    observation_id = observation.get("id")
    if not isinstance(observation_id, str) or not observation_id:
        return None

    subject = observation.get("subject") or {}
    reference = subject.get("reference") if isinstance(subject, dict) else None
    site_code = (reference or "Location/unknown").rsplit("/", 1)[-1]

    effective = _parse_effective(observation.get("effectiveDateTime"))
    if effective is None:
        return None
    return code, observation_id, site_code, effective


def _readable_quantity(observation: dict[str, Any]) -> tuple[str, float] | None:
    """(unit, value) from `valueQuantity`, or None if absent or unusable."""
    quantity = observation.get("valueQuantity") or {}
    if not isinstance(quantity, dict) or not quantity:
        return None
    unit = quantity.get("code")
    raw_value = quantity.get("value")
    if not isinstance(unit, str) or not unit:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
        return None
    value = float(raw_value)
    if not math.isfinite(value):
        logger.warning("Skipping Observation with non-finite value: %r", raw_value)
        return None
    return unit, value


def _readable_coded_value(observation: dict[str, Any]) -> str | None:
    """The first coding's code from `valueCodeableConcept`, or None."""
    concept = observation.get("valueCodeableConcept") or {}
    if not isinstance(concept, dict):
        return None
    codings = concept.get("coding") or []
    if not isinstance(codings, list) or not codings or not isinstance(codings[0], dict):
        return None
    code = codings[0].get("code")
    return code if isinstance(code, str) and code else None


def _parse_effective(raw: Any) -> datetime | None:
    """FHIR `dateTime` allows YYYY, YYYY-MM, and YYYY-MM-DD as well as instants."""
    if not isinstance(raw, str) or not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue
    logger.warning("Skipping Observation with unparseable effectiveDateTime: %r", raw)
    return None
