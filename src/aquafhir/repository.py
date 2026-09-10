import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aquafhir.models import (
    Alert,
    AlertBriefing,
    ChainVerification,
    MappingProposal,
    ProvenanceEntry,
    UnitSuggestionResult,
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Repository:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL UNIQUE,
                    document TEXT NOT NULL,
                    receipt TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS briefings (
                    id TEXT PRIMARY KEY,
                    alert_id TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_briefings_alert
                    ON briefings(alert_id);
                CREATE INDEX IF NOT EXISTS idx_observations_created
                    ON observations(created_at);
                CREATE TABLE IF NOT EXISTS cursors (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS provenance (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            # Databases created before the FHIR receipt was persisted predate
            # the column. Adding it here keeps them readable without a manual
            # migration step; SQLite has no IF NOT EXISTS for ADD COLUMN.
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(observations)").fetchall()
            }
            if "receipt" not in columns:
                connection.execute("ALTER TABLE observations ADD COLUMN receipt TEXT")

    def save_proposal(self, proposal: MappingProposal) -> None:
        document = proposal.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO proposals(id, document, created_at) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET document = excluded.document""",
                (proposal.id, _canonical(document), proposal.created_at.isoformat()),
            )

    def get_proposal(self, proposal_id: str) -> MappingProposal | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        return MappingProposal.model_validate_json(row["document"]) if row else None

    def save_unit_suggestion(
        self, proposal_id: str, code: str, result: UnitSuggestionResult
    ) -> UnitSuggestionResult | None:
        """Merge without allowing a slow AI request to reopen a decided proposal."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT document FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if not row:
                return None
            proposal = MappingProposal.model_validate_json(row["document"])
            if proposal.status.value != "pending":
                return None
            existing = proposal.unit_suggestions.get(code)
            if existing and existing.status != "unavailable":
                return existing
            proposal.unit_suggestions[code] = result
            connection.execute(
                "UPDATE proposals SET document = ? WHERE id = ?",
                (_canonical(proposal.model_dump(mode="json")), proposal_id),
            )
            return result

    def list_proposals(self, limit: int = 100) -> list[MappingProposal]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document FROM proposals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [MappingProposal.model_validate_json(row["document"]) for row in rows]

    def save_observation(
        self,
        proposal_id: str,
        observation: dict[str, Any],
        receipt: dict[str, Any] | None = None,
    ) -> None:
        """Store the published resource and the server's answer to it.

        The receipt is kept so the console can show what actually happened at
        approval time after a reload, instead of only within the session that
        performed it.
        """
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO observations(id, proposal_id, document, receipt, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    document = excluded.document, receipt = excluded.receipt""",
                (
                    observation["id"],
                    proposal_id,
                    _canonical(observation),
                    _canonical(receipt) if receipt is not None else None,
                    now,
                ),
            )

    def get_observation_for_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """The stored resource and receipt for one proposal, or None."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document, receipt FROM observations WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "observation": json.loads(row["document"]),
            "fhir_response": json.loads(row["receipt"]) if row["receipt"] else None,
        }

    def find_duplicate(self, proposal: MappingProposal) -> str | None:
        """Id of an earlier proposal carrying an identical reading, if any.

        Exact match on the six fields that identify a measurement event. Two
        different values reported for the same site, parameter and instant are
        deliberately *not* treated as duplicates: that is a conflict for a
        reviewer to see, not something to merge away.
        """
        reading = proposal.reading
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, document FROM proposals WHERE id != ? ORDER BY created_at",
                (proposal.id,),
            ).fetchall()
        for row in rows:
            other = MappingProposal.model_validate_json(row["document"]).reading
            if (
                other.source_id == reading.source_id
                and other.site_code == reading.site_code
                and other.parameter == reading.parameter
                and other.observed_at == reading.observed_at
                and other.value == reading.value
                and other.unit == reading.unit
            ):
                return row["id"]
        return None

    def save_alert(self, alert: Alert) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO alerts(id, document, created_at) VALUES (?, ?, ?)",
                (alert.id, _canonical(alert.model_dump(mode="json")), alert.created_at.isoformat()),
            )
        return cursor.rowcount == 1

    def list_alerts(self, limit: int = 100) -> list[Alert]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document FROM alerts ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Alert.model_validate_json(row["document"]) for row in rows]

    def get_cursor(self, name: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM cursors WHERE name = ?", (name,)
            ).fetchone()
        return row["value"] if row else None

    def set_cursor(self, name: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO cursors(name, value) VALUES (?, ?)
                ON CONFLICT(name) DO UPDATE SET value = excluded.value""",
                (name, value),
            )

    def append_provenance(
        self, event_type: str, entity_id: str, payload: dict[str, Any]
    ) -> ProvenanceEntry:
        created_at = datetime.now(UTC)
        payload_json = _canonical(payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT hash FROM provenance ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = previous["hash"] if previous else "GENESIS"
            digest_input = "|".join(
                [previous_hash, event_type, entity_id, created_at.isoformat(), payload_json]
            )
            digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
            cursor = connection.execute(
                """INSERT INTO provenance(
                    event_type, entity_id, payload, previous_hash, hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event_type,
                    entity_id,
                    payload_json,
                    previous_hash,
                    digest,
                    created_at.isoformat(),
                ),
            )
            sequence = cursor.lastrowid
        return ProvenanceEntry(
            sequence=sequence,
            event_type=event_type,
            entity_id=entity_id,
            payload=json.loads(payload_json),
            previous_hash=previous_hash,
            hash=digest,
            created_at=created_at,
        )

    def list_provenance(self, limit: int = 100) -> list[ProvenanceEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM provenance ORDER BY sequence DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._provenance_from_row(row) for row in rows]

    def verify_chain(self) -> ChainVerification:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM provenance ORDER BY sequence ASC"
            ).fetchall()
        expected_previous = "GENESIS"
        for count, row in enumerate(rows, start=1):
            digest_input = "|".join(
                [
                    expected_previous,
                    row["event_type"],
                    row["entity_id"],
                    row["created_at"],
                    row["payload"],
                ]
            )
            digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
            if row["previous_hash"] != expected_previous or row["hash"] != digest:
                return ChainVerification(
                    valid=False,
                    entries_checked=count,
                    first_invalid_sequence=row["sequence"],
                )
            expected_previous = row["hash"]
        return ChainVerification(valid=True, entries_checked=len(rows))

    @staticmethod
    def _provenance_from_row(row: sqlite3.Row) -> ProvenanceEntry:
        return ProvenanceEntry(
            sequence=row["sequence"],
            event_type=row["event_type"],
            entity_id=row["entity_id"],
            payload=json.loads(row["payload"]),
            previous_hash=row["previous_hash"],
            hash=row["hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -- alerts, briefings, and observation inventory ----------------------

    def get_alert(self, alert_id: str) -> Alert | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM alerts WHERE id = ?", (alert_id,)
            ).fetchone()
        return Alert.model_validate_json(row["document"]) if row else None

    def save_briefing(self, briefing: AlertBriefing) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO briefings(id, alert_id, audience, document, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET document = excluded.document""",
                (
                    briefing.id,
                    briefing.alert_id,
                    briefing.audience,
                    _canonical(briefing.model_dump(mode="json")),
                    briefing.created_at.isoformat(),
                ),
            )

    def list_briefings(
        self, alert_id: str | None = None, limit: int = 100
    ) -> list[AlertBriefing]:
        query = "SELECT document FROM briefings"
        parameters: tuple[Any, ...] = ()
        if alert_id:
            query += " WHERE alert_id = ?"
            parameters = (alert_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self._connect() as connection:
            rows = connection.execute(query, (*parameters, limit)).fetchall()
        return [AlertBriefing.model_validate_json(row["document"]) for row in rows]

    def get_observation(self, observation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT document FROM observations WHERE id = ?", (observation_id,)
            ).fetchone()
        return json.loads(row["document"]) if row else None

    def list_observations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document FROM observations ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["document"]) for row in rows]

    def observation_summaries(
        self, limit: int = 100, site_code: str | None = None
    ) -> list[dict[str, Any]]:
        """Flatten stored Observations into rows safe to put in a prompt.

        Only fields the pipeline itself produced are exposed. Nothing here is
        free text a source could use to steer a model.
        """
        summaries = [observation_summary(item) for item in self.list_observations(limit)]
        if site_code:
            summaries = [item for item in summaries if item["site_code"] == site_code]
        return summaries

    def count_proposals_by_status(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT json_extract(document, '$.status') AS status, COUNT(*) AS total "
                "FROM proposals GROUP BY status"
            ).fetchall()
        return {row["status"]: row["total"] for row in rows}


def observation_summary(observation: dict[str, Any]) -> dict[str, Any]:
    coding = (observation.get("code", {}).get("coding") or [{}])[0]
    quantity = observation.get("valueQuantity", {})
    tags = observation.get("meta", {}).get("tag") or [{}]
    subject = observation.get("subject", {}).get("reference", "Location/unknown")
    return {
        "observation_id": observation.get("id", "unknown"),
        "code": coding.get("code", "unknown"),
        "display": observation.get("code", {}).get("text", ""),
        "value": quantity.get("value"),
        "unit": quantity.get("code", ""),
        "observed_at": observation.get("effectiveDateTime", ""),
        "site_code": subject.rsplit("/", 1)[-1],
        "source_type": tags[0].get("code", "unknown"),
    }
