"""
Basic tests for pg_plan_alternatives
"""

import unittest
from pg_plan_alternatives import __version__
from pg_plan_alternatives.helper import NodeTagHelper, BPFHelper, DwarfOffsetHelper
import tempfile
import textwrap
import os
from pathlib import Path


class TestVersion(unittest.TestCase):
    """Test version information"""

    def test_version_exists(self):
        """Test that version is defined"""
        self.assertIsNotNone(__version__)
        self.assertIsInstance(__version__, str)
        self.assertTrue(len(__version__) > 0)


class TestPathTypeHelper(unittest.TestCase):
    """Test PathTypeHelper class"""

    def setUp(self):
        # create a temporary nodetags file with minimal entries used in tests
        self.tmp = tempfile.NamedTemporaryFile("w", delete=False)
        content = textwrap.dedent("""
            /* nodetags.h */
            T_Path = 1,
            T_IndexPath = 2,
            T_HashPath = 13,
        """)
        self.tmp.write(content)
        self.tmp.flush()
        self.tmp.close()
        NodeTagHelper.load_from_file(self.tmp.name)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except Exception:
            pass

    def test_path_type_to_str(self):
        """Test path type to string conversion"""
        self.assertEqual(NodeTagHelper.name_from_value(1), "T_Path")
        self.assertEqual(NodeTagHelper.name_from_value(2), "T_IndexPath")
        self.assertEqual(NodeTagHelper.name_from_value(13), "T_HashPath")

    def test_path_type_to_str_unknown(self):
        """Test unknown path type"""
        result = NodeTagHelper.name_from_value(999)
        self.assertTrue(result.startswith("Unknown"))

    def test_path_type_to_int(self):
        """Test path type name to int conversion"""
        self.assertEqual(NodeTagHelper.value_from_name("T_Path"), 1)
        self.assertEqual(NodeTagHelper.value_from_name("T_IndexPath"), 2)
        self.assertEqual(NodeTagHelper.value_from_name("T_HashPath"), 13)

    def test_path_type_to_int_invalid(self):
        """Test invalid path type name"""
        with self.assertRaises(ValueError):
            NodeTagHelper.value_from_name("InvalidPath")


class TestBPFHelper(unittest.TestCase):
    """Test BPFHelper class"""

    def test_enum_to_defines(self):
        """Test enum to defines conversion"""
        from enum import IntEnum, auto

        class TestEnum(IntEnum):
            FIRST = auto()
            SECOND = auto()

        result = BPFHelper.enum_to_defines(TestEnum, "TEST_")
        self.assertIn("#define TEST_FIRST 1", result)
        self.assertIn("#define TEST_SECOND 2", result)


class TestDwarfOffsetHelper(unittest.TestCase):
    """Test DWARF offset helper mapping utilities."""

    def _valid_struct_members(self):
        return {
            "Path": {
                "pathtype": 4,
                "parent": 8,
                "rows": 40,
                "startup_cost": 48,
                "total_cost": 56,
            },
            "RelOptInfo": {"relid": 112},
            "JoinPath": {"jointype": 72, "outerjoinpath": 80, "innerjoinpath": 88},
            "RangeTblEntry": {"rtekind": 24, "relid": 28},
        }

    def test_map_required_offsets(self):
        offsets = DwarfOffsetHelper.map_required_offsets(self._valid_struct_members())

        self.assertEqual(offsets["OFFSET_PATH_PATHTYPE"], 4)
        self.assertEqual(offsets["OFFSET_RELOPTINFO_RELID"], 112)
        self.assertEqual(offsets["OFFSET_RANGETBLENTRY_RELID"], 28)

    def test_map_required_offsets_missing_field(self):
        struct_members = self._valid_struct_members()
        del struct_members["JoinPath"]["innerjoinpath"]

        with self.assertRaises(ValueError) as exc:
            DwarfOffsetHelper.map_required_offsets(struct_members)

        self.assertIn("JoinPath.innerjoinpath", str(exc.exception))

    def test_offsets_to_defines(self):
        offsets = DwarfOffsetHelper.map_required_offsets(self._valid_struct_members())
        defines = DwarfOffsetHelper.offsets_to_defines(offsets)

        self.assertIn("#define OFFSET_PATH_PATHTYPE 4", defines)
        self.assertIn("#define OFFSET_JOINPATH_OUTERJOINPATH 80", defines)
        self.assertIn("#define OFFSET_RANGETBLENTRY_RTEKIND 24", defines)

    def test_cache_key_changes_with_mtime(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp_file:
            tmp_file.write("abc")
            tmp_path = tmp_file.name

        try:
            first_key = DwarfOffsetHelper._make_cache_key(tmp_path)
            current_mtime = os.stat(tmp_path).st_mtime
            os.utime(tmp_path, (current_mtime + 1, current_mtime + 1))
            second_key = DwarfOffsetHelper._make_cache_key(tmp_path)
            self.assertNotEqual(first_key, second_key)
        finally:
            os.unlink(tmp_path)

    def test_cache_load_save_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            current_dir = os.getcwd()
            os.chdir(tmp_dir)

            try:
                data = {
                    "k1": {
                        "OFFSET_PATH_PATHTYPE": 4,
                        "OFFSET_PATH_PARENT": 8,
                    }
                }
                DwarfOffsetHelper._save_cache(data)
                loaded = DwarfOffsetHelper._load_cache()
                self.assertEqual(loaded, data)

                cache_file = Path(tmp_dir) / DwarfOffsetHelper.CACHE_FILE
                self.assertTrue(cache_file.exists())
            finally:
                os.chdir(current_dir)


if __name__ == "__main__":
    unittest.main()
