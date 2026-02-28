"""
Helper classes for pg_plan_alternatives
"""

import os
import re
import sys
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from elftools.elf.elffile import ELFFile
from elftools.dwarf.dwarf_expr import DWARFExprParser

import psycopg2


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


class DwarfOffsetHelper:
    """Resolve struct field offsets from DWARF debug information."""

    REQUIRED_FIELDS: dict[str, tuple[str, str]] = {
        "OFFSET_PATH_PATHTYPE": ("Path", "pathtype"),
        "OFFSET_PATH_PARENT": ("Path", "parent"),
        "OFFSET_PATH_ROWS": ("Path", "rows"),
        "OFFSET_PATH_STARTUP_COST": ("Path", "startup_cost"),
        "OFFSET_PATH_TOTAL_COST": ("Path", "total_cost"),
        "OFFSET_RELOPTINFO_RELID": ("RelOptInfo", "relid"),
        "OFFSET_JOINPATH_JOINTYPE": ("JoinPath", "jointype"),
        "OFFSET_JOINPATH_OUTERJOINPATH": ("JoinPath", "outerjoinpath"),
        "OFFSET_JOINPATH_INNERJOINPATH": ("JoinPath", "innerjoinpath"),
        "OFFSET_RANGETBLENTRY_RTEKIND": ("RangeTblEntry", "rtekind"),
        "OFFSET_RANGETBLENTRY_RELID": ("RangeTblEntry", "relid"),
    }

    CACHE_FILE = ".pg_dwarf_cache"

    @classmethod
    def extract_offsets_from_binary(cls, binary_path: str) -> dict[str, int]:
        """Extract required offsets from DWARF debug information."""
        offsets, _cache_hit = cls.extract_offsets_from_binary_with_source(binary_path)
        return offsets

    @classmethod
    def extract_offsets_from_binary_with_source(
        cls, binary_path: str
    ) -> tuple[dict[str, int], bool]:
        """Extract offsets and return whether they came from cache."""
        if not os.path.exists(binary_path):
            raise FileNotFoundError(f"Binary not found: {binary_path}")

        cache_key = cls._make_cache_key(binary_path)
        cache_data = cls._load_cache()

        cached_offsets = cache_data.get(cache_key)
        if isinstance(cached_offsets, dict):
            return ({name: int(value) for name, value in cached_offsets.items()}, True)

        with open(binary_path, "rb") as binary_fh:
            elf_file = ELFFile(binary_fh)
            if not elf_file.has_dwarf_info():
                raise ValueError(
                    f"Binary does not contain DWARF debug info: {binary_path}"
                )
            dwarf_info = elf_file.get_dwarf_info()
            struct_members = cls._load_struct_member_offsets(dwarf_info)

        offsets = cls.map_required_offsets(struct_members)

        cache_data[cache_key] = offsets
        cls._save_cache(cache_data)

        return offsets, False

    @classmethod
    def map_required_offsets(
        cls, struct_members: dict[str, dict[str, int]]
    ) -> dict[str, int]:
        """Map required struct members to BPF offset macro names."""
        offsets: dict[str, int] = {}
        missing: list[str] = []

        for macro_name, (struct_name, field_name) in cls.REQUIRED_FIELDS.items():
            fields = struct_members.get(struct_name, {})
            value = fields.get(field_name)
            if value is None:
                missing.append(f"{struct_name}.{field_name}")
                continue
            offsets[macro_name] = value

        if missing:
            missing_s = ", ".join(sorted(missing))
            raise ValueError(f"Unable to resolve required DWARF offsets: {missing_s}")

        return offsets

    @classmethod
    def offsets_to_defines(cls, offsets: dict[str, int]) -> str:
        """Convert resolved offsets into C #define statements."""
        lines: list[str] = []
        for macro_name in cls.REQUIRED_FIELDS:
            lines.append(f"#define {macro_name} {offsets[macro_name]}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _decode_name(value: Any) -> str:
        """Decode a DWARF name attribute to a Python string."""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    @staticmethod
    def _normalize_struct_name(name: str) -> str:
        """Normalize struct names as they can appear as 'struct X'."""
        if name.startswith("struct "):
            return name.split(" ", 1)[1]
        return name

    @staticmethod
    def _member_offset(member_die: Any) -> int | None:
        """Extract a member offset from a DW_TAG_member DIE."""
        location = member_die.attributes.get("DW_AT_data_member_location")
        result: int | None = None

        if location is None:
            return None

        if isinstance(location.value, int):
            result = int(location.value)
        elif isinstance(location.value, (bytes, bytearray)):
            if DWARFExprParser is not None:
                try:
                    expr_parser = DWARFExprParser(member_die.dwarfinfo.structs)
                    ops = expr_parser.parse_expr(location.value)
                except (ValueError, TypeError, AttributeError, IndexError):
                    ops = []

                if len(ops) == 1 and ops[0].op_name in {
                    "DW_OP_plus_uconst",
                    "DW_OP_constu",
                }:
                    result = int(ops[0].args[0])
                elif (
                    len(ops) == 2
                    and ops[0].op_name == "DW_OP_constu"
                    and ops[1].op_name == "DW_OP_plus"
                ):
                    result = int(ops[0].args[0])

        return result

    @classmethod
    def _load_struct_member_offsets(cls, dwarf_info: Any) -> dict[str, dict[str, int]]:
        """Load all named struct member offsets from DWARF CUs."""
        result: dict[str, dict[str, int]] = {}

        for cu in dwarf_info.iter_CUs():
            for die in cu.iter_DIEs():
                if die.tag != "DW_TAG_structure_type":
                    continue

                name_attr = die.attributes.get("DW_AT_name")
                if name_attr is None:
                    continue

                struct_name = cls._normalize_struct_name(
                    cls._decode_name(name_attr.value)
                )
                if not struct_name:
                    continue

                fields: dict[str, int] = {}
                for child in die.iter_children():
                    if child.tag != "DW_TAG_member":
                        continue

                    member_name_attr = child.attributes.get("DW_AT_name")
                    if member_name_attr is None:
                        continue

                    member_name = cls._decode_name(member_name_attr.value)
                    member_offset = cls._member_offset(child)
                    if member_offset is not None:
                        fields[member_name] = member_offset

                if not fields:
                    continue

                existing = result.get(struct_name)
                if existing is None or len(fields) > len(existing):
                    result[struct_name] = fields

        return result

    @classmethod
    def _cache_file_path(cls) -> Path:
        """Get cache file path in current working directory."""
        return Path.cwd() / cls.CACHE_FILE

    @staticmethod
    def _make_cache_key(binary_path: str) -> str:
        """Build a cache key from binary identity and metadata."""
        stat_result = os.stat(binary_path)
        real_path = os.path.realpath(binary_path)
        return (
            f"{real_path}|"
            f"inode={stat_result.st_ino}|"
            f"size={stat_result.st_size}|"
            f"mtime_ns={stat_result.st_mtime_ns}"
        )

    @classmethod
    def _load_cache(cls) -> dict[str, dict[str, int]]:
        """Load cached offsets from disk."""
        cache_file = cls._cache_file_path()
        if not cache_file.exists():
            return {}

        try:
            with open(cache_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {}
            return data
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}

    @classmethod
    def _save_cache(cls, cache_data: dict[str, dict[str, int]]) -> None:
        """Persist cached offsets to disk."""
        cache_file = cls._cache_file_path()
        try:
            with open(cache_file, "w", encoding="utf-8") as fh:
                json.dump(cache_data, fh)
        except OSError:
            pass


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


class OIDResolver:
    """Resolve PostgreSQL OIDs to human‑readable names and cache results.

    The resolver connects to a live PostgreSQL database using a standard
    connection URL (e.g. ``postgres://user:pass@host:5432/db``).  During
    initialization it fetches the catalog entries and warms an in‑memory
    cache so subsequent lookups are very fast.

    ``psycopg2`` is a hard requirement of the package; the resolver assumes
    the library is importable and will raise normally if not.
    """

    def __init__(self, connection_url: str):
        self.connection_url = connection_url
        self.cache: dict[str, str] = {}
        # use ``Any`` to work around missing type information for psycopg2
        self.connection: Any = None
        self.cur: Any = None
        self.connect()

    def connect(self):
        """Open the database connection and warm up the cache."""
        connection_url_parsed = urlparse(self.connection_url)
        username = connection_url_parsed.username
        password = connection_url_parsed.password
        database = connection_url_parsed.path.lstrip("/")
        hostname = connection_url_parsed.hostname
        port = connection_url_parsed.port

        try:
            # ``psycopg2`` is a hard dependency of the package.
            self.connection = psycopg2.connect(  # type: ignore[attr-defined]
                database=database,
                user=username,
                password=password,
                host=hostname,
                port=port,
            )
            self.connection.set_session(autocommit=True)
            self.cur = self.connection.cursor()

            # warm the cache so lookups are fast later
            self.fetch_all_oids()
        except psycopg2.OperationalError as error:  # type: ignore[attr-defined]
            print(f"Unable to connect to the database {self.connection_url}")
            print(f"{error}")
            sys.exit(1)

    def disconnect(self):
        """Close the database connection."""
        if self.cur:
            self.cur.close()
            self.cur = None
        if self.connection:
            self.connection.close()
            self.connection = None

    def fetch_all_oids(self):
        """Retrieve the full relation catalog and populate the cache."""
        select_stmt = """
        SELECT n.nspname, c.relname, c.oid 
        FROM pg_namespace n
        JOIN pg_class c ON n.oid = c.relnamespace
        """
        self.cur.execute(select_stmt)
        for nspname, relname, oid in self.cur.fetchall():
            self.cache[str(oid)] = f"{nspname}.{relname}"

    def fetch_oid_from_db(self, oid):
        """Query the database for a single OID and cache the result."""
        select_stmt = """
        SELECT n.nspname, c.relname
        FROM pg_namespace n
        JOIN pg_class c ON n.oid = c.relnamespace
        WHERE c.oid = %s;
        """
        oid_s = str(oid)
        try:
            self.cur.execute(select_stmt, [oid_s])
            result_row = self.cur.fetchone()
            if result_row is None:
                return f"Oid {oid_s}"
            name = f"{result_row[0]}.{result_row[1]}"
            self.cache[oid_s] = name
            return name
        except psycopg2.Error as error:  # type: ignore[attr-defined]
            print(f"Error while executing SQL statement: {error}")
            print(f"pgerror: {error.pgerror}")
            print(f"pgcode: {error.pgcode}")
            return ""

    def resolve_oid(self, oid):
        """Return a human‑readable name for *oid*.

        The cache is checked first; on a miss the database will be queried.
        """
        key = str(oid)
        if key in self.cache:
            return self.cache[key]
        return self.fetch_oid_from_db(oid)
