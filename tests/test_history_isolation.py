import os
import tempfile
import unittest

from backend import config
from backend.crdt import BoardDoc, make_op, validate_op
from backend.history import BoardHistory, SHARD_META_CACHE


class HistoryIsolationTests(unittest.TestCase):
    def setUp(self):
        self._old_data_dir = config.DATA_DIR
        self._old_boards_dir = config.BOARDS_DIR
        self.tmp = tempfile.TemporaryDirectory(prefix="wb-history-tests-")
        config.DATA_DIR = self.tmp.name
        config.BOARDS_DIR = os.path.join(self.tmp.name, "boards")
        SHARD_META_CACHE.clear()

    def tearDown(self):
        config.DATA_DIR = self._old_data_dir
        config.BOARDS_DIR = self._old_boards_dir
        SHARD_META_CACHE.clear()
        self.tmp.cleanup()

    @staticmethod
    def op(board, rev, ts, op_type="add_shape"):
        if op_type == "add_shape":
            payload = {
                "shape": {
                    "id": f"{board}-shape-{rev}", "kind": "rect",
                    "x": rev, "y": rev + 1, "w": 10, "h": 10,
                }
            }
        else:
            payload = {"id": f"{board}-shape", "dx": rev, "dy": 0}
        op = make_op(op_type, f"site-{board}", rev, payload, seq=rev, ts=ts)
        op["rev"] = rev
        op["by"] = board
        return op

    def test_same_hour_shards_are_isolated_and_counts_are_not_bytes(self):
        ts = 1_700_000_000_000
        expected = {"A": 2, "B": 5}
        histories = {}

        for board, count in expected.items():
            hist = BoardHistory(f"board-{board}")
            hist.append_ops([self.op(board, i, ts + i) for i in range(1, count + 1)])
            histories[board] = hist

        # Populate the in-memory metadata cache for both boards. Their shard
        # names intentionally collide, but their metadata must not.
        indexes = {board: hist.shards_index() for board, hist in histories.items()}
        self.assertEqual([m["name"] for m in indexes["A"]],
                         [m["name"] for m in indexes["B"]])
        self.assertEqual(indexes["A"][0]["count"], 2)
        self.assertEqual((indexes["A"][0]["first_rev"], indexes["A"][0]["last_rev"]), (1, 2))
        self.assertEqual(indexes["B"][0]["count"], 5)
        self.assertEqual((indexes["B"][0]["first_rev"], indexes["B"][0]["last_rev"]), (1, 5))

        self.assertEqual(histories["A"].op_stats()["total"], 2)
        self.assertEqual(histories["B"].op_stats()["total"], 5)
        self.assertEqual({op["by"] for op in histories["B"].iter_ops(0)}, {"B"})

    def test_move_ops_are_readable_from_persistent_history(self):
        ts = 1_700_003_000_000
        hist = BoardHistory("board-moves")
        hist.append_ops([self.op("moves", 1, ts, "move")])

        records = hist.iter_ops(0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["type"], "move")
        self.assertEqual(records[0]["dx"], 1)
        self.assertEqual(hist.op_stats()["total"], 1)

    def test_move_uses_dx_for_x_and_allows_axis_aligned_drag(self):
        op = validate_op(make_op("move", "site", 1, {"id": "shape", "dx": 3, "dy": 0}, seq=1))
        self.assertIsNotNone(op)
        doc = BoardDoc("board")
        doc.apply_op(op)
        self.assertEqual(doc.shapes["shape"]["x"], 3)
        self.assertEqual(doc.shapes["shape"]["y"], 0)

    def test_metadata_cache_invalidates_after_append(self):
        ts = 1_700_000_000_000
        hist = BoardHistory("board-live")
        hist.append_ops([self.op("live", 1, ts)])
        self.assertEqual(hist.shards_index()[0]["count"], 1)

        hist.append_ops([self.op("live", 2, ts + 1000)])
        meta = hist.shards_index()[0]
        self.assertEqual(meta["count"], 2)
        self.assertEqual(meta["last_rev"], 2)


if __name__ == "__main__":
    unittest.main()
