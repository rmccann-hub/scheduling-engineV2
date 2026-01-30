# OR-Tools constraint builders for the cell scheduling engine.
# Version: 1.0.0
# Defines task intervals, precedence constraints, and resource constraints.

from dataclasses import dataclass, field
from typing import Literal

from ortools.sat.python import cp_model

from .constants import CycleTimeConstants, CellColor
from .data_loader import Job
from .calculated_fields import CalculatedFields


# Task types in execution order
TASK_SEQUENCE = ("SETUP", "LAYOUT", "POUR", "CURE", "UNLOAD")

# Tasks that require operator
OPERATOR_TASKS = frozenset({"SETUP", "LAYOUT", "POUR", "UNLOAD"})


@dataclass
class TaskTimes:
    """Task durations for a specific job/panel.
    
    Attributes:
        setup: SETUP duration in minutes (0 if same fixture as prior panel).
        layout: LAYOUT duration in minutes.
        pour: POUR duration in minutes (base × molds).
        cure: CURE duration in minutes (adjusted for summer).
        unload: UNLOAD duration in minutes.
    """
    setup: int
    layout: int
    pour: int
    cure: int
    unload: int
    
    @property
    def operator_time(self) -> int:
        """Total operator time for this panel (excludes CURE)."""
        return self.setup + self.layout + self.pour + self.unload
    
    @property
    def total_time(self) -> int:
        """Total time for this panel including CURE."""
        return self.setup + self.layout + self.pour + self.cure + self.unload


@dataclass
class PanelVariables:
    """OR-Tools variables for a single panel on a table.
    
    Attributes:
        table_id: Table identifier (e.g., "RED_1").
        panel_index: Panel ordinal (0-based).
        job_id: Job assigned to this panel.
        task_times: Calculated task durations.
        task_starts: Dict of task name to start time variable.
        task_ends: Dict of task name to end time variable.
        task_intervals: Dict of task name to interval variable.
        operator_intervals: List of interval variables for operator tasks.
        is_scheduled: Boolean variable indicating if panel is scheduled.
    """
    table_id: str
    panel_index: int
    job_id: str
    task_times: TaskTimes
    task_starts: dict[str, cp_model.IntVar] = field(default_factory=dict)
    task_ends: dict[str, cp_model.IntVar] = field(default_factory=dict)
    task_intervals: dict[str, cp_model.IntervalVar] = field(default_factory=dict)
    operator_intervals: list[cp_model.IntervalVar] = field(default_factory=list)
    is_scheduled: cp_model.IntVar | None = None


@dataclass 
class CellScheduleModel:
    """Container for all OR-Tools model components for a single cell.
    
    Attributes:
        model: The CP-SAT model.
        cell_color: Cell identifier (RED, BLUE, etc.).
        shift_minutes: Available minutes in shift (440 or 500).
        horizon: Maximum time horizon for scheduling.
        table1_panels: List of PanelVariables for table 1.
        table2_panels: List of PanelVariables for table 2.
        operator_intervals: All operator intervals for NoOverlap constraint.
        total_panels_scheduled: Variable tracking total panels.
        forced_operator_idle: Variable tracking operator idle time.
        forced_table_idle: Variables tracking table idle time.
    """
    model: cp_model.CpModel
    cell_color: CellColor
    shift_minutes: int
    horizon: int
    table1_panels: list[PanelVariables] = field(default_factory=list)
    table2_panels: list[PanelVariables] = field(default_factory=list)
    operator_intervals: list[cp_model.IntervalVar] = field(default_factory=list)
    total_panels_scheduled: cp_model.IntVar | None = None
    forced_operator_idle: cp_model.IntVar | None = None
    forced_table1_idle: cp_model.IntVar | None = None
    forced_table2_idle: cp_model.IntVar | None = None


def calculate_task_times(
    job: Job,
    calc: CalculatedFields,
    constants: CycleTimeConstants,
    summer_mode: bool,
    is_first_panel: bool,
    same_fixture_as_prior: bool,
    is_on_table_today: bool,
    starts_with_pour: bool = False
) -> TaskTimes:
    """Calculate task durations for a panel.
    
    Args:
        job: Job assigned to this panel.
        calc: Calculated fields for the job.
        constants: Cycle time constants for lookups.
        summer_mode: Whether summer cure multiplier applies.
        is_first_panel: Whether this is the first panel on the table.
        same_fixture_as_prior: Whether prior panel used same fixture.
        is_on_table_today: Whether job is already set up (ON_TABLE_TODAY).
        starts_with_pour: Whether this ON_TABLE_TODAY job starts with POUR.
    
    Returns:
        TaskTimes with all durations calculated.
    """
    timing = constants.get_task_timing(job.wire_diameter, job.equivalent)
    
    # SETUP: 0 if same fixture as prior OR if ON_TABLE_TODAY first panel
    if is_on_table_today and is_first_panel:
        setup = 0
    elif same_fixture_as_prior:
        setup = 0
    else:
        setup = timing.setup
    
    # LAYOUT: 0 if ON_TABLE_TODAY and starts_with_pour (LAYOUT already done)
    if is_on_table_today and is_first_panel and starts_with_pour:
        layout = 0
    else:
        layout = timing.layout
    
    # POUR: Base time × number of molds
    pour = int(timing.pour * job.molds)
    
    # CURE: Base time × summer multiplier (1.5 if summer, 1.0 otherwise)
    cure_multiplier = 1.5 if summer_mode else 1.0
    cure = int(timing.cure * cure_multiplier)
    
    # UNLOAD: Standard from timing
    unload = timing.unload
    
    return TaskTimes(
        setup=setup,
        layout=layout,
        pour=pour,
        cure=cure,
        unload=unload
    )


def create_panel_variables(
    model: cp_model.CpModel,
    table_id: str,
    panel_index: int,
    job: Job,
    task_times: TaskTimes,
    horizon: int,
    is_optional: bool = False
) -> PanelVariables:
    """Create OR-Tools variables for a single panel.
    
    Args:
        model: CP-SAT model to add variables to.
        table_id: Table identifier.
        panel_index: Panel ordinal (0-based).
        job: Job assigned to this panel.
        task_times: Pre-calculated task durations.
        horizon: Maximum time value.
        is_optional: Whether this panel can be skipped.
    
    Returns:
        PanelVariables with all variables created.
    """
    prefix = f"{table_id}_p{panel_index}"
    
    panel = PanelVariables(
        table_id=table_id,
        panel_index=panel_index,
        job_id=job.job_id,
        task_times=task_times
    )
    
    # Create is_scheduled variable for optional panels
    if is_optional:
        panel.is_scheduled = model.NewBoolVar(f"{prefix}_scheduled")
    
    # Create variables for each task
    for task_name in TASK_SEQUENCE:
        duration = getattr(task_times, task_name.lower())
        
        # Start and end time variables
        start_var = model.NewIntVar(0, horizon, f"{prefix}_{task_name}_start")
        end_var = model.NewIntVar(0, horizon, f"{prefix}_{task_name}_end")
        
        panel.task_starts[task_name] = start_var
        panel.task_ends[task_name] = end_var
        
        # Create interval variable
        if is_optional and panel.is_scheduled is not None:
            # Optional interval - only enforced if is_scheduled is true
            interval = model.NewOptionalIntervalVar(
                start_var, duration, end_var,
                panel.is_scheduled,
                f"{prefix}_{task_name}_interval"
            )
        else:
            # Required interval
            interval = model.NewIntervalVar(
                start_var, duration, end_var,
                f"{prefix}_{task_name}_interval"
            )
        
        panel.task_intervals[task_name] = interval
        
        # Track operator intervals (all tasks except CURE)
        if task_name in OPERATOR_TASKS:
            panel.operator_intervals.append(interval)
    
    return panel


def add_task_precedence_constraints(
    model: cp_model.CpModel,
    panel: PanelVariables
) -> None:
    """Add precedence constraints: SETUP → LAYOUT → POUR → CURE → UNLOAD.
    
    Also adds maximum gap constraints to prevent unreasonable delays.
    
    Args:
        model: CP-SAT model.
        panel: Panel variables to constrain.
    """
    # Maximum allowed gap between operator tasks (minutes)
    MAX_INTER_TASK_GAP = 60
    
    for i in range(len(TASK_SEQUENCE) - 1):
        current_task = TASK_SEQUENCE[i]
        next_task = TASK_SEQUENCE[i + 1]
        
        # Next task starts when current task ends
        model.Add(
            panel.task_starts[next_task] >= panel.task_ends[current_task]
        )
        
        # CRITICAL: Prevent excessive gaps between LAYOUT and POUR
        # After LAYOUT completes, POUR should start within reasonable time
        if current_task == "LAYOUT" and next_task == "POUR":
            model.Add(
                panel.task_starts["POUR"] <= panel.task_ends["LAYOUT"] + MAX_INTER_TASK_GAP
            )


def add_panel_sequence_constraints(
    model: cp_model.CpModel,
    panels: list[PanelVariables]
) -> None:
    """Add constraints that panels run in sequence on a table.
    
    Panel N+1 cannot start until Panel N completes UNLOAD.
    
    Args:
        model: CP-SAT model.
        panels: List of panel variables in order.
    """
    for i in range(len(panels) - 1):
        current_panel = panels[i]
        next_panel = panels[i + 1]
        
        # Next panel's SETUP starts after current panel's UNLOAD ends
        model.Add(
            next_panel.task_starts["SETUP"] >= current_panel.task_ends["UNLOAD"]
        )


def add_operator_no_overlap_constraint(
    model: cp_model.CpModel,
    all_operator_intervals: list[cp_model.IntervalVar]
) -> None:
    """Add NoOverlap constraint for operator (can only be at one place at a time).
    
    Args:
        model: CP-SAT model.
        all_operator_intervals: All operator task intervals from both tables.
    """
    model.AddNoOverlap(all_operator_intervals)


def add_pour_cutoff_constraint(
    model: cp_model.CpModel,
    panel: PanelVariables,
    shift_minutes: int,
    cutoff_minutes: int = 40
) -> None:
    """Add constraint: Cannot start POUR with less than cutoff minutes remaining.
    
    Per CELL_RULES_SIMPLIFIED: POUR cannot start if <40 minutes remaining.
    
    Args:
        model: CP-SAT model.
        panel: Panel variables.
        shift_minutes: Total shift duration.
        cutoff_minutes: Minimum minutes required to start POUR (default 40).
    """
    # POUR start must be <= (shift_minutes - cutoff_minutes)
    # OR the panel is not scheduled (for optional panels)
    max_pour_start = shift_minutes - cutoff_minutes
    
    if panel.is_scheduled is not None:
        # Optional panel: constraint only applies if scheduled
        model.Add(
            panel.task_starts["POUR"] <= max_pour_start
        ).OnlyEnforceIf(panel.is_scheduled)
    else:
        # Required panel: always enforce
        model.Add(panel.task_starts["POUR"] <= max_pour_start)


def add_shift_end_constraints(
    model: cp_model.CpModel,
    panels: list[PanelVariables],
    shift_minutes: int
) -> None:
    """Add constraints that all tasks must complete within shift.
    
    Args:
        model: CP-SAT model.
        panels: All panel variables.
        shift_minutes: Total shift duration.
    """
    for panel in panels:
        for task_name in TASK_SEQUENCE:
            if panel.is_scheduled is not None:
                # Optional: only enforce if scheduled
                model.Add(
                    panel.task_ends[task_name] <= shift_minutes
                ).OnlyEnforceIf(panel.is_scheduled)
            else:
                # Required: always enforce
                model.Add(panel.task_ends[task_name] <= shift_minutes)


def add_on_table_today_constraints(
    model: cp_model.CpModel,
    panel: PanelVariables,
    start_with_pour: bool
) -> None:
    """Add constraints for ON_TABLE_TODAY panels.
    
    For jobs already set up:
    - SETUP = 0 minutes (already handled in task_times)
    - If start_with_pour: LAYOUT also = 0, POUR starts at time 0
    - Otherwise: start with LAYOUT at time 0 (SETUP already 0)
    
    Note: Task durations are set to 0 in calculate_task_times when appropriate,
    so we only need to constrain start times here.
    
    Args:
        model: CP-SAT model.
        panel: First panel variables for the ON_TABLE_TODAY job.
        start_with_pour: Whether this table starts with POUR (not LAYOUT).
    """
    if start_with_pour:
        # SETUP and LAYOUT have 0 duration, POUR starts at 0
        model.Add(panel.task_starts["SETUP"] == 0)
        model.Add(panel.task_starts["LAYOUT"] == 0)
        model.Add(panel.task_starts["POUR"] == 0)
    else:
        # SETUP has 0 duration, start with LAYOUT at 0
        model.Add(panel.task_starts["SETUP"] == 0)
        model.Add(panel.task_starts["LAYOUT"] == 0)


def create_cell_model(
    cell_color: CellColor,
    shift_minutes: int,
    table1_jobs: list[tuple[Job, CalculatedFields, TaskTimes]],
    table2_jobs: list[tuple[Job, CalculatedFields, TaskTimes]],
    table1_on_table_today: bool = False,
    table2_on_table_today: bool = False,
    table1_starts_pour: bool = False,
    table2_starts_pour: bool = False
) -> CellScheduleModel:
    """Create a complete cell scheduling model.
    
    Args:
        cell_color: Cell identifier.
        shift_minutes: Available shift minutes (440 or 500).
        table1_jobs: List of (Job, CalculatedFields, TaskTimes) for table 1.
        table2_jobs: List of (Job, CalculatedFields, TaskTimes) for table 2.
        table1_on_table_today: Whether table 1 has ON_TABLE_TODAY job.
        table2_on_table_today: Whether table 2 has ON_TABLE_TODAY job.
        table1_starts_pour: Whether table 1 starts with POUR (not LAYOUT).
        table2_starts_pour: Whether table 2 starts with POUR (not LAYOUT).
    
    Returns:
        CellScheduleModel with all variables and constraints.
    """
    model = cp_model.CpModel()
    
    # Use a reasonable horizon (shift + buffer for calculations)
    horizon = shift_minutes + 100
    
    cell_model = CellScheduleModel(
        model=model,
        cell_color=cell_color,
        shift_minutes=shift_minutes,
        horizon=horizon
    )
    
    table1_id = f"{cell_color}_1"
    table2_id = f"{cell_color}_2"
    
    # Create panel variables for table 1
    for i, (job, calc, times) in enumerate(table1_jobs):
        panel = create_panel_variables(
            model, table1_id, i, job, times, horizon,
            is_optional=(i > 0)  # First panel required, rest optional
        )
        cell_model.table1_panels.append(panel)
        cell_model.operator_intervals.extend(panel.operator_intervals)
        
        # Add task precedence within panel
        add_task_precedence_constraints(model, panel)
        
        # Add POUR cutoff constraint
        add_pour_cutoff_constraint(model, panel, shift_minutes)
    
    # Create panel variables for table 2
    for i, (job, calc, times) in enumerate(table2_jobs):
        panel = create_panel_variables(
            model, table2_id, i, job, times, horizon,
            is_optional=(i > 0)
        )
        cell_model.table2_panels.append(panel)
        cell_model.operator_intervals.extend(panel.operator_intervals)
        
        add_task_precedence_constraints(model, panel)
        add_pour_cutoff_constraint(model, panel, shift_minutes)
    
    # Add panel sequence constraints (panels run consecutively on each table)
    if cell_model.table1_panels:
        add_panel_sequence_constraints(model, cell_model.table1_panels)
    if cell_model.table2_panels:
        add_panel_sequence_constraints(model, cell_model.table2_panels)
    
    # Add operator no-overlap constraint (operator can only be one place)
    if cell_model.operator_intervals:
        add_operator_no_overlap_constraint(model, cell_model.operator_intervals)
    
    # Add shift end constraints
    all_panels = cell_model.table1_panels + cell_model.table2_panels
    add_shift_end_constraints(model, all_panels, shift_minutes)
    
    # Add ON_TABLE_TODAY constraints if applicable
    if table1_on_table_today and cell_model.table1_panels:
        add_on_table_today_constraints(
            model, cell_model.table1_panels[0], table1_starts_pour
        )
    
    if table2_on_table_today and cell_model.table2_panels:
        add_on_table_today_constraints(
            model, cell_model.table2_panels[0], table2_starts_pour
        )
    
    # Create tracking variables
    _add_tracking_variables(model, cell_model)
    
    return cell_model


def _add_tracking_variables(
    model: cp_model.CpModel,
    cell_model: CellScheduleModel
) -> None:
    """Add variables to track total panels, idle time, etc.
    
    Args:
        model: CP-SAT model.
        cell_model: Cell model to add tracking variables to.
    """
    # Count scheduled panels
    scheduled_vars = []
    for panel in cell_model.table1_panels + cell_model.table2_panels:
        if panel.is_scheduled is not None:
            scheduled_vars.append(panel.is_scheduled)
        else:
            # Required panel, always counts as 1
            scheduled_vars.append(1)
    
    cell_model.total_panels_scheduled = model.NewIntVar(
        0, len(scheduled_vars), f"{cell_model.cell_color}_total_panels"
    )
    model.Add(cell_model.total_panels_scheduled == sum(scheduled_vars))


def add_objective_maximize_panels(
    model: cp_model.CpModel,
    cell_model: CellScheduleModel,
    panel_weight: int = 10
) -> None:
    """Add objective to maximize panels scheduled.
    
    Args:
        model: CP-SAT model.
        cell_model: Cell model with tracking variables.
        panel_weight: Weight per panel in objective.
    """
    if cell_model.total_panels_scheduled is not None:
        model.Maximize(cell_model.total_panels_scheduled * panel_weight)


def add_objective_minimize_makespan(
    model: cp_model.CpModel,
    cell_model: CellScheduleModel
) -> None:
    """Add objective to minimize total schedule duration (makespan).
    
    Args:
        model: CP-SAT model.
        cell_model: Cell model with panels.
    """
    # Find the latest end time across all scheduled panels
    all_end_times = []
    for panel in cell_model.table1_panels + cell_model.table2_panels:
        all_end_times.append(panel.task_ends["UNLOAD"])
    
    if all_end_times:
        makespan = model.NewIntVar(0, cell_model.horizon, "makespan")
        model.AddMaxEquality(makespan, all_end_times)
        model.Minimize(makespan)
