"""
Helper classes for pg_plan_alternatives
"""

import os
from pathlib import Path
from bcc import BPF


class BPFHelper:
    """Helper for BPF operations"""
    
    # The size of the kernel ring buffer
    page_cnt = 2048

    @staticmethod
    def enum_to_defines(enum_instance, prefix):
        """
        Convert an enum to C #define statements
        """
        defines = ""
        for item in enum_instance:
            defines += f"#define {prefix}{item.name} {item.value}\n"
        return defines

    @staticmethod
    def read_bpf_code(filename):
        """
        Read BPF C code from the bpf directory
        """
        # Get the directory where this module is located
        module_dir = Path(__file__).parent
        bpf_file = module_dir / "bpf" / filename
        
        if not bpf_file.exists():
            raise FileNotFoundError(f"BPF file not found: {bpf_file}")
        
        with open(bpf_file, 'r') as f:
            return f.read()

    @staticmethod
    def attach_uprobes(bpf, binary_path, functions):
        """
        Attach uprobes to the specified functions
        
        Args:
            bpf: BPF instance
            binary_path: Path to the PostgreSQL binary
            functions: List of tuples (function_name, bpf_function_name)
        """
        for pg_function, bpf_function in functions:
            bpf.attach_uprobe(
                name=binary_path,
                sym=pg_function,
                fn_name=bpf_function
            )


class PathTypeHelper:
    """
    Helper for PostgreSQL path types
    Based on src/include/nodes/relation.h
    """
    
    path_types = {
        "T_Invalid": 0,
        "T_Path": 1,
        "T_IndexPath": 2,
        "T_BitmapHeapPath": 3,
        "T_BitmapAndPath": 4,
        "T_BitmapOrPath": 5,
        "T_TidPath": 6,
        "T_TidRangePath": 7,
        "T_SubqueryScanPath": 8,
        "T_ForeignPath": 9,
        "T_CustomPath": 10,
        "T_NestPath": 11,
        "T_MergePath": 12,
        "T_HashPath": 13,
        "T_AppendPath": 14,
        "T_MergeAppendPath": 15,
        "T_GroupResultPath": 16,
        "T_MaterialPath": 17,
        "T_MemoizePath": 18,
        "T_UniquePath": 19,
        "T_GatherPath": 20,
        "T_GatherMergePath": 21,
        "T_ProjectionPath": 22,
        "T_ProjectSetPath": 23,
        "T_SortPath": 24,
        "T_IncrementalSortPath": 25,
        "T_GroupPath": 26,
        "T_UpperUniquePath": 27,
        "T_AggPath": 28,
        "T_GroupingSetsPath": 29,
        "T_MinMaxAggPath": 30,
        "T_WindowAggPath": 31,
        "T_SetOpPath": 32,
        "T_RecursiveUnionPath": 33,
        "T_LockRowsPath": 34,
        "T_ModifyTablePath": 35,
        "T_LimitPath": 36,
    }

    @staticmethod
    def path_type_to_str(path_type):
        """
        Return the name of a path type based on the numeric value
        """
        for path_name, path_value in PathTypeHelper.path_types.items():
            if path_value == path_type:
                return path_name
        return f"Unknown({path_type})"

    @staticmethod
    def path_type_to_int(path_name):
        """
        Return the numeric value of a path type based on the name
        """
        if path_name not in PathTypeHelper.path_types:
            raise ValueError(f"Unknown path type {path_name}")
        return PathTypeHelper.path_types[path_name]
