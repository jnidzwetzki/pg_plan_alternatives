"""
Helper classes for pg_plan_alternatives
"""

import os
import re
from pathlib import Path


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

        with open(bpf_file, "r", encoding="utf-8") as f:
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
            bpf.attach_uprobe(name=binary_path, sym=pg_function, fn_name=bpf_function)


class NodeTagHelper:
    """
    Helper to parse PostgreSQL's generated nodetags.h and provide mappings

    The path to the `nodetags.h` file must be provided and loaded via
    `load_from_file()` before the mappings are used.
    """

    _name_by_value = {}
    _value_by_name = {}

    @staticmethod
    def load_from_file(filepath):
        """Parse `nodetags.h` and populate in-memory mappings.

        Raises FileNotFoundError if the file does not exist or ValueError
        if no tags are parsed.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"nodetags file not found: {filepath}")

        NodeTagHelper._name_by_value.clear()
        NodeTagHelper._value_by_name.clear()

        pattern = re.compile(r"^(T_[A-Za-z0-9_]+)\s*=\s*(\d+)\s*,")

        with open(filepath, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if (
                    not line
                    or line.startswith("/*")
                    or line.startswith("*")
                    or line.startswith("//")
                ):
                    continue
                m = pattern.match(line)
                if m:
                    name = m.group(1)
                    val = int(m.group(2))
                    NodeTagHelper._name_by_value[val] = name
                    NodeTagHelper._value_by_name[name] = val

        if not NodeTagHelper._name_by_value:
            raise ValueError(f"No node tags parsed from {filepath}")

    @staticmethod
    def name_from_value(value):
        """Return the nodetag name for a numeric value."""
        return NodeTagHelper._name_by_value.get(value, f"Unknown({value})")

    @staticmethod
    def value_from_name(name):
        """Return the numeric value for a nodetag name."""
        if name not in NodeTagHelper._value_by_name:
            raise ValueError(f"Unknown node tag {name}")
        return NodeTagHelper._value_by_name[name]
