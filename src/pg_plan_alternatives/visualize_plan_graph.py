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
from datetime import datetime

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
            with open(self.args.input, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        self.events.append(event)
                        
                        pid = event.get('pid')
                        event_type = event.get('event_type')
                        
                        if event_type == 'ADD_PATH':
                            self.plans_by_pid[pid].append(event)
                        elif event_type == 'CREATE_PLAN':
                            self.chosen_plans[pid].append(event)
                    except json.JSONDecodeError as e:
                        self.log(f"Warning: Failed to parse line: {line[:50]}... - {e}")
        except FileNotFoundError:
            print(f"Error: Input file not found: {self.args.input}", file=sys.stderr)
            sys.exit(1)
        
        self.log(f"Loaded {len(self.events)} events")
        self.log(f"Found {len(self.plans_by_pid)} PIDs")

    def create_graph(self, pid=None):
        """Create a graph for a specific PID or all PIDs"""
        if pid:
            graph_name = f"Query Plans (PID {pid})"
            events = self.plans_by_pid[pid]
            chosen = self.chosen_plans.get(pid, [])
        else:
            graph_name = "Query Plans (All PIDs)"
            events = [e for events_list in self.plans_by_pid.values() for e in events_list]
            chosen = [e for chosen_list in self.chosen_plans.values() for e in chosen_list]

        self.log(f"Creating graph: {graph_name}")
        self.log(f"  Plans considered: {len(events)}")
        self.log(f"  Plans chosen: {len(chosen)}")

        # Create graphviz graph
        dot = graphviz.Digraph(comment=graph_name)
        dot.attr(rankdir='TB')
        dot.attr('node', shape='box', style='rounded,filled', fontname='Arial')
        
        # Set graph attributes for better layout
        dot.attr(splines='ortho', nodesep='0.5', ranksep='0.7')

        # Track nodes by path type to group similar plans
        nodes_by_type = defaultdict(list)
        
        # Add nodes for each considered path
        for i, event in enumerate(events):
            path_type = event.get('path_type', 'Unknown')
            startup_cost = event.get('startup_cost', 0)
            total_cost = event.get('total_cost', 0)
            rows = event.get('rows', 0)
            
            node_id = f"plan_{pid}_{i}" if pid else f"plan_all_{i}"
            
            # Check if this plan was chosen
            is_chosen = any(
                c.get('path_type') == path_type and
                abs(c.get('total_cost', 0) - total_cost) < 0.01
                for c in chosen
            )
            
            # Style based on whether it was chosen
            if is_chosen:
                fillcolor = 'lightgreen'
                penwidth = '3'
                label = f"{path_type}\n[CHOSEN]\nStartup: {startup_cost:.2f}\nTotal: {total_cost:.2f}\nRows: {rows}"
            else:
                fillcolor = 'lightblue'
                penwidth = '1'
                label = f"{path_type}\nStartup: {startup_cost:.2f}\nTotal: {total_cost:.2f}\nRows: {rows}"
            
            dot.node(node_id, label, fillcolor=fillcolor, penwidth=penwidth)
            nodes_by_type[path_type].append((node_id, total_cost, startup_cost))

        # If we have multiple plans of the same type, show cost comparison
        for path_type, nodes in nodes_by_type.items():
            if len(nodes) > 1:
                # Sort by total cost
                nodes.sort(key=lambda x: x[1])
                
                # Add invisible edges to group similar plans
                for i in range(len(nodes) - 1):
                    dot.edge(nodes[i][0], nodes[i+1][0], style='invis')

        # Add summary statistics
        if events:
            total_plans = len(events)
            cheapest_plan = min(events, key=lambda e: e.get('total_cost', float('inf')))
            most_expensive_plan = max(events, key=lambda e: e.get('total_cost', 0))
            
            stats_label = (
                f"Statistics\\n"
                f"Total plans considered: {total_plans}\\n"
                f"Cheapest: {cheapest_plan.get('path_type')} ({cheapest_plan.get('total_cost', 0):.2f})\\n"
                f"Most expensive: {most_expensive_plan.get('path_type')} ({most_expensive_plan.get('total_cost', 0):.2f})"
            )
            
            dot.node('stats', stats_label, shape='note', fillcolor='lightyellow')

        return dot

    def visualize(self):
        """Create visualization"""
        self.load_events()

        if not self.events:
            print("No events to visualize", file=sys.stderr)
            return

        # Determine output format from file extension
        output_path = self.args.output
        if output_path.endswith('.html'):
            # For HTML, we'll create an SVG and embed it
            format = 'svg'
        else:
            # Extract format from extension
            parts = output_path.rsplit('.', 1)
            if len(parts) == 2:
                format = parts[1].lower()
                output_path = parts[0]
            else:
                format = 'png'

        if self.args.group_by_pid:
            # Create separate graphs for each PID
            for pid in self.plans_by_pid.keys():
                dot = self.create_graph(pid)
                output_file = f"{output_path}_pid{pid}"
                self.log(f"Rendering graph for PID {pid} to {output_file}.{format}")
                dot.render(output_file, format=format, cleanup=True)
        else:
            # Create single graph for all PIDs
            dot = self.create_graph()
            self.log(f"Rendering graph to {output_path}.{format}")
            
            if self.args.output.endswith('.html'):
                # Create HTML with embedded SVG
                svg_data = dot.pipe(format='svg').decode('utf-8')
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
                with open(self.args.output, 'w') as f:
                    f.write(html_content)
                self.log(f"HTML file created: {self.args.output}")
            else:
                dot.render(output_path, format=format, cleanup=True)
                self.log(f"Graph file created: {output_path}.{format}")

        self.log("Visualization complete")


def main():
    """Main entry point"""
    args = parser.parse_args()

    visualizer = PlanVisualizer(args)
    visualizer.visualize()


if __name__ == "__main__":
    main()
