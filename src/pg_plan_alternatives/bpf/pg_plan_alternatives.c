#include <uapi/linux/ptrace.h>

/*
 * Placeholder for EVENT_* defines
 * Will be automatically generated from Python Events ENUM
 */
__DEFINES__

typedef struct PlanEvent {
    u32 pid;
    u64 timestamp;
    u32 event_type;
    
    // Path information
    u32 path_type;        // NodeTag type
    u64 startup_cost;     // Cost_startup (converted to fixed-point)
    u64 total_cost;       // Cost_total (converted to fixed-point)
    u64 rows;             // Plan rows estimate
    u32 width;            // Plan width
    
    // Parent relation info
    u32 parent_relid;     // Parent relation OID
    u32 relid;            // Relation OID (for scan paths)
    
    // Join information
    u32 join_type;        // JoinType enum
    u32 inner_relid;      // Inner relation for joins
    u32 outer_relid;      // Outer relation for joins
    
    char query_string[256]; // Query string if available
} PlanEvent;

BPF_PERF_OUTPUT(planevents);

static void fill_basic_data(PlanEvent *event) {
    event->pid = bpf_get_current_pid_tgid();
    event->timestamp = bpf_ktime_get_ns();
}

/*
 * PostgreSQL add_path function
 * 
 * From src/backend/optimizer/util/pathnode.c:
 * void add_path(RelOptInfo *parent_rel, Path *new_path)
 * 
 * Path structure (from src/include/nodes/relation.h):
 * typedef struct Path {
 *     NodeTag     type;
 *     NodeTag     pathtype;  // Actually this is stored differently in different PG versions
 *     
 *     RelOptInfo *parent;
 *     PathTarget *pathtarget;
 *     ParamPathInfo *param_info;
 *     bool        parallel_aware;
 *     bool        parallel_safe;
 *     int         parallel_workers;
 *     
 *     Cost        startup_cost;  // double
 *     Cost        total_cost;    // double
 *     
 *     List       *pathkeys;
 * } Path;
 *
 * RelOptInfo structure:
 * typedef struct RelOptInfo {
 *     NodeTag     type;
 *     RelOptKind  reloptkind;
 *     Relids      relids;
 *     double      rows;
 *     bool        consider_startup;
 *     bool        consider_param_startup;
 *     bool        consider_parallel;
 *     struct Path *cheapest_startup_path;
 *     struct Path *cheapest_total_path;
 *     struct Path *cheapest_unique_path;
 *     List       *pathlist;
 *     List       *ppilist;
 *     List       *partial_pathlist;
 *     struct Path *cheapest_parameterized_path;
 *     Relids      relid;
 *     ...
 * } RelOptInfo;
 */

/*
 * Read a double as fixed-point (multiply by 1000 and convert to u64)
 */
static u64 read_double_as_fixed(void *ptr) {
    double value;
    bpf_probe_read_user(&value, sizeof(double), ptr);
    // Convert to fixed-point with 3 decimal places
    return (u64)(value * 1000.0);
}

int bpf_add_path(struct pt_regs *ctx) {
    PlanEvent event = {.event_type = EVENT_ADD_PATH};
    fill_basic_data(&event);
    
    // Get function parameters
    void *parent_rel = (void *)PT_REGS_PARM1(ctx);
    void *new_path = (void *)PT_REGS_PARM2(ctx);
    
    if (!parent_rel || !new_path) {
        return 0;
    }
    
    // Read Path structure fields
    // Offset 0: NodeTag type (4 bytes)
    bpf_probe_read_user(&event.path_type, sizeof(u32), new_path);
    
    // The exact offsets depend on PostgreSQL version and architecture
    // For 64-bit systems with typical alignment:
    // - NodeTag type: offset 0 (4 bytes)
    // - pathtype: offset 4 (4 bytes) 
    // - parent: offset 8 (8 bytes pointer)
    // - pathtarget: offset 16 (8 bytes pointer)
    // - param_info: offset 24 (8 bytes pointer)
    // - parallel_aware, parallel_safe, parallel_workers: offset 32 (bools + int)
    // - startup_cost: offset 40 (8 bytes double)
    // - total_cost: offset 48 (8 bytes double)
    
    // Read costs (as doubles at typical offsets)
    void *startup_cost_ptr = new_path + 40;
    void *total_cost_ptr = new_path + 48;
    
    event.startup_cost = read_double_as_fixed(startup_cost_ptr);
    event.total_cost = read_double_as_fixed(total_cost_ptr);
    
    // Read parent RelOptInfo fields
    // RelOptInfo has relids at various offsets depending on version
    // We'll try to read what we can
    bpf_probe_read_user(&event.parent_relid, sizeof(u32), parent_rel + 32);
    
    // For IndexPath and similar, there's a 'path' substructure first
    // then additional fields like indexinfo
    // We'll capture what we can generically
    
    // Try to read rows estimate from parent RelOptInfo
    double rows_estimate;
    bpf_probe_read_user(&rows_estimate, sizeof(double), parent_rel + 16);
    event.rows = (u64)rows_estimate;
    
    planevents.perf_submit(ctx, &event, sizeof(PlanEvent));
    return 0;
}

/*
 * Also trace create_plan to see which path was actually chosen
 */
int bpf_create_plan(struct pt_regs *ctx) {
    PlanEvent event = {.event_type = EVENT_CREATE_PLAN};
    fill_basic_data(&event);
    
    void *path = (void *)PT_REGS_PARM2(ctx);
    
    if (!path) {
        return 0;
    }
    
    // Read path type
    bpf_probe_read_user(&event.path_type, sizeof(u32), path);
    
    // Read costs
    void *startup_cost_ptr = path + 40;
    void *total_cost_ptr = path + 48;
    
    event.startup_cost = read_double_as_fixed(startup_cost_ptr);
    event.total_cost = read_double_as_fixed(total_cost_ptr);
    
    planevents.perf_submit(ctx, &event, sizeof(PlanEvent));
    return 0;
}
