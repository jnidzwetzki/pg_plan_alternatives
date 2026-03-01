"""Unit tests for plan visualization deduplication behavior."""

import unittest

from pg_plan_alternatives.visualize_plan_graph import PlanVisualizer


class _Args:
    input = ""
    output = ""
    group_by_pid = False
    verbose = False
    db_url = None


class TestPlanVisualizerDedup(unittest.TestCase):
    def setUp(self):
        self.visualizer = PlanVisualizer(_Args())

    def test_representative_indices_keep_distinct_hashjoin_rti_directions(self):
        events = [
            {
                "timestamp": 100,
                "pid": 1,
                "event_type": "ADD_PATH",
                "path_type": "T_HashJoin",
                "startup_cost": 27.5,
                "total_cost": 45.136125,
                "rows": 1000,
                "parent_rel_oid": 0,
                "join_type": 1,
                "join_type_name": "JOIN_LEFT",
                "outer_rti": 1,
                "inner_rti": 2,
                "outer_rel_oid": 26144,
                "inner_rel_oid": 26149,
            },
            {
                "timestamp": 101,
                "pid": 1,
                "event_type": "ADD_PATH",
                "path_type": "T_HashJoin",
                "startup_cost": 27.5,
                "total_cost": 45.136125,
                "rows": 1000,
                "parent_rel_oid": 0,
                "join_type": 3,
                "join_type_name": "JOIN_RIGHT",
                "outer_rti": 2,
                "inner_rti": 1,
                "outer_rel_oid": 26149,
                "inner_rel_oid": 26144,
            },
        ]

        representative_indices = self.visualizer._representative_event_indices(events)

        kept_pairs = {
            (
                events[index].get("join_type_name"),
                events[index].get("outer_rti"),
                events[index].get("inner_rti"),
            )
            for index in representative_indices
        }

        self.assertEqual(
            kept_pairs,
            {
                ("JOIN_LEFT", 1, 2),
                ("JOIN_RIGHT", 2, 1),
            },
        )


if __name__ == "__main__":
    unittest.main()
