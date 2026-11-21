from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import telemetry_store


class CompactionTelemetryTests(unittest.TestCase):
    """R&D validation 2026-11-21: a context_compaction row recorded only its name, not what was done."""

    def test_compaction_row_keeps_stage_and_token_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(telemetry_store, "DB_PATH", Path(folder) / "traces.sqlite3"), \
                    patch.object(telemetry_store, "_SCHEMA_READY", False):
                telemetry_store.save_event({
                    "event": "context_compaction", "request_id": "r1", "stage": "pruned",
                    "tokens_before": 30120, "tokens_after": 21004, "threshold_tokens": 24576,
                    "pruned": 7, "summarised": 0,
                })
                with closing(telemetry_store._open()) as connection:
                    row = connection.execute("SELECT status, reason FROM events WHERE event = 'context_compaction'").fetchone()
        self.assertEqual(row["status"], "pruned")
        self.assertEqual(row["reason"], "30120 -> 21004 estimated tokens (threshold 24576); pruned 7, summarised 0")


if __name__ == "__main__":
    unittest.main()
