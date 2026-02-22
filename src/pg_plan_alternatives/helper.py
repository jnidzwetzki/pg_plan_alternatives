"""
Helper classes for pg_plan_alternatives
"""

import os
import re
import sys
from pathlib import Path
from typing import Any

# database dependency used for resolving relation OIDs
from urllib.parse import urlparse

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
