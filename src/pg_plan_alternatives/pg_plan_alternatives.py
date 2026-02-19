#!/usr/bin/env python3
#
# PostgreSQL Plan Alternatives Tracer
#
# This tool traces all query plans that are considered by PostgreSQL
# during query planning, not just the final chosen plan.
#
# It instruments the add_path() function using eBPF and UProbes.
###############################################

import os
import sys
import json
import argparse
from enum import IntEnum, auto
from datetime import datetime
import struct
from bcc import BPF

from pg_plan_alternatives import __version__
from pg_plan_alternatives.helper import BPFHelper, NodeTagHelper

EXAMPLES = """
usage examples:
# Trace PostgreSQL binary and output all considered plans
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -n /path/to/nodetags.h

# Trace specific PID
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -n /path/to/nodetags.h

# Trace multiple PIDs
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -p 5678 -n /path/to/nodetags.h

# Output in JSON format
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -j -n /path/to/nodetags.h

# Write output to file
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -o plans.json -n /path/to/nodetags.h

# Be verbose
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -v -n /path/to/nodetags.h
"""


class TraceEvents(IntEnum):
    """Events to trace"""

    ADD_PATH = auto()
    CREATE_PLAN = auto()


class JoinType(IntEnum):
    """PostgreSQL JoinType enum"""

    JOIN_INNER = 0
    JOIN_LEFT = 1
    JOIN_FULL = 2
    JOIN_RIGHT = 3
    JOIN_SEMI = 4
    JOIN_ANTI = 5
    JOIN_RIGHT_ANTI = 6
    JOIN_UNIQUE_OUTER = 7
    JOIN_UNIQUE_INNER = 8


parser = argparse.ArgumentParser(
    description="PostgreSQL Plan Alternatives Tracer - Shows all query plans considered during planning",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=EXAMPLES,
)
parser.add_argument(
    "-V",
    "--version",
    action="version",
    version=f"{parser.prog} ({__version__})",
)
parser.add_argument("-v", "--verbose", action="store_true", help="be verbose")
parser.add_argument(
    "-j", "--json", action="store_true", help="generate output as JSON data"
)
parser.add_argument(
    "-p",
    "--pid",
    type=int,
    nargs="+",
    action="extend",
    dest="pids",
    metavar="PID",
    help="the pid(s) to trace",
)
parser.add_argument(
    "-x",
    "--exec",
    type=str,
    required=True,
    metavar="PATH",
    help="the path to the PostgreSQL binary",
)
parser.add_argument(
    "-n",
    "--nodetags",
    type=str,
    required=True,
    metavar="PATH",
    help="path to nodetags.h file (required)",
)
parser.add_argument(
    "-o",
    "--output",
    type=str,
    metavar="FILE",
    help="output file (default: stdout)",
)
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="show planned actions (attach targets, files) but do not perform tracing",
)


class PlanAlternativesTracer:
    """Main tracer class"""

    def __init__(self, args):
        self.args = args
        self.bpf = None
        self.output_file = None
        self.plans_by_query = {}
        self.query_counter = 0

    def __del__(self):
        if self.output_file:
            self.output_file.close()

    def log(self, message):
        """Print a message to stderr if verbose mode is enabled"""
        if self.args.verbose:
            print(message, file=sys.stderr)

    def output(self, message):
        """Output a message to stdout or file"""
        if self.output_file:
            self.output_file.write(message + "\n")
            self.output_file.flush()
        else:
            print(message)

    def setup_bpf(self):
        """Setup BPF program"""
        self.log("Setting up BPF program...")

        # Read BPF C code
        bpf_code = BPFHelper.read_bpf_code("pg_plan_alternatives.c")

        # Replace __DEFINES__ with enum definitions
        defines = BPFHelper.enum_to_defines(TraceEvents, "EVENT_")
        bpf_code = bpf_code.replace("__DEFINES__", defines)

        if self.args.verbose:
            self.log("BPF program code prepared")

        # Initialize BPF
        self.bpf = BPF(text=bpf_code)

        # Attach uprobes
        self.log(f"Attaching to binary: {self.args.exec}")

        functions = [
            ("set_rel_pathlist", "bpf_set_rel_pathlist"),
            ("add_path", "bpf_add_path"),
            ("create_plan", "bpf_create_plan"),
        ]

        try:
            BPFHelper.attach_uprobes(self.bpf, self.args.exec, functions)
            self.log("Successfully attached uprobes")
        except (OSError, RuntimeError) as e:
            print(f"Error attaching uprobes: {e}", file=sys.stderr)
            print(
                "Make sure the PostgreSQL binary has debug symbols and the functions exist",
                file=sys.stderr,
            )
            sys.exit(1)

        # Set up perf buffer
        self.bpf["planevents"].open_perf_buffer(
            self.handle_event, page_cnt=BPFHelper.page_cnt
        )

    def init(self):
        """Initialize tracer: compile/load BPF and attach probes."""
        self.setup_bpf()

    def handle_event(self, _cpu, data, _size):
        """Handle a plan event from BPF"""
        event = self.bpf["planevents"].event(data)

        print(
            f"Received event: PID={event.pid}, Type={TraceEvents(event.event_type).name}, PathType={NodeTagHelper.name_from_value(event.path_type)}"
        )  # Debug log

        # Filter by PID if specified
        if self.args.pids and event.pid not in self.args.pids:
            return

        timestamp = event.timestamp
        pid = event.pid
        event_type = event.event_type

        # Decode costs from raw double bits (u64) to Python floats
        try:
            startup_cost = struct.unpack(
                "<d", int(event.startup_cost).to_bytes(8, "little")
            )[0]
        except (struct.error, OverflowError, ValueError, TypeError):
            startup_cost = float(event.startup_cost)

        try:
            total_cost = struct.unpack(
                "<d", int(event.total_cost).to_bytes(8, "little")
            )[0]
        except (struct.error, OverflowError, ValueError, TypeError):
            total_cost = float(event.total_cost)

        path_type_str = NodeTagHelper.name_from_value(event.path_type)

        try:
            join_type_str = JoinType(event.join_type).name
        except ValueError:
            join_type_str = f"Unknown({event.join_type})"

        # Decode rows estimate (was sent as raw double bits)
        try:
            rows_val = struct.unpack("<d", int(event.rows).to_bytes(8, "little"))[0]
            # rows are typically an estimate; present as integer when possible
            rows = int(rows_val)
        except (struct.error, OverflowError, ValueError, TypeError):
            rows = int(event.rows)

        output_data = {
            "timestamp": timestamp,
            "pid": pid,
            "event_type": TraceEvents(event_type).name,
            "path_type": path_type_str,
            "startup_cost": startup_cost,
            "total_cost": total_cost,
            "rows": rows,
            "parent_rti": event.parent_relid,
            "parent_rel_oid": event.relid,
            "join_type": event.join_type,
            "join_type_name": join_type_str,
            "inner_rti": event.inner_relid,
            "outer_rti": event.outer_relid,
            "inner_rel_oid": event.inner_rel_oid,
            "outer_rel_oid": event.outer_rel_oid,
        }

        if self.args.json:
            self.output(json.dumps(output_data))
        else:
            # Human-readable output
            event_name = TraceEvents(event_type).name
            time_str = datetime.fromtimestamp(timestamp / 1e9).strftime("%H:%M:%S.%f")[
                :-3
            ]

            if event_type == TraceEvents.ADD_PATH:
                rel_extra = ""
                if event.parent_relid:
                    rel_extra += f", parent_rti={event.parent_relid}"
                if event.relid:
                    rel_extra += f", parent_oid={event.relid}"
                if event.join_type or event.inner_relid or event.outer_relid:
                    rel_extra += f", join={join_type_str}"
                if event.outer_relid:
                    rel_extra += f", outer_rti={event.outer_relid}"
                if event.outer_rel_oid:
                    rel_extra += f", outer_oid={event.outer_rel_oid}"
                if event.inner_relid:
                    rel_extra += f", inner_rti={event.inner_relid}"
                if event.inner_rel_oid:
                    rel_extra += f", inner_oid={event.inner_rel_oid}"
                msg = (
                    f"[{time_str}] [PID {pid}] ADD_PATH: {path_type_str} "
                    f"(startup={startup_cost:.2f}, total={total_cost:.2f}, rows={rows}{rel_extra})"
                )
            elif event_type == TraceEvents.CREATE_PLAN:
                msg = (
                    f"[{time_str}] [PID {pid}] CREATE_PLAN: {path_type_str} "
                    f"(startup={startup_cost:.2f}, total={total_cost:.2f}) [CHOSEN]"
                )
            else:
                msg = f"[{time_str}] [PID {pid}] {event_name}: {path_type_str}"

            self.output(msg)

        # CREATE_PLAN child paths are emitted directly by eBPF probe.

    def run(self):
        """Main run loop"""
        self.setup_bpf()

        # Open output file if specified
        if self.args.output:
            try:
                # Opening for long-lived use; using a context manager here would
                # close the file immediately.
                # pylint: disable=consider-using-with
                self.output_file = open(self.args.output, "w", encoding="utf-8")
                # pylint: enable=consider-using-with
            except IOError as e:
                print(f"Error opening output file: {e}", file=sys.stderr)
                sys.exit(1)

        try:
            self.log("Tracing plan alternatives... Hit Ctrl-C to end.")

            # Print header
            if not self.args.json:
                self.output("=" * 80)
                self.output("PostgreSQL Plan Alternatives Tracer")
                self.output(f"Binary: {self.args.exec}")
                if self.args.pids:
                    self.output(f"PIDs: {', '.join(map(str, self.args.pids))}")
                else:
                    self.output("Tracing all PostgreSQL processes")
                self.output("=" * 80)

            # Poll for events
            while True:
                self.bpf.perf_buffer_poll()
        except KeyboardInterrupt:
            self.log("\nDetaching...")
        finally:
            if self.output_file:
                try:
                    self.output_file.close()
                finally:
                    self.output_file = None


def main():
    """Main entry point"""
    args = parser.parse_args()

    # Check if running as root
    if os.geteuid() != 0:
        print("Error: This tool requires root privileges to use eBPF", file=sys.stderr)
        print("Please run with sudo", file=sys.stderr)
        sys.exit(1)

    # Check if binary exists
    if not os.path.exists(args.exec):
        print(f"Error: Binary not found: {args.exec}", file=sys.stderr)
        sys.exit(1)

    # Check nodetags file exists and load it
    if not os.path.exists(args.nodetags):
        print(f"Error: nodetags file not found: {args.nodetags}", file=sys.stderr)
        sys.exit(1)

    try:
        NodeTagHelper.load_from_file(args.nodetags)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading nodetags file: {e}", file=sys.stderr)
        sys.exit(1)

    # Create tracer and initialize (compile/load BPF and attach probes)
    tracer = PlanAlternativesTracer(args)
    tracer.init()

    if not args.dry_run:
        tracer.run()


if __name__ == "__main__":
    main()
