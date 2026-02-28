#include <uapi/linux/ptrace.h>

/*
 * Placeholder for EVENT_* defines
 * Will be automatically generated from Python Events ENUM
 */
__DEFINES__

/*
 * Placeholder for offset defines generated from DWARF.
 */
__OFFSETS__

typedef struct PlanEvent {
  u32 pid;
  u64 timestamp;
  u32 event_type;

  // Pointer identities (used for lineage reconstruction in user-space)
  u64 path_ptr;
  u64 parent_rel_ptr;
  u64 outer_path_ptr;
  u64 inner_path_ptr;
  u32 outer_path_type;
  u32 inner_path_type;

  // Path information
  u32 path_type;     // NodeTag type
  u64 startup_cost;  // Cost_startup (converted to fixed-point)
  u64 total_cost;    // Cost_total (converted to fixed-point)
  u64 rows;          // Plan rows estimate

  // Parent relation info
  u32 parent_relid;  // Parent range-table index (RelOptInfo.relid)
  u32 relid;         // Parent relation OID (resolved from RangeTblEntry)

  // Join information
  u32 join_type;      // JoinType enum
  u32 inner_relid;    // Inner RT index for joins
  u32 outer_relid;    // Outer RT index for joins
  u32 inner_rel_oid;  // Inner relation OID for joins
  u32 outer_rel_oid;  // Outer relation OID for joins

  char query_string[256];  // Query string if available
} PlanEvent;

BPF_PERF_OUTPUT(planevents);

// Per-CPU event storage to avoid exceeding the 512-byte BPF stack limit.
BPF_PERCPU_ARRAY(plan_event_scratch, PlanEvent, 1);

typedef struct RelMeta {
  u32 rti;
  u32 rel_oid;
} RelMeta;

typedef struct RelMetaKey {
  u32 pid;
  u64 rel_ptr;
} RelMetaKey;

BPF_HASH(relmeta_by_relptr, RelMetaKey, RelMeta, 8192);

#define MAX_CREATE_PLAN_NODES 16
// Per-CPU stack storage for CREATE_PLAN path traversal (stores Path* as u64).
BPF_PERCPU_ARRAY(create_plan_stack, u64, MAX_CREATE_PLAN_NODES);

static __always_inline int create_plan_stack_set(u32 idx, void *path_ptr) {
  u64 *slot = create_plan_stack.lookup(&idx);
  if (!slot) {
    return 0;
  }

  *slot = (u64)path_ptr;
  return 1;
}

static __always_inline PlanEvent *get_plan_event_scratch(void) {
  u32 idx = 0;
  return plan_event_scratch.lookup(&idx);
}

static __always_inline void *create_plan_stack_get(u32 idx) {
  u64 *slot = create_plan_stack.lookup(&idx);
  if (!slot) {
    return 0;
  }

  return (void *)(*slot);
}

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
 *     NodeTag     pathtype;
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
 * Read raw double bits as u64. Do not perform any floating-point
 * arithmetic in BPF — the compiler will emit unsupported builtins
 * (e.g. __muldf3). Convert IEEE-754 bits to numeric values in
 * user-space (Python) instead.
 */
static u64 read_double_bits(void *ptr) {
  u64 bits = 0;
  bpf_probe_read_user(&bits, sizeof(bits), ptr);
  return bits;
}

static void fill_rel_identity_from_path(void *path, u32 *relid, u32 *rel_oid) {
  if (!path) {
    return;
  }

  // Path.parent (RelOptInfo*)
  void *rel = 0;
  bpf_probe_read_user(&rel, sizeof(rel), path + OFFSET_PATH_PARENT);
  if (!rel) {
    return;
  }

  // RelOptInfo.relid (RT index)
  bpf_probe_read_user(relid, sizeof(*relid), rel + OFFSET_RELOPTINFO_RELID);

  // Resolve real relation OID for base rels via rel pointer map
  // keyed by (pid, relptr). Only apply when RTI matches to avoid
  // stale pointer reuse attaching wrong OIDs.
  RelMetaKey rel_ptr_key = {};
  rel_ptr_key.pid = bpf_get_current_pid_tgid();
  rel_ptr_key.rel_ptr = (u64)rel;
  RelMeta *meta = relmeta_by_relptr.lookup(&rel_ptr_key);
  if (meta && *relid && meta->rti == *relid) {
    *rel_oid = meta->rel_oid;
  }
}

static int fill_plan_event_from_path(void *path, PlanEvent *event,
                                     void **outer_path, void **inner_path) {
  if (!path || !event) {
    return 0;
  }

  event->path_ptr = (u64)path;

  void *parent_rel = 0;
  bpf_probe_read_user(&parent_rel, sizeof(parent_rel),
                      path + OFFSET_PATH_PARENT);
  event->parent_rel_ptr = (u64)parent_rel;

  // Path.pathtype
  bpf_probe_read_user(&event->path_type, sizeof(u32),
                      path + OFFSET_PATH_PATHTYPE);

  // Path rows and costs
  event->rows = read_double_bits(path + OFFSET_PATH_ROWS);
  event->startup_cost = read_double_bits(path + OFFSET_PATH_STARTUP_COST);
  event->total_cost = read_double_bits(path + OFFSET_PATH_TOTAL_COST);

  // Parent relation identity from Path.parent (RelOptInfo*)
  fill_rel_identity_from_path(path, &event->parent_relid, &event->relid);

  // JoinPath fields
  // Only try to decode join internals for join/upper rel paths
  // (parent_relid==0). This prevents reading random offsets from base scan
  // paths and emitting bogus CREATE_PLAN child nodes.
  u32 join_type = 0;
  void *outer = 0;
  void *inner = 0;

  if (event->parent_relid == 0) {
    bpf_probe_read_user(&join_type, sizeof(join_type),
                        path + OFFSET_JOINPATH_JOINTYPE);
    bpf_probe_read_user(&outer, sizeof(outer),
                        path + OFFSET_JOINPATH_OUTERJOINPATH);
    bpf_probe_read_user(&inner, sizeof(inner),
                        path + OFFSET_JOINPATH_INNERJOINPATH);

    event->outer_path_ptr = (u64)outer;
    event->inner_path_ptr = (u64)inner;

    if (join_type <= 8) {
      event->join_type = join_type;
      if (outer) {
        bpf_probe_read_user(&event->outer_path_type, sizeof(u32),
                            outer + OFFSET_PATH_PATHTYPE);
        fill_rel_identity_from_path(outer, &event->outer_relid,
                                    &event->outer_rel_oid);
      }
      if (inner) {
        bpf_probe_read_user(&event->inner_path_type, sizeof(u32),
                            inner + OFFSET_PATH_PATHTYPE);
        fill_rel_identity_from_path(inner, &event->inner_relid,
                                    &event->inner_rel_oid);
      }
    }
  }

  if (outer_path) {
    *outer_path = outer;
  }
  if (inner_path) {
    *inner_path = inner;
  }

  return 1;
}

int bpf_add_path(struct pt_regs *ctx) {
  PlanEvent *event = get_plan_event_scratch();
  if (!event) {
    return 0;
  }

  __builtin_memset(event, 0, sizeof(*event));
  event->event_type = EVENT_ADD_PATH;
  fill_basic_data(event);

  // Get function parameters
  void *parent_rel = (void *)PT_REGS_PARM1(ctx);
  void *new_path = (void *)PT_REGS_PARM2(ctx);

  if (!parent_rel || !new_path) {
    return 0;
  }

  void *outer_path = 0;
  void *inner_path = 0;
  if (!fill_plan_event_from_path(new_path, event, &outer_path, &inner_path)) {
    return 0;
  }

  event->parent_rel_ptr = (u64)parent_rel;

  // Prefer parent_rel from function args when available for stability.
  bpf_probe_read_user(&event->parent_relid, sizeof(u32),
                      parent_rel + OFFSET_RELOPTINFO_RELID);
  RelMetaKey rel_ptr_key = {};
  rel_ptr_key.pid = event->pid;
  rel_ptr_key.rel_ptr = (u64)parent_rel;
  RelMeta *meta = relmeta_by_relptr.lookup(&rel_ptr_key);
  if (meta && meta->rel_oid && event->parent_relid &&
      meta->rti == event->parent_relid) {
    event->relid = meta->rel_oid;
  }

  planevents.perf_submit(ctx, event, sizeof(PlanEvent));

  // Also emit immediate child paths so non-added wrapper nodes (e.g.
  // MaterialPath under JoinPath.innerjoinpath) are visible in ADD_PATH traces.
  if (outer_path) {
    __builtin_memset(event, 0, sizeof(*event));
    event->event_type = EVENT_ADD_PATH;
    fill_basic_data(event);
    if (fill_plan_event_from_path(outer_path, event, 0, 0)) {
      planevents.perf_submit(ctx, event, sizeof(PlanEvent));
    }
  }

  if (inner_path) {
    __builtin_memset(event, 0, sizeof(*event));
    event->event_type = EVENT_ADD_PATH;
    fill_basic_data(event);
    if (fill_plan_event_from_path(inner_path, event, 0, 0)) {
      planevents.perf_submit(ctx, event, sizeof(PlanEvent));
    }
  }

  return 0;
}

/*
 * Track RelOptInfo* -> relation OID mappings while planner builds base-relation
 * pathlists.
 *
 * set_rel_pathlist(PlannerInfo *root, RelOptInfo *rel, Index rti,
 *                  RangeTblEntry *rte)
 */
int bpf_set_rel_pathlist(struct pt_regs *ctx) {
  void *rel = (void *)PT_REGS_PARM2(ctx);
  void *rte = (void *)PT_REGS_PARM4(ctx);
  u32 rti = (u32)PT_REGS_PARM3(ctx);

  if (!rel || !rte || !rti) {
    return 0;
  }

  u32 rtekind = 0;
  bpf_probe_read_user(&rtekind, sizeof(rtekind),
                      rte + OFFSET_RANGETBLENTRY_RTEKIND);

  // RTE_RELATION = 0
  if (rtekind != 0) {
    return 0;
  }

  RelMeta meta = {};
  meta.rti = rti;
  bpf_probe_read_user(&meta.rel_oid, sizeof(meta.rel_oid),
                      rte + OFFSET_RANGETBLENTRY_RELID);

  RelMetaKey rel_ptr_key = {};
  rel_ptr_key.pid = bpf_get_current_pid_tgid();
  rel_ptr_key.rel_ptr = (u64)rel;
  relmeta_by_relptr.update(&rel_ptr_key, &meta);

  return 0;
}

/*
 * Also trace create_plan to see which path was actually chosen
 */
int bpf_create_plan(struct pt_regs *ctx) {
  void *path = (void *)PT_REGS_PARM2(ctx);

  if (!path) {
    return 0;
  }

  // Bounded DFS over selected path tree.
  int sp = 0;

  create_plan_stack_set(sp, path);
  sp++;

  for (int iter = 0; iter < MAX_CREATE_PLAN_NODES; iter++) {
    if (sp <= 0) {
      break;
    }

    sp--;
    void *current_path = create_plan_stack_get((u32)sp);
    if (!current_path) {
      continue;
    }

    PlanEvent *event = get_plan_event_scratch();
    if (!event) {
      continue;
    }

    __builtin_memset(event, 0, sizeof(*event));
    event->event_type = EVENT_CREATE_PLAN;
    fill_basic_data(event);

    void *outer_path = 0;
    void *inner_path = 0;
    if (!fill_plan_event_from_path(current_path, event, &outer_path,
                                   &inner_path)) {
      continue;
    }

    planevents.perf_submit(ctx, event, sizeof(PlanEvent));

    if (outer_path && sp < MAX_CREATE_PLAN_NODES) {
      create_plan_stack_set((u32)sp, outer_path);
      sp++;
    }
    if (inner_path && sp < MAX_CREATE_PLAN_NODES) {
      create_plan_stack_set((u32)sp, inner_path);
      sp++;
    }
  }

  return 0;
}
