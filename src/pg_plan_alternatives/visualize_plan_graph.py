#!/usr/bin/env python3
# pylint: disable=too-many-lines
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

import graphviz

from pg_plan_alternatives.helper import OIDResolver
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
parser.add_argument(
    "--db-url",
    dest="db_url",
    type=str,
    help="Postgres connection URL used to resolve relation OIDs into names",
)


class PlanVisualizer:
    """Visualizer for query plan alternatives"""

    def __init__(self, args):
        self.args = args
        self.events = []
        self.plans_by_pid = defaultdict(list)
        self.chosen_plans = defaultdict(list)

        # resolver used when the user passes --db-url
        self.oid_resolver = None
        if getattr(self.args, "db_url", None):
            self.oid_resolver = OIDResolver(self.args.db_url)

    def _format_oid_line(self, role, oid):
        """Return a formatted line describing *oid* for a node label."""
        if not oid:
            return ""
        if self.oid_resolver:
            name = self.oid_resolver.resolve_oid(oid)
            return f"{role}: {name} ({oid})"
        return f"{role} OID: {oid}"

    def _format_oid_label(self, oid):
        """Format an OID for cluster labels.

        When a resolver is present return ``name (oid)``; otherwise a simple
        ``OID <n>`` string is produced.  ``None`` or zero values yield
        ``"OID n/a"``.
        """
        if not oid:
            return "OID n/a"
        if self.oid_resolver:
            name = self.oid_resolver.resolve_oid(oid)
            return f"{name} ({oid})"
        return f"OID {oid}"

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
            int(event.get("path_ptr", 0)),
            event.get("path_node_type_name", ""),
            int(event.get("parent_rel_ptr", 0)),
            int(event.get("outer_path_ptr", 0)),
            int(event.get("inner_path_ptr", 0)),
            event.get("outer_path_type_name", ""),
            event.get("inner_path_type_name", ""),
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
    def _join_semantic_signature(event):
        """Return a semantic signature for join-path deduplication.

        PostgreSQL may emit equivalent join alternatives multiple times with
        different transient planner pointers.  For visualization purposes we
        collapse those into one node by keying on stable planner properties.
        """
        return (
            event.get("pid", 0),
            event.get("event_type", ""),
            event.get("path_node_type_name", ""),
            event.get("path_type", ""),
            round(float(event.get("startup_cost", 0.0)), 6),
            round(float(event.get("total_cost", 0.0)), 6),
            int(event.get("rows", 0)),
            int(event.get("join_type", 0)),
            event.get("join_type_name", ""),
            int(event.get("inner_rti", 0)),
            int(event.get("outer_rti", 0)),
            int(event.get("inner_rel_oid", 0)),
            int(event.get("outer_rel_oid", 0)),
            event.get("outer_path_type_name", ""),
            event.get("inner_path_type_name", ""),
        )

    @staticmethod
    def _is_join_path_event(event):
        """Return True when the event describes a binary join alternative."""
        has_outer = bool(
            int(event.get("outer_rti", 0))
            or int(event.get("outer_rel_oid", 0))
            or int(event.get("outer_path_ptr", 0))
        )
        has_inner = bool(
            int(event.get("inner_rti", 0))
            or int(event.get("inner_rel_oid", 0))
            or int(event.get("inner_path_ptr", 0))
        )
        return has_outer and has_inner

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

    @staticmethod
    def _parent_rel_cluster_sort_key(cluster_key):
        """Sort parent-rel clusters deterministically for stable graph layout."""
        pid, parent_rel_ptr = cluster_key
        return (pid, parent_rel_ptr)

    @staticmethod
    def _format_cost(cost):
        """Format costs with enough precision to differentiate alternatives."""
        # Use 3 decimals to keep labels compact while preserving planner-level
        # distinctions (e.g., 16.595 vs 16.600).
        return f"{float(cost):.3f}"

    @staticmethod
    def _selection_equivalence_key(event):
        """Return a semantic key for mapping CREATE_PLAN nodes to ADD_PATH peers."""
        return (
            event.get("pid", 0),
            event.get("path_node_type_name", ""),
            event.get("path_type", ""),
            round(float(event.get("startup_cost", 0.0)), 6),
            round(float(event.get("total_cost", 0.0)), 6),
            int(event.get("rows", 0)),
            int(event.get("parent_rel_oid", 0)),
            int(event.get("join_type", 0)),
            event.get("join_type_name", ""),
            int(event.get("outer_rti", 0)),
            int(event.get("inner_rti", 0)),
            int(event.get("outer_rel_oid", 0)),
            int(event.get("inner_rel_oid", 0)),
        )

    @staticmethod
    def _event_specificity(event):
        """Return a specificity score for choosing best representative."""
        has_parent_rti = 1 if int(event.get("parent_rti", 0)) else 0
        has_parent_oid = 1 if int(event.get("parent_rel_oid", 0)) else 0
        has_join_rti = (
            1 if int(event.get("outer_rti", 0)) or int(event.get("inner_rti", 0)) else 0
        )
        has_join_oid = (
            1
            if int(event.get("outer_rel_oid", 0)) or int(event.get("inner_rel_oid", 0))
            else 0
        )
        has_parent_ptr = 1 if int(event.get("parent_rel_ptr", 0)) else 0

        # Prefer relation-identifiable events first, then join identity,
        # then generic parent-rel pointer availability.
        return (
            has_parent_rti * 16
            + has_parent_oid * 8
            + has_join_rti * 4
            + has_join_oid * 2
            + has_parent_ptr
        )

    def _promote_chosen_node(self, node_id, node_to_event, nodes_by_equivalence):
        """Prefer richer ADD_PATH node when CREATE_PLAN matches a duplicate."""
        event = node_to_event.get(node_id)
        if not event:
            return node_id

        if int(event.get("parent_rti", 0)):
            return node_id

        candidates = nodes_by_equivalence.get(
            self._selection_equivalence_key(event), []
        )
        if len(candidates) <= 1:
            return node_id

        return max(
            candidates,
            key=lambda candidate_node: self._event_specificity(
                node_to_event[candidate_node]
            ),
        )

    def _representative_event_indices(self, events):
        """Return event indices to render after semantic duplicate suppression."""
        candidates_by_key = defaultdict(list)
        for event_index, event in enumerate(events):
            candidates_by_key[self._selection_equivalence_key(event)].append(
                (event_index, event)
            )

        keep_indices = set()
        for candidates in candidates_by_key.values():
            best_index = None
            best_specificity = -1
            best_timestamp = 0

            for event_index, event in candidates:
                specificity = self._event_specificity(event)
                event_ts = int(event.get("timestamp", 0))

                if best_index is None:
                    best_index = event_index
                    best_specificity = specificity
                    best_timestamp = event_ts
                    continue

                if specificity > best_specificity or (
                    specificity == best_specificity and event_ts < best_timestamp
                ):
                    best_index = event_index
                    best_specificity = specificity
                    best_timestamp = event_ts

            if best_index is not None:
                keep_indices.add(best_index)

        return keep_indices

    @staticmethod
    def _is_base_relation_access(path_type):
        """Return True when *path_type* is a direct base-relation access path."""
        if not path_type:
            return False

        return path_type.endswith("Scan")

    @staticmethod
    def _has_lineage_relationship(src_event, dst_event):
        """Return True if events are directly linked as parent/child paths."""
        src_path_ptr = int(src_event.get("path_ptr", 0))
        dst_path_ptr = int(dst_event.get("path_ptr", 0))
        if not src_path_ptr or not dst_path_ptr:
            return False

        src_outer = int(src_event.get("outer_path_ptr", 0))
        src_inner = int(src_event.get("inner_path_ptr", 0))
        dst_outer = int(dst_event.get("outer_path_ptr", 0))
        dst_inner = int(dst_event.get("inner_path_ptr", 0))

        return (
            src_outer == dst_path_ptr
            or src_inner == dst_path_ptr
            or dst_outer == src_path_ptr
            or dst_inner == src_path_ptr
        )

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
        self.log(f"  Paths considered: {len(events)}")
        self.log(f"  Paths chosen: {len(chosen)}")

        # Create graphviz graph
        dot: "graphviz.Digraph" = graphviz.Digraph(comment=graph_name)
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
        nodes_by_parent_rel = defaultdict(list)
        relation_cluster_nodes = defaultdict(list)
        join_cluster_nodes = defaultdict(list)
        parent_rel_cluster_nodes = defaultdict(list)
        event_records = []
        node_to_event = {}
        node_is_base_access = {}
        nodes_by_path_ptr = defaultdict(list)
        nodes_by_equivalence = defaultdict(list)

        # Process in timestamp order and deduplicate identical ADD_PATH re-adds.
        events = sorted(events, key=lambda e: e.get("timestamp", 0))
        deduplicated_events = []
        seen_signatures = set()
        seen_join_semantic_signatures = set()
        duplicate_count = 0
        semantic_duplicate_count = 0
        for event in events:
            sig = self._event_signature(event)
            if sig in seen_signatures:
                duplicate_count += 1
                continue

            if self._is_join_path_event(event):
                join_sig = self._join_semantic_signature(event)
                if join_sig in seen_join_semantic_signatures:
                    semantic_duplicate_count += 1
                    continue
                seen_join_semantic_signatures.add(join_sig)

            seen_signatures.add(sig)
            deduplicated_events.append(event)

        if duplicate_count:
            self.log(f"  Deduplicated {duplicate_count} repeated ADD_PATH events")
        if semantic_duplicate_count:
            self.log(
                f"  Deduplicated {semantic_duplicate_count} semantically equivalent join ADD_PATH events"
            )

        events = deduplicated_events

        referenced_path_ptrs = set()
        for event in events:
            event_pid = event.get("pid", pid)
            outer_path_ptr = int(event.get("outer_path_ptr", 0))
            inner_path_ptr = int(event.get("inner_path_ptr", 0))
            if outer_path_ptr:
                referenced_path_ptrs.add((event_pid, outer_path_ptr))
            if inner_path_ptr:
                referenced_path_ptrs.add((event_pid, inner_path_ptr))

        chosen_path_ptrs = set()
        for chosen_event in chosen:
            chosen_pid = chosen_event.get("pid", pid)
            chosen_path_ptr = int(chosen_event.get("path_ptr", 0))
            if chosen_path_ptr:
                chosen_path_ptrs.add((chosen_pid, chosen_path_ptr))

        representative_event_indices = self._representative_event_indices(events)

        # Add nodes for each considered path
        for i, event in enumerate(events):
            if i not in representative_event_indices:
                continue

            path_type = event.get("path_type", "Unknown")
            path_node_type_name = event.get("path_node_type_name", "")
            startup_cost = event.get("startup_cost", 0)
            total_cost = event.get("total_cost", 0)
            rows = event.get("rows", 0)
            parent_rel_oid = event.get("parent_rel_oid", 0)
            inner_rel_oid = event.get("inner_rel_oid", 0)
            outer_rel_oid = event.get("outer_rel_oid", 0)
            parent_rti = event.get("parent_rti", 0)
            inner_rti = event.get("inner_rti", 0)
            outer_rti = event.get("outer_rti", 0)
            join_type_name = event.get("join_type_name", "N/A")
            event_pid = event.get("pid", pid)

            # Defensive filter: skip isolated base-path records that have no
            # relation identity and no join linkage. These can occur if tracing
            # captured transient/invalid planner states and only add noise.
            path_ptr = int(event.get("path_ptr", 0))
            parent_rel_ptr = int(event.get("parent_rel_ptr", 0))
            if self._is_isolated_base_path(
                event,
                event_pid,
                referenced_path_ptrs,
                chosen_path_ptrs,
            ):
                continue

            node_id = f"plan_{event_pid}_{i}"

            fillcolor = "lightblue"
            penwidth = "1"
            oid_lines = []
            if parent_rel_oid:
                oid_lines.append(self._format_oid_line("Parent", parent_rel_oid))
            if outer_rel_oid:
                oid_lines.append(self._format_oid_line("Outer", outer_rel_oid))
            if inner_rel_oid:
                oid_lines.append(self._format_oid_line("Inner", inner_rel_oid))

            oid_text = ""
            if oid_lines:
                oid_text = "\\n" + "\\n".join(oid_lines)

            path_identity_line = f"Type: {path_node_type_name}\n"

            label = (
                f"{path_type}\n"
                f"{path_identity_line}"
                f"Startup: {self._format_cost(startup_cost)}\n"
                f"Total: {self._format_cost(total_cost)}\n"
                f"Rows: {rows}"
                f"{oid_text}"
            )

            dot.node(node_id, label, fillcolor=fillcolor, penwidth=penwidth)
            nodes_by_type[path_type].append((node_id, total_cost, startup_cost))
            node_to_event[node_id] = event
            node_is_base_access[node_id] = self._is_base_relation_access(path_type)
            if path_ptr:
                nodes_by_path_ptr[(event_pid, path_ptr)].append(
                    (event.get("timestamp", 0), node_id, path_type)
                )

            nodes_by_equivalence[self._selection_equivalence_key(event)].append(node_id)

            rel_key = (event_pid, parent_rti)
            if parent_rti:
                nodes_by_relation[rel_key].append(node_id)
                if self._is_base_relation_access(path_type):
                    relation_cluster_key = (event_pid, parent_rti, parent_rel_oid)
                    relation_cluster_nodes[relation_cluster_key].append(
                        (node_id, event)
                    )
            elif self._is_join_path_event(event):
                join_cluster_key = (
                    event_pid,
                    join_type_name,
                    outer_rti,
                    inner_rti,
                    outer_rel_oid,
                    inner_rel_oid,
                )
                join_cluster_nodes[join_cluster_key].append((node_id, event))
            elif parent_rel_ptr:
                parent_rel_key = (event_pid, parent_rel_ptr)
                nodes_by_parent_rel[parent_rel_key].append(node_id)
                parent_rel_cluster_nodes[parent_rel_key].append((node_id, event))

            event_records.append((node_id, event))

        # Group base relation alternatives into dedicated clusters.
        # To ensure they remain on the left edge of the layout we wrap
        # the individual relation clusters inside an additional outer
        # "left" cluster.  By using rank="source" we coerce Graphviz
        # to treat the entire collection as the source rank, pushing the
        # group to the very leftmost side of the graph (rankdir=LR).
        with dot.subgraph(name="cluster_left") as left_outer:  # type: ignore
            # outermost container forces source rank for maximum leftness
            left_outer.attr(rank="source")
            with left_outer.subgraph(name="cluster_relations") as main_rel:  # type: ignore
                main_rel.attr(rank="source")
                for cluster_index, cluster_key in enumerate(
                    sorted(relation_cluster_nodes.keys(), key=self._cluster_sort_key)
                ):
                    event_pid, parent_rti, parent_rel_oid = cluster_key
                    oid_label = self._format_oid_label(parent_rel_oid)
                    cluster_name = f"cluster_rel_{cluster_index}"
                    # create a nested subgraph for each relation cluster
                    with main_rel.subgraph(name=cluster_name) as rel_cluster:  # type: ignore
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
                else self._format_oid_label(outer_rel_oid)
            )
            inner_label = (
                f"RTI {inner_rti}"
                if inner_rti
                else self._format_oid_label(inner_rel_oid)
            )
            with dot.subgraph(name=cluster_name) as join_cluster:  # type: ignore
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

        # Group non-RTI alternatives (e.g. AggPath) by parent_rel_ptr.
        for cluster_index, cluster_key in enumerate(
            sorted(
                parent_rel_cluster_nodes.keys(), key=self._parent_rel_cluster_sort_key
            )
        ):
            event_pid, parent_rel_ptr = cluster_key
            cluster_name = f"cluster_parent_rel_{cluster_index}"
            with dot.subgraph(name=cluster_name) as parent_cluster:  # type: ignore
                parent_cluster.attr(
                    label=f"Derived relation {parent_rel_ptr}",
                    color="gray55",
                    style="rounded,dashed",
                    penwidth="1.2",
                    fontname="Arial",
                    fontsize="10",
                )
                if pid is None:
                    parent_cluster.attr(
                        label=f"PID {event_pid} • Derived relation {parent_rel_ptr}"
                    )
                for node_id, _ in sorted(
                    parent_rel_cluster_nodes[cluster_key],
                    key=lambda item: item[1].get("timestamp", 0),
                ):
                    parent_cluster.node(node_id)

        # Connect progression per relation.
        for rel_key, rel_nodes in nodes_by_relation.items():
            if len(rel_nodes) <= 1:
                continue
            for i in range(len(rel_nodes) - 1):
                src_node = rel_nodes[i]
                dst_node = rel_nodes[i + 1]
                src_event = node_to_event[src_node]
                dst_event = node_to_event[dst_node]
                if self._has_lineage_relationship(src_event, dst_event):
                    continue
                if (
                    src_event.get("path_type") == "T_Agg"
                    and dst_event.get("path_type") == "T_Agg"
                ):
                    continue
                if (
                    src_event.get("path_type") == "T_Sort"
                    and dst_event.get("path_type") == "T_Agg"
                ):
                    continue
                if node_is_base_access.get(src_node) and node_is_base_access.get(
                    dst_node
                ):
                    dot.edge(
                        src_node,
                        dst_node,
                        style="dashed",
                        color="gray50",
                        xlabel="alt",
                        constraint="false",
                        arrowhead="none",
                    )
                else:
                    dot.edge(
                        src_node,
                        dst_node,
                        color="black",
                        constraint="false",
                    )

        # Connect progression within non-RTI parent-rel groups.
        for parent_rel_key, rel_nodes in nodes_by_parent_rel.items():
            if len(rel_nodes) <= 1:
                continue
            for i in range(len(rel_nodes) - 1):
                src_node = rel_nodes[i]
                dst_node = rel_nodes[i + 1]
                src_event = node_to_event[src_node]
                dst_event = node_to_event[dst_node]
                if self._has_lineage_relationship(src_event, dst_event):
                    continue
                if (
                    src_event.get("path_type") == "T_Agg"
                    and dst_event.get("path_type") == "T_Agg"
                ):
                    continue
                if (
                    src_event.get("path_type") == "T_Sort"
                    and dst_event.get("path_type") == "T_Agg"
                ):
                    continue
                dot.edge(
                    src_node,
                    dst_node,
                    style="dashed",
                    color="gray50",
                    xlabel="alt",
                    constraint="false",
                    arrowhead="none",
                )

        # Use CREATE_PLAN events only to identify matching ADD_PATH nodes.
        chosen_node_ids = set()
        for chosen_event in sorted(chosen, key=lambda e: e.get("timestamp", 0)):
            chosen_pid = chosen_event.get("pid", pid)
            chosen_path_ptr = int(chosen_event.get("path_ptr", 0))
            if not chosen_path_ptr:
                continue

            direct_node = self._resolve_node_by_pointer(
                nodes_by_path_ptr,
                chosen_pid,
                chosen_path_ptr,
                chosen_event.get("timestamp", 0),
            )
            if direct_node:
                chosen_node_ids.add(
                    self._promote_chosen_node(
                        direct_node,
                        node_to_event,
                        nodes_by_equivalence,
                    )
                )

        # Re-style only matched chosen ADD_PATH nodes
        for chosen_node_id in chosen_node_ids:
            event = node_to_event[chosen_node_id]
            path_type = event.get("path_type", "Unknown")
            path_node_type_name = event.get("path_node_type_name", "")
            startup_cost = event.get("startup_cost", 0)
            total_cost = event.get("total_cost", 0)
            rows = event.get("rows", 0)
            parent_rel_oid = event.get("parent_rel_oid", 0)
            inner_rel_oid = event.get("inner_rel_oid", 0)
            outer_rel_oid = event.get("outer_rel_oid", 0)

            oid_lines = []
            if parent_rel_oid:
                oid_lines.append(self._format_oid_line("Parent", parent_rel_oid))
            if outer_rel_oid:
                oid_lines.append(self._format_oid_line("Outer", outer_rel_oid))
            if inner_rel_oid:
                oid_lines.append(self._format_oid_line("Inner", inner_rel_oid))

            oid_text = ""
            if oid_lines:
                oid_text = "\\n" + "\\n".join(oid_lines)

            chosen_label = (
                f"{path_type}\n[CHOSEN]\n"
                f"Type: {path_node_type_name}\n"
                f"Startup: {self._format_cost(startup_cost)}\n"
                f"Total: {self._format_cost(total_cost)}\n"
                f"Rows: {rows}"
                f"{oid_text}"
            )
            dot.node(chosen_node_id, chosen_label, fillcolor="lightgreen", penwidth="3")

        # Build explicit parent-child lineage from path pointers.
        for node_id, event in event_records:
            path_type = event.get("path_type", "Unknown")
            event_pid = event.get("pid", pid)
            outer_path_ptr = int(event.get("outer_path_ptr", 0))
            inner_path_ptr = int(event.get("inner_path_ptr", 0))
            event_ts = event.get("timestamp", 0)

            if outer_path_ptr:
                outer_node = self._resolve_node_by_pointer(
                    nodes_by_path_ptr,
                    event_pid,
                    outer_path_ptr,
                    event_ts,
                    event.get("outer_path_type_name"),
                )
                if outer_node and outer_node != node_id:
                    outer_edge_label = (
                        "subpath"
                        if path_type in ("T_Sort", "T_Agg", "T_Result")
                        else "outer"
                    )
                    dot.edge(
                        outer_node,
                        node_id,
                        color="steelblue3",
                        xlabel=outer_edge_label,
                        minlen="2",
                    )

            if inner_path_ptr:
                inner_node = self._resolve_node_by_pointer(
                    nodes_by_path_ptr,
                    event_pid,
                    inner_path_ptr,
                    event_ts,
                    event.get("inner_path_type_name"),
                )
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
        rendered_events = [event for _node_id, event in event_records]

        if rendered_events:
            total_plans = len(rendered_events)
            cheapest_plan = min(
                rendered_events, key=lambda e: e.get("total_cost", float("inf"))
            )
            most_expensive_plan = max(
                rendered_events, key=lambda e: e.get("total_cost", 0)
            )

            stats_label = (
                f"Statistics\\n"
                f"Total paths considered: {total_plans}\\n"
                f"Cheapest: {cheapest_plan.get('path_type')} ({cheapest_plan.get('total_cost', 0):.2f})\\n"
                f"Most expensive: {most_expensive_plan.get('path_type')} ({most_expensive_plan.get('total_cost', 0):.2f})"
            )

            dot.node("stats", stats_label, shape="note", fillcolor="lightyellow")

            legend_label = (
                "Legend\\n"
                "Blue edge: outer/subpath input\\n"
                "Orange edge: inner input\\n"
                "Dashed cluster: relation/join group\\n"
                "Green node: selected plan\\n"
                "Black edge: relation path progression"
            )
            dot.node("legend", legend_label, shape="note", fillcolor="white")

        return dot

    @staticmethod
    def _resolve_node_by_pointer(
        nodes_by_path_ptr,
        event_pid,
        path_ptr,
        event_ts,
        expected_path_type=None,
    ):
        """Resolve a pointer to the closest node around an event timestamp.

        Child path snapshots for ADD_PATH can be emitted immediately after the
        parent join event, so we allow a small forward window and prefer the
        closest candidate in time.
        """
        forward_window_ns = 5_000_000
        candidates = nodes_by_path_ptr.get((event_pid, path_ptr), [])
        if not candidates:
            return None

        if expected_path_type:
            typed_candidates = [
                candidate
                for candidate in candidates
                if candidate[2] == expected_path_type
            ]
            if typed_candidates:
                candidates = typed_candidates

        prev_candidate = None
        next_candidate = None

        for candidate_ts, candidate_node, _candidate_type in candidates:
            if candidate_ts <= event_ts:
                prev_candidate = (candidate_ts, candidate_node)
                continue
            next_candidate = (candidate_ts, candidate_node)
            break

        selected_node = candidates[-1][1]

        if prev_candidate and next_candidate:
            prev_delta = event_ts - prev_candidate[0]
            next_delta = next_candidate[0] - event_ts
            # 5ms forward window: large enough for emitted sibling events,
            # small enough to avoid unrelated later pointer reuse.
            if next_delta <= prev_delta and next_delta <= forward_window_ns:
                selected_node = next_candidate[1]
            else:
                selected_node = prev_candidate[1]
        elif next_candidate:
            if next_candidate[0] - event_ts <= forward_window_ns:
                selected_node = next_candidate[1]
        elif prev_candidate:
            selected_node = prev_candidate[1]

        return selected_node

    def _is_isolated_base_path(  # pylint: disable=too-many-boolean-expressions
        self,
        event,
        event_pid,
        referenced_path_ptrs,
        chosen_path_ptrs,
    ):
        """Return True when *event* represents a stray base-path with no
        identifying relation or join links and no later references.

        The large boolean expression that used to live inline in
        :meth:`create_graph` was extracted here so that pylint's
        ``too-many-boolean-expressions`` check is satisfied.
        """
        parent_rti = int(event.get("parent_rti", 0))
        inner_rti = int(event.get("inner_rti", 0))
        outer_rti = int(event.get("outer_rti", 0))
        parent_rel_ptr = int(event.get("parent_rel_ptr", 0))
        path_ptr = int(event.get("path_ptr", 0))

        if (
            parent_rti == 0
            and inner_rti == 0
            and outer_rti == 0
            and parent_rel_ptr == 0
            and (event_pid, path_ptr) not in referenced_path_ptrs
            and (event_pid, path_ptr) not in chosen_path_ptrs
        ):
            return True
        return False

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
