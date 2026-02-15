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
import signal
from enum import IntEnum, auto
from bcc import BPF
from datetime import datetime

from pg_plan_alternatives import __version__
from pg_plan_alternatives.helper import BPFHelper, PathTypeHelper

EXAMPLES = """
usage examples:
# Trace PostgreSQL binary and output all considered plans
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres

# Trace specific PID
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234

# Trace multiple PIDs
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -p 5678

# Output in JSON format
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -j

# Write output to file
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -o plans.json

# Be verbose
pg_plan_alternatives -x /usr/lib/postgresql/16/bin/postgres -p 1234 -v
"""


class TraceEvents(IntEnum):
    """Events to trace"""
    ADD_PATH = auto()
    CREATE_PLAN = auto()


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
    "-o",
    "--output",
    type=str,
    metavar="FILE",
    help="output file (default: stdout)",
)


class PlanAlternativesTracer:
    """Main tracer class"""

    def __init__(self, args):
        self.args = args
        self.bpf = None
        self.output_file = None
        self.plans_by_query = {}
        self.query_counter = 0

        if args.output:
            self.output_file = open(args.output, 'w')

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
            self.output_file.write(message + '\n')
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
            ("add_path", "bpf_add_path"),
            ("create_plan", "bpf_create_plan"),
        ]
        
        try:
            BPFHelper.attach_uprobes(self.bpf, self.args.exec, functions)
            self.log("Successfully attached uprobes")
        except Exception as e:
            print(f"Error attaching uprobes: {e}", file=sys.stderr)
            print("Make sure the PostgreSQL binary has debug symbols and the functions exist", file=sys.stderr)
            sys.exit(1)

        # Set up perf buffer
        self.bpf["planevents"].open_perf_buffer(
            self.handle_event, page_cnt=BPFHelper.page_cnt
        )

    def handle_event(self, cpu, data, size):
        """Handle a plan event from BPF"""
        event = self.bpf["planevents"].event(data)

        # Filter by PID if specified
        if self.args.pids and event.pid not in self.args.pids:
            return

        timestamp = event.timestamp
        pid = event.pid
        event_type = event.event_type

        # Convert costs from fixed-point back to float
        startup_cost = event.startup_cost / 1000.0
        total_cost = event.total_cost / 1000.0

        path_type_str = PathTypeHelper.path_type_to_str(event.path_type)

        if self.args.json:
            # Output as JSON
            output_data = {
                "timestamp": timestamp,
                "pid": pid,
                "event_type": TraceEvents(event_type).name,
                "path_type": path_type_str,
                "startup_cost": startup_cost,
                "total_cost": total_cost,
                "rows": event.rows,
                "width": event.width,
                "parent_relid": event.parent_relid,
                "relid": event.relid,
                "join_type": event.join_type,
                "inner_relid": event.inner_relid,
                "outer_relid": event.outer_relid,
            }
            self.output(json.dumps(output_data))
        else:
            # Human-readable output
            event_name = TraceEvents(event_type).name
            time_str = datetime.fromtimestamp(timestamp / 1e9).strftime('%H:%M:%S.%f')[:-3]
            
            if event_type == TraceEvents.ADD_PATH:
                msg = f"[{time_str}] [PID {pid}] ADD_PATH: {path_type_str} " \
                      f"(startup={startup_cost:.2f}, total={total_cost:.2f}, rows={event.rows})"
            elif event_type == TraceEvents.CREATE_PLAN:
                msg = f"[{time_str}] [PID {pid}] CREATE_PLAN: {path_type_str} " \
                      f"(startup={startup_cost:.2f}, total={total_cost:.2f}) [CHOSEN]"
            else:
                msg = f"[{time_str}] [PID {pid}] {event_name}: {path_type_str}"
            
            self.output(msg)

    def run(self):
        """Main run loop"""
        self.setup_bpf()
        
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
        try:
            while True:
                self.bpf.perf_buffer_poll()
        except KeyboardInterrupt:
            self.log("\nDetaching...")


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

    # Create and run tracer
    tracer = PlanAlternativesTracer(args)
    tracer.run()


if __name__ == "__main__":
    main()
