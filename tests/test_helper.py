"""
Basic tests for pg_plan_alternatives
"""

import unittest
from pg_plan_alternatives import __version__
from pg_plan_alternatives.helper import NodeTagHelper, BPFHelper
import tempfile
import textwrap
import os


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
        self.tmp = tempfile.NamedTemporaryFile('w', delete=False)
        content = textwrap.dedent('''
            /* nodetags.h */
            T_Path = 1,
            T_IndexPath = 2,
            T_HashPath = 13,
        ''')
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


if __name__ == '__main__':
    unittest.main()
