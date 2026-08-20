import operator
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import yaml

from aquafhir.models import Alert

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
        coding = observation.get("code", {}).get("coding", [])
        quantity = observation.get("valueQuantity", {})
        if not coding or "value" not in quantity or "code" not in quantity:
            return []
        code = coding[0].get("code")
        unit = quantity["code"]
        value = float(quantity["value"])
        subject = observation.get("subject", {}).get("reference", "Location/unknown")
        site_code = subject.rsplit("/", 1)[-1]
        effective = datetime.fromisoformat(observation["effectiveDateTime"].replace("Z", "+00:00"))

        alerts: list[Alert] = []
        for rule in self.rules:
            if rule["code"] != code or rule["unit"] != unit:
                continue
            comparison = OPERATORS[rule["operator"]]
            if comparison(value, float(rule["value"])):
                stable_key = f"{observation['id']}|{self.policy_id}|{rule['code']}"
                alerts.append(
                    Alert(
                        id=str(uuid5(NAMESPACE_URL, stable_key)),
                        observation_id=observation["id"],
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

