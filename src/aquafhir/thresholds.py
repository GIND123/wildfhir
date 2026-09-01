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
        """
        parsed = _readable_quantity(observation)
        if parsed is None:
            return []
        code, unit, value, observation_id, site_code, effective = parsed

        alerts: list[Alert] = []
        for rule in self.rules:
            if rule["code"] != code or rule["unit"] != unit:
                continue
            comparison = OPERATORS[rule["operator"]]
            if comparison(value, float(rule["value"])):
                stable_key = f"{observation_id}|{self.policy_id}|{rule['code']}"
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
                        site_code=site_code,
                        observed_at=effective,
                    )
                )
        return alerts


def _readable_quantity(
    observation: dict[str, Any],
) -> tuple[str, str, float, str, str, datetime] | None:
    """Pull the six fields the policy needs, or None if the resource is unusable.

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

    quantity = observation.get("valueQuantity") or {}
    if not isinstance(quantity, dict):
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

    observation_id = observation.get("id")
    if not isinstance(observation_id, str) or not observation_id:
        return None

    subject = observation.get("subject") or {}
    reference = subject.get("reference") if isinstance(subject, dict) else None
    site_code = (reference or "Location/unknown").rsplit("/", 1)[-1]

    effective = _parse_effective(observation.get("effectiveDateTime"))
    if effective is None:
        return None
    return code, unit, value, observation_id, site_code, effective


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
