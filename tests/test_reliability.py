from __future__ import annotations

import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from channel import Stream
from utils import json_load, json_save


class JsonReliabilityTests(unittest.TestCase):
    def test_save_keeps_previous_valid_file_as_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "settings.json")

            json_save(path, {"value": 1})
            json_save(path, {"value": 2})

            self.assertEqual(json.loads(path.read_text(encoding="utf8")), {"value": 2})
            self.assertEqual(
                json.loads(path.with_name("settings.json.bak").read_text(encoding="utf8")),
                {"value": 1},
            )

    def test_load_recovers_corrupt_main_file_without_consuming_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "settings.json")
            backup_path = path.with_name("settings.json.bak")
            path.write_text("{broken", encoding="utf8")
            backup_path.write_text('{"value": 7}', encoding="utf8")

            loaded = json_load(path, {"value": 0})

            self.assertEqual(loaded, {"value": 7})
            self.assertEqual(json.loads(path.read_text(encoding="utf8")), {"value": 7})
            self.assertEqual(json.loads(backup_path.read_text(encoding="utf8")), {"value": 7})

    def test_load_promotes_completed_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "settings.json")
            new_path = path.with_name("settings.json.new")
            path.write_text('{"value": 1}', encoding="utf8")
            new_path.write_text('{"value": 2}', encoding="utf8")

            loaded = json_load(path, {"value": 0})

            self.assertEqual(loaded, {"value": 2})
            self.assertFalse(new_path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf8")), {"value": 2})


class StreamPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        twitch = SimpleNamespace(
            settings=SimpleNamespace(available_drops_check=False),
            _auth_state=SimpleNamespace(user_id="42"),
        )
        channel = SimpleNamespace(id=123, _login="example", _twitch=twitch)
        self.stream = Stream(
            channel,
            id=456,
            game={"id": "789", "name": "Example Game"},
            viewers=10,
            title="Example",
        )

    def test_spade_payload_refreshes_client_time(self) -> None:
        with patch("channel.isonow", side_effect=["first", "second"]):
            first = json.loads(base64.b64decode(self.stream.spade_payload["data"]))
            second = json.loads(base64.b64decode(self.stream.spade_payload["data"]))

        self.assertEqual(first[0]["properties"]["client_time"], "first")
        self.assertEqual(second[0]["properties"]["client_time"], "second")

    def test_gql_payload_contains_current_watch_event(self) -> None:
        with patch("channel.isonow", return_value="now"):
            payload = self.stream.gql_payload

        encoded = payload["variables"]["input"]["data"]
        event = json.loads(gzip.decompress(base64.b64decode(encoded)))
        self.assertEqual(event[0]["properties"]["client_time"], "now")
        self.assertEqual(event[0]["properties"]["broadcast_id"], "456")

if __name__ == "__main__":
    unittest.main()
