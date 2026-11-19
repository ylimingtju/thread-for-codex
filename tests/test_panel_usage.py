"""Model attribution and incremental reading of Codex token-count events."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "codex-director"))
from panel_usage import usage_for_threads


def event(at, kind, payload):
    stamp = datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="milliseconds")
    return json.dumps({"timestamp": stamp, "type": kind, "payload": payload}) + "\n"


def turn(at, model, *, context_at=None):
    turn_id = f"turn-{at}"
    started = event(at, "event_msg", {"type": "task_started", "turn_id": turn_id})
    return started + event(context_at or at, "turn_context", {"model": model, "turn_id": turn_id})


def tokens(at, cumulative, last):
    def counts(pair):
        inp, out = pair
        return {"input_tokens": inp, "cached_input_tokens": inp // 2, "output_tokens": out,
                "reasoning_output_tokens": out // 2, "total_tokens": inp + out}
    return event(at, "event_msg", {"type": "token_count", "info": {
        "total_token_usage": counts(cumulative), "last_token_usage": counts(last)}})


def model_counts(result):
    return {r["model"]: (r["input_tokens"], r["output_tokens"], r["total_tokens"])
            for r in result["models"]}


class TokenUsage(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.log = Path(directory.name) / "rollout.jsonl"

    def test_model_switch_and_cutoff(self):
        # An old-chat turn can finish after the first dispatch. Its tokens stay in the old turn.
        self.log.write_text(turn(9, "gpt-6.2-sol", context_at=11) + tokens(12, (400, 40), (400, 40))
                            + turn(20.125, "gpt-6.2-astra") + tokens(21, (420, 48), (20, 8))
                            + tokens(22, (420, 48), (20, 8))
                            + turn(30, "gpt-6.2-sol") + tokens(31, (424, 48), (4, 0)))
        other = self.log.with_name("other.jsonl")
        other.write_text(turn(20, "gpt-6.2-astra") + tokens(24, (3, 2), (3, 2)))
        result = usage_for_threads([(str(self.log), 10.9), (str(other), None)])
        self.assertEqual(model_counts(result), {"gpt-6.2-sol": (4, 0, 4), "gpt-6.2-astra": (23, 10, 33)})
        self.assertEqual((result["input_tokens"], result["output_tokens"], result["total_tokens"]),
                         (27, 10, 37))
        self.assertFalse(result["partial"])
        self.assertEqual(usage_for_threads([(str(self.log), None)])["total_tokens"], 472)

    def test_append_truncate_and_missing_source(self):
        self.log.write_text(turn(10, "gpt-6.2-sol") + tokens(11, (7, 2), (7, 2)))
        source = [(str(self.log), None)]
        self.assertEqual(usage_for_threads(source)["total_tokens"], 9)
        line = tokens(12, (10, 3), (3, 1))
        with self.log.open("a") as stream:
            stream.write(line[:30])
        self.assertEqual(usage_for_threads(source)["total_tokens"], 9)
        with self.log.open("a") as stream:
            stream.write(line[30:])
        result = usage_for_threads(source + [(None, None)])
        self.assertTrue(result["partial"])
        self.assertEqual(model_counts(result), {"gpt-6.2-sol": (10, 3, 13)})
        self.log.write_text(turn(40, "gpt-6.2-astra") + tokens(41, (2, 1), (2, 1)))
        self.assertEqual(model_counts(usage_for_threads(source)), {"gpt-6.2-astra": (2, 1, 3)})
        self.log.unlink()
        result = usage_for_threads(source)
        self.assertEqual(result["models"], [])
        self.assertTrue(result["partial"])

    def test_unknown_model_and_empty_rollout(self):
        self.log.write_text("")
        sources = [(str(self.log), None)]
        self.assertEqual(usage_for_threads(sources)["models"], [])
        self.log.write_text(tokens(11, (2, 1), (2, 1)))
        self.assertEqual(model_counts(usage_for_threads(sources)), {"unknown": (2, 1, 3)})


if __name__ == "__main__":
    unittest.main()
