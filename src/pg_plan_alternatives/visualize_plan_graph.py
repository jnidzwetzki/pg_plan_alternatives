#!/usr/bin/env python3
#
# PostgreSQL Plan Alternatives Visualizer
#
# This tool reads JSON output from pg_plan_alternatives and creates
# an interactive graph visualization showing all considered query plans
# and their costs.
###############################################

import json
import argparse
import sys
from collections import defaultdict

try:
    import graphviz
except ImportError:
    print("Error: graphviz package is required for visualization", file=sys.stderr)
    print("Install with: pip install graphviz", file=sys.stderr)
    sys.exit(1)

from pg_plan_alternatives import __version__

EXAMPLES = """
usage examples:
# Create a graph from JSON trace output
visualize_plan_graph -i plans.json -o plans.png

# Create an SVG graph
visualize_plan_graph -i plans.json -o plans.svg

# Create an HTML interactive graph
visualize_plan_graph -i plans.json -o plans.html

# Group by PID
visualize_plan_graph -i plans.json -o plans.png --group-by-pid
"""

parser = argparse.ArgumentParser(
    description="PostgreSQL Plan Alternatives Visualizer - Creates graphs from trace output",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=EXAMPLES,
)
parser.add_argument(
    "-V",
    "--version",
    action="version",
    version=f"{parser.prog} ({__version__})",
)
parser.add_argument(
    "-i",
    "--input",
    type=str,
    required=True,
    metavar="FILE",
    help="input JSON file from pg_plan_alternatives",
)
parser.add_argument(
    "-o",
    "--output",
    type=str,
    required=True,
    metavar="FILE",
    help="output file (format determined by extension: .png, .svg, .pdf, .html)",
)
parser.add_argument(
    "--group-by-pid",
    action="store_true",
    help="create separate graphs for each PID",
)
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    help="be verbose",
)


class PlanVisualizer:
    """Visualizer for query plan alternatives"""

    def __init__(self, args):
        self.args = args
        self.events = []
        self.plans_by_pid = defaultdict(list)
        self.chosen_plans = defaultdict(list)

    def log(self, message):
        """Print verbose message"""
        if self.args.verbose:
            print(message, file=sys.stderr)

    def load_events(self):
        """Load events from JSON file"""
        self.log(f"Loading events from {self.args.input}...")

        try:
            with open(self.args.input, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        self.events.append(event)

                        pid = event.get("pid")
                        event_type = event.get("event_type")

                        if event_type == "ADD_PATH":
                            self.plans_by_pid[pid].append(event)
                        elif event_type == "CREATE_PLAN":
                            self.chosen_plans[pid].append(event)
                    except json.JSONDecodeError as e:
                        self.log(f"Warning: Failed to parse line: {line[:50]}... - {e}")
        except FileNotFoundError:
            print(f"Error: Input file not found: {self.args.input}", file=sys.stderr)
            sys.exit(1)

        self.log(f"Loaded {len(self.events)} events")
        self.log(f"Found {len(self.plans_by_pid)} PIDs")

    @staticmethod
    def _event_signature(event):
        """Return a stable signature for deduplicating equivalent ADD_PATH events."""
        return (
            event.get("pid", 0),
            event.get("event_type", ""),
            event.get("path_type", ""),
            round(float(event.get("startup_cost", 0.0)), 6),
            round(float(event.get("total_cost", 0.0)), 6),
            int(event.get("rows", 0)),
            int(event.get("parent_rti", 0)),
            int(event.get("parent_rel_oid", 0)),
            int(event.get("join_type", 0)),
            int(event.get("inner_rti", 0)),
            int(event.get("outer_rti", 0)),
            int(event.get("inner_rel_oid", 0)),
            int(event.get("outer_rel_oid", 0)),
        )

    @staticmethod
    def _matches_selected_identity(path_event, chosen_event):
        fields = [
            "parent_rti",
            "parent_rel_oid",
            "join_type",
            "inner_rti",
            "outer_rti",
            "inner_rel_oid",
            "outer_rel_oid",
        ]
        match = True
        for field in fields:
            chosen_val = int(chosen_event.get(field, 0))
            if chosen_val and int(path_event.get(field, 0)) != chosen_val:
                match = False
                break
        return match

    @staticmethod
    def _cluster_sort_key(cluster_key):
        """Sort clusters deterministically for stable graph layout."""
        pid, first, second = cluster_key
        return (pid, first, second)

    @staticmethod
    def _join_cluster_sort_key(cluster_key):
        """Sort join clusters deterministically for stable graph layout."""
        pid, join_type_name, outer_rti, inner_rti, outer_rel_oid, inner_rel_oid = (
            cluster_key
        )
        return (pid, join_type_name, outer_rti, inner_rti, outer_rel_oid, inner_rel_oid)

    def create_graph(self, pid=None):
        """Create a graph for a specific PID or all PIDs"""
        if pid:
            graph_name = f"Query Plans (PID {pid})"
            events = self.plans_by_pid[pid]
            chosen = self.chosen_plans.get(pid, [])
        else:
            graph_name = "Query Plans (All PIDs)"
            events = [
                e for events_list in self.plans_by_pid.values() for e in events_list
            ]
            chosen = [
                e for chosen_list in self.chosen_plans.values() for e in chosen_list
            ]

        self.log(f"Creating graph: {graph_name}")
        self.log(f"  Plans considered: {len(events)}")
        self.log(f"  Plans chosen: {len(chosen)}")

        # Create graphviz graph
        dot = graphviz.Digraph(comment=graph_name)
        dot.attr(
            rankdir="LR",
            splines="spline",
            overlap="false",
            nodesep="0.6",
            ranksep="0.9",
            compound="true",
            newrank="true",
        )
        dot.attr(
            "node", shape="box", style="rounded,filled", fontname="Arial", fontsize="9"
        )

        # Keep visible edge styling consistent
        dot.attr("edge", fontname="Arial", fontsize="9", arrowsize="0.7")

        # Track nodes by path type to group similar plans
        nodes_by_type = defaultdict(list)
        nodes_by_relation = defaultdict(list)
        relation_cluster_nodes = defaultdict(list)
        join_cluster_nodes = defaultdict(list)
        event_records = []
        path_nodes = []
        node_to_event = {}

        # Process in timestamp order and deduplicate identical ADD_PATH re-adds.
        events = sorted(events, key=lambda e: e.get("timestamp", 0))
        deduplicated_events = []
        seen_signatures = set()
        duplicate_count = 0
        for event in events:
            sig = self._event_signature(event)
            if sig in seen_signatures:
                duplicate_count += 1
                continue
            seen_signatures.add(sig)
            deduplicated_events.append(event)

        if duplicate_count:
            self.log(f"  Deduplicated {duplicate_count} repeated ADD_PATH events")

        events = deduplicated_events

        # Add nodes for each considered path
        for i, event in enumerate(events):
            path_type = event.get("path_type", "Unknown")
            startup_cost = event.get("startup_cost", 0)
            total_cost = event.get("total_cost", 0)
            rows = event.get("rows", 0)
            parent_rel_oid = event.get("parent_rel_oid", 0)
            inner_rel_oid = event.get("inner_rel_oid", 0)
            outer_rel_oid = event.get("outer_rel_oid", 0)
            parent_rti = event.get("parent_rti", 0)
            inner_rti = event.get("inner_rti", 0)
            outer_rti = event.get("outer_rti", 0)
            join_type_name = event.get("join_type_name", "JOIN_INNER")
            event_pid = event.get("pid", pid)

            # Defensive filter: skip isolated base-path records that have no
            # relation identity and no join linkage. These can occur if tracing
            # captured transient/invalid planner states and only add noise.
            if parent_rti == 0 and inner_rti == 0 and outer_rti == 0:
                continue

            node_id = f"plan_{pid}_{i}" if pid else f"plan_all_{i}"

            fillcolor = "lightblue"
            penwidth = "1"
            oid_lines = []
            if parent_rel_oid:
                oid_lines.append(f"Parent OID: {parent_rel_oid}")
            if outer_rel_oid:
                oid_lines.append(f"Outer OID: {outer_rel_oid}")
            if inner_rel_oid:
                oid_lines.append(f"Inner OID: {inner_rel_oid}")

            oid_text = ""
            if oid_lines:
                oid_text = "\\n" + "\\n".join(oid_lines)

            label = (
                f"{path_type}\n"
                f"Startup: {startup_cost:.2f}\n"
                f"Total: {total_cost:.2f}\n"
                f"Rows: {rows}"
                f"{oid_text}"
            )

            dot.node(node_id, label, fillcolor=fillcolor, penwidth=penwidth)
            nodes_by_type[path_type].append((node_id, total_cost, startup_cost))
            path_nodes.append((node_id, event))
            node_to_event[node_id] = event

            rel_key = (event_pid, parent_rti)
            if parent_rti:
                nodes_by_relation[rel_key].append(node_id)
                relation_cluster_key = (event_pid, parent_rti, parent_rel_oid)
                relation_cluster_nodes[relation_cluster_key].append((node_id, event))
            elif inner_rti or outer_rti:
                join_cluster_key = (
                    event_pid,
                    join_type_name,
                    outer_rti,
                    inner_rti,
                    outer_rel_oid,
                    inner_rel_oid,
                )
                join_cluster_nodes[join_cluster_key].append((node_id, event))

            event_records.append((node_id, event))

        # Group base relation alternatives into dedicated clusters.
        for cluster_index, cluster_key in enumerate(
            sorted(relation_cluster_nodes.keys(), key=self._cluster_sort_key)
        ):
            event_pid, parent_rti, parent_rel_oid = cluster_key
            oid_label = f"OID {parent_rel_oid}" if parent_rel_oid else "OID n/a"
            cluster_name = f"cluster_rel_{cluster_index}"
            with dot.subgraph(name=cluster_name) as rel_cluster:
                rel_cluster.attr(
                    label=f"Relation RTI {parent_rti} ({oid_label})",
                    color="gray65",
                    style="rounded,dashed",
                    penwidth="1.2",
                    fontname="Arial",
                    fontsize="10",
                )
                if pid is None:
                    rel_cluster.attr(
                        label=f"PID {event_pid} • Relation RTI {parent_rti} ({oid_label})"
                    )
                rel_cluster.attr(rank="same")
                for node_id, _ in sorted(
                    relation_cluster_nodes[cluster_key],
                    key=lambda item: item[1].get("timestamp", 0),
                ):
                    rel_cluster.node(node_id)

        # Group join alternatives into dedicated clusters.
        for cluster_index, cluster_key in enumerate(
            sorted(join_cluster_nodes.keys(), key=self._join_cluster_sort_key)
        ):
            (
                event_pid,
                join_type_name,
                outer_rti,
                inner_rti,
                outer_rel_oid,
                inner_rel_oid,
            ) = cluster_key
            cluster_name = f"cluster_join_{cluster_index}"
            outer_label = (
                f"RTI {outer_rti}"
                if outer_rti
                else f"OID {outer_rel_oid}" if outer_rel_oid else "n/a"
            )
            inner_label = (
                f"RTI {inner_rti}"
                if inner_rti
                else f"OID {inner_rel_oid}" if inner_rel_oid else "n/a"
            )
            with dot.subgraph(name=cluster_name) as join_cluster:
                join_cluster.attr(
                    label=f"{join_type_name} (outer: {outer_label}, inner: {inner_label})",
                    color="lightsteelblue4",
                    style="rounded,dashed",
                    penwidth="1.2",
                    fontname="Arial",
                    fontsize="10",
                )
                if pid is None:
                    join_cluster.attr(
                        label=f"PID {event_pid} • {join_type_name} (outer: {outer_label}, inner: {inner_label})"
                    )
                for node_id, _ in sorted(
                    join_cluster_nodes[cluster_key],
                    key=lambda item: item[1].get("timestamp", 0),
                ):
                    join_cluster.node(node_id)

        # Connect alternatives per relation (visible dashed progression)
        for rel_key, rel_nodes in nodes_by_relation.items():
            if len(rel_nodes) <= 1:
                continue
            for i in range(len(rel_nodes) - 1):
                dot.edge(
                    rel_nodes[i],
                    rel_nodes[i + 1],
                    style="dashed",
                    color="gray50",
                    xlabel="alt",
                    constraint="false",
                )

        # Use CREATE_PLAN events only to identify matching ADD_PATH nodes.
        chosen_node_ids = set()
        chosen_relation_node_by_rti = {}
        for i, chosen_event in enumerate(
            sorted(chosen, key=lambda e: e.get("timestamp", 0))
        ):
            c_path = chosen_event.get("path_type", "Unknown")
            c_total = chosen_event.get("total_cost", 0)
            c_startup = chosen_event.get("startup_cost", 0)
            c_ts = chosen_event.get("timestamp", 0)

            best_node = None
            best_score = None
            for node_id, event in path_nodes:
                if event.get("path_type") != c_path:
                    continue
                if not self._matches_selected_identity(event, chosen_event):
                    continue
                ev_total = event.get("total_cost", 0)
                ev_startup = event.get("startup_cost", 0)
                ev_ts = event.get("timestamp", 0)
                if ev_ts > c_ts:
                    continue
                total_diff = abs(ev_total - c_total)
                startup_diff = abs(ev_startup - c_startup)
                ts_diff = c_ts - ev_ts
                score = (round(total_diff, 6), round(startup_diff, 6), ts_diff)
                if best_score is None or score < best_score:
                    best_score = score
                    best_node = node_id

            if best_node:
                chosen_node_ids.add(best_node)
                chosen_parent_rti = chosen_event.get("parent_rti", 0)
                chosen_pid = chosen_event.get("pid", pid)
                if chosen_parent_rti:
                    chosen_relation_node_by_rti[(chosen_pid, chosen_parent_rti)] = (
                        best_node
                    )

        # Re-style only matched chosen ADD_PATH nodes
        for chosen_node_id in chosen_node_ids:
            event = node_to_event[chosen_node_id]
            path_type = event.get("path_type", "Unknown")
            startup_cost = event.get("startup_cost", 0)
            total_cost = event.get("total_cost", 0)
            rows = event.get("rows", 0)
            parent_rel_oid = event.get("parent_rel_oid", 0)
            inner_rel_oid = event.get("inner_rel_oid", 0)
            outer_rel_oid = event.get("outer_rel_oid", 0)

            oid_lines = []
            if parent_rel_oid:
                oid_lines.append(f"Parent OID: {parent_rel_oid}")
            if outer_rel_oid:
                oid_lines.append(f"Outer OID: {outer_rel_oid}")
            if inner_rel_oid:
                oid_lines.append(f"Inner OID: {inner_rel_oid}")

            oid_text = ""
            if oid_lines:
                oid_text = "\\n" + "\\n".join(oid_lines)

            chosen_label = (
                f"{path_type}\n[CHOSEN]\n"
                f"Startup: {startup_cost:.2f}\n"
                f"Total: {total_cost:.2f}\n"
                f"Rows: {rows}"
                f"{oid_text}"
            )
            dot.node(chosen_node_id, chosen_label, fillcolor="lightgreen", penwidth="3")

        # Build lookup of most recent node per (pid, rti) while iterating by time,
        # but prefer selected relation nodes as join inputs whenever available.
        latest_node_by_rti = {}
        for node_id, event in event_records:
            event_pid = event.get("pid", pid)
            parent_rti = event.get("parent_rti", 0)
            if parent_rti:
                latest_node_by_rti[(event_pid, parent_rti)] = node_id

            outer_rti = event.get("outer_rti", 0)
            inner_rti = event.get("inner_rti", 0)
            if outer_rti:
                outer_key = (event_pid, outer_rti)
                outer_node = chosen_relation_node_by_rti.get(
                    outer_key
                ) or latest_node_by_rti.get(outer_key)
                if outer_node and outer_node != node_id:
                    dot.edge(
                        outer_node,
                        node_id,
                        color="steelblue3",
                        xlabel="outer",
                        minlen="2",
                    )
            if inner_rti:
                inner_key = (event_pid, inner_rti)
                inner_node = chosen_relation_node_by_rti.get(
                    inner_key
                ) or latest_node_by_rti.get(inner_key)
                if inner_node and inner_node != node_id:
                    dot.edge(
                        inner_node,
                        node_id,
                        color="darkorange3",
                        xlabel="inner",
                        minlen="2",
                    )

        # If we have multiple plans of the same type, show cost comparison
        for path_type, nodes in nodes_by_type.items():
            if len(nodes) > 1:
                # Sort by total cost
                nodes.sort(key=lambda x: x[1])

                # Add invisible edges to group similar plans
                for i in range(len(nodes) - 1):
                    dot.edge(nodes[i][0], nodes[i + 1][0], style="invis")

        # Add summary statistics
        if events:
            total_plans = len(events)
            cheapest_plan = min(events, key=lambda e: e.get("total_cost", float("inf")))
            most_expensive_plan = max(events, key=lambda e: e.get("total_cost", 0))

            stats_label = (
                f"Statistics\\n"
                f"Total plans considered: {total_plans}\\n"
                f"Cheapest: {cheapest_plan.get('path_type')} ({cheapest_plan.get('total_cost', 0):.2f})\\n"
                f"Most expensive: {most_expensive_plan.get('path_type')} ({most_expensive_plan.get('total_cost', 0):.2f})"
            )

            dot.node("stats", stats_label, shape="note", fillcolor="lightyellow")

            legend_label = (
                "Legend\\n"
                "Blue edge: outer input\\n"
                "Orange edge: inner input\\n"
                "Dashed cluster: relation/join group\\n"
                "Green node: selected plan\\n"
                "Dashed edge (alt): next alternative for same RTI"
            )
            dot.node("legend", legend_label, shape="note", fillcolor="white")

        return dot

    def visualize(self):
        """Create visualization"""
        self.load_events()

        if not self.events:
            print("No events to visualize", file=sys.stderr)
            return

        # Determine output format from file extension
        output_path = self.args.output
        if output_path.endswith(".html"):
            # For HTML, we'll create an SVG and embed it
            output_format = "svg"
        else:
            # Extract format from extension
            parts = output_path.rsplit(".", 1)
            if len(parts) == 2:
                output_format = parts[1].lower()
                output_path = parts[0]
            else:
                output_format = "png"

        if self.args.group_by_pid:
            # Create separate graphs for each PID
            for pid in self.plans_by_pid.keys():
                dot = self.create_graph(pid)
                output_file = f"{output_path}_pid{pid}"
                self.log(
                    f"Rendering graph for PID {pid} to {output_file}.{output_format}"
                )
                dot.render(output_file, format=output_format, cleanup=True)
        else:
            # Create single graph for all PIDs
            dot = self.create_graph()
            self.log(f"Rendering graph to {output_path}.{output_format}")

            if self.args.output.endswith(".html"):
                # Create HTML with embedded SVG
                svg_data = dot.pipe(format="svg").decode("utf-8")
                html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>PostgreSQL Plan Alternatives</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 100%;
            background-color: white;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
        }}
        .svg-container {{
            margin-top: 20px;
            text-align: center;
        }}
        svg {{
            max-width: 100%;
            height: auto;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>PostgreSQL Plan Alternatives Visualization</h1>
        <p>This graph shows all query plans considered by PostgreSQL during query planning.</p>
        <p><strong>Green nodes</strong> indicate plans that were chosen. <strong>Blue nodes</strong> indicate alternative plans that were considered but not selected.</p>
        <div class="svg-container">
            {svg_data}
        </div>
    </div>
</body>
</html>
"""
                with open(self.args.output, "w", encoding="utf-8") as f:
                    f.write(html_content)
                self.log(f"HTML file created: {self.args.output}")
            else:
                dot.render(output_path, format=output_format, cleanup=True)
                self.log(f"Graph file created: {output_path}.{output_format}")

        self.log("Visualization complete")


def main():
    """Main entry point"""
    args = parser.parse_args()

    visualizer = PlanVisualizer(args)
    visualizer.visualize()


if __name__ == "__main__":
    main()
