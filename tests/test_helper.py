"""
Basic tests for pg_plan_alternatives
"""

import unittest
from pg_plan_alternatives import __version__
from pg_plan_alternatives.helper import PathTypeHelper, BPFHelper


class TestVersion(unittest.TestCase):
    """Test version information"""
    
    def test_version_exists(self):
        """Test that version is defined"""
        self.assertIsNotNone(__version__)
        self.assertIsInstance(__version__, str)
        self.assertTrue(len(__version__) > 0)


class TestPathTypeHelper(unittest.TestCase):
    """Test PathTypeHelper class"""
    
    def test_path_type_to_str(self):
        """Test path type to string conversion"""
        self.assertEqual(PathTypeHelper.path_type_to_str(1), "T_Path")
        self.assertEqual(PathTypeHelper.path_type_to_str(2), "T_IndexPath")
        self.assertEqual(PathTypeHelper.path_type_to_str(13), "T_HashPath")
    
    def test_path_type_to_str_unknown(self):
        """Test unknown path type"""
        result = PathTypeHelper.path_type_to_str(999)
        self.assertTrue(result.startswith("Unknown"))
    
    def test_path_type_to_int(self):
        """Test path type name to int conversion"""
        self.assertEqual(PathTypeHelper.path_type_to_int("T_Path"), 1)
        self.assertEqual(PathTypeHelper.path_type_to_int("T_IndexPath"), 2)
        self.assertEqual(PathTypeHelper.path_type_to_int("T_HashPath"), 13)
    
    def test_path_type_to_int_invalid(self):
        """Test invalid path type name"""
        with self.assertRaises(ValueError):
            PathTypeHelper.path_type_to_int("InvalidPath")


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
