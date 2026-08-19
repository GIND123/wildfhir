import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aquafhir.models import (
    Alert,
    ChainVerification,
    MappingProposal,
    ProvenanceEntry,
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
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    document TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
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

    def list_proposals(self, limit: int = 100) -> list[MappingProposal]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT document FROM proposals ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [MappingProposal.model_validate_json(row["document"]) for row in rows]

    def save_observation(self, proposal_id: str, observation: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO observations(id, proposal_id, document, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET document = excluded.document""",
                (observation["id"], proposal_id, _canonical(observation), now),
            )

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
