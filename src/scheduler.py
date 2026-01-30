# Single-cell scheduling engine using OR-Tools CP-SAT solver.
# Version: 1.0.0
# Schedules two tables with one operator, handling task interleaving.

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from ortools.sat.python import cp_model

from .constants import CycleTimeConstants, CellColor
from .data_loader import Job, DailyProductionLoad
from .calculated_fields import CalculatedFields, calculate_fields_for_job
from .constraints import (
    TaskTimes,
    PanelVariables,
    CellScheduleModel,
    calculate_task_times,
    create_cell_model,
    add_objective_maximize_panels,
    TASK_SEQUENCE
)
from .errors import InfeasibleScheduleError, SolverTimeoutError


@dataclass
class ScheduledTask:
    """A scheduled task with start and end times.
    
    Attributes:
        task_name: SETUP, LAYOUT, POUR, CURE, or UNLOAD.
        start_time: Start time in minutes from shift start.
        end_time: End time in minutes from shift start.
        duration: Task duration in minutes.
        requires_operator: Whether this task needs the operator.
    """
    task_name: str
    start_time: int
    end_time: int
    duration: int
    requires_operator: bool
    
    def overlaps(self, other: "ScheduledTask") -> bool:
        """Check if this task overlaps with another in time."""
        return self.start_time < other.end_time and other.start_time < self.end_time


@dataclass
class ScheduledPanel:
    """A scheduled panel with all task times.
    
    Attributes:
        table_id: Table identifier (e.g., "RED_1").
        panel_index: Panel ordinal (0-based).
        job_id: Job assigned to this panel.
        tasks: Dictionary of task name to ScheduledTask.
        is_complete: Whether all tasks are within shift.
    """
    table_id: str
    panel_index: int
    job_id: str
    tasks: dict[str, ScheduledTask] = field(default_factory=dict)
    is_complete: bool = True
    
    @property
    def start_time(self) -> int:
        """Panel start time (SETUP start)."""
        return self.tasks["SETUP"].start_time if "SETUP" in self.tasks else 0
    
    @property
    def end_time(self) -> int:
        """Panel end time (UNLOAD end)."""
        return self.tasks["UNLOAD"].end_time if "UNLOAD" in self.tasks else 0
    
    @property
    def operator_time(self) -> int:
        """Total operator time for this panel."""
        return sum(
            t.duration for t in self.tasks.values() 
            if t.requires_operator
        )
    
    @property
    def cure_time(self) -> int:
        """CURE duration for this panel."""
        return self.tasks["CURE"].duration if "CURE" in self.tasks else 0


@dataclass
class CellScheduleResult:
    """Result of scheduling a single cell.
    
    Attributes:
        cell_color: Cell identifier.
        shift_minutes: Total shift minutes.
        status: Solver status (OPTIMAL, FEASIBLE, INFEASIBLE, etc.).
        table1_panels: Scheduled panels for table 1.
        table2_panels: Scheduled panels for table 2.
        total_panels: Total panels scheduled.
        total_operator_time: Total operator minutes used.
        forced_operator_idle: Minutes operator waited for CURE.
        forced_table_idle: Dict of table_id to idle minutes.
        solve_time_seconds: Time taken to solve.
    """
    cell_color: CellColor
    shift_minutes: int
    status: str
    table1_panels: list[ScheduledPanel] = field(default_factory=list)
    table2_panels: list[ScheduledPanel] = field(default_factory=list)
    total_panels: int = 0
    total_operator_time: int = 0
    forced_operator_idle: int = 0
    forced_table_idle: dict[str, int] = field(default_factory=dict)
    solve_time_seconds: float = 0.0
    
    @property
    def is_feasible(self) -> bool:
        """Check if a feasible solution was found."""
        return self.status in ("OPTIMAL", "FEASIBLE")
    
    def get_all_panels(self) -> list[ScheduledPanel]:
        """Get all panels from both tables, sorted by start time."""
        all_panels = self.table1_panels + self.table2_panels
        return sorted(all_panels, key=lambda p: p.start_time)


@dataclass
class JobAssignment:
    """Assignment of a job to a table for scheduling.
    
    Attributes:
        job: The job to schedule.
        calc: Calculated fields for the job.
        panels_to_schedule: Number of panels to schedule for this job.
        is_on_table_today: Whether job is ON_TABLE_TODAY.
        starts_with_pour: Whether to start with POUR (not LAYOUT).
    """
    job: Job
    calc: CalculatedFields
    panels_to_schedule: int
    is_on_table_today: bool = False
    starts_with_pour: bool = False


def schedule_single_cell(
    cell_color: CellColor,
    shift_minutes: int,
    table1_assignments: list[JobAssignment],
    table2_assignments: list[JobAssignment],
    constants: CycleTimeConstants,
    summer_mode: bool = False,
    timeout_seconds: float = 30.0
) -> CellScheduleResult:
    """Schedule a single cell with two tables and one operator.
    
    Args:
        cell_color: Cell to schedule (RED, BLUE, etc.).
        shift_minutes: Available minutes (440 standard, 500 overtime).
        table1_assignments: Job assignments for table 1.
        table2_assignments: Job assignments for table 2.
        constants: Cycle time constants.
        summer_mode: Whether summer cure multiplier applies.
        timeout_seconds: Solver time limit.
    
    Returns:
        CellScheduleResult with scheduled panels and metrics.
    
    Raises:
        SolverTimeoutError: If solver exceeds time limit without solution.
    """
    # Build task times for each panel
    table1_data = _build_table_data(
        table1_assignments, constants, summer_mode
    )
    table2_data = _build_table_data(
        table2_assignments, constants, summer_mode
    )
    
    # Determine ON_TABLE_TODAY status and start conditions
    t1_on_table = any(a.is_on_table_today for a in table1_assignments)
    t2_on_table = any(a.is_on_table_today for a in table2_assignments)
    t1_starts_pour = any(a.starts_with_pour for a in table1_assignments if a.is_on_table_today)
    t2_starts_pour = any(a.starts_with_pour for a in table2_assignments if a.is_on_table_today)
    
    # Create the constraint model
    cell_model = create_cell_model(
        cell_color=cell_color,
        shift_minutes=shift_minutes,
        table1_jobs=table1_data,
        table2_jobs=table2_data,
        table1_on_table_today=t1_on_table,
        table2_on_table_today=t2_on_table,
        table1_starts_pour=t1_starts_pour,
        table2_starts_pour=t2_starts_pour
    )
    
    # Add objective: maximize panels
    add_objective_maximize_panels(cell_model.model, cell_model)
    
    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = timeout_seconds
    
    status = solver.Solve(cell_model.model)
    status_name = solver.StatusName(status)
    
    # Build result
    result = CellScheduleResult(
        cell_color=cell_color,
        shift_minutes=shift_minutes,
        status=status_name,
        solve_time_seconds=solver.WallTime()
    )
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # Extract scheduled panels
        result.table1_panels = _extract_scheduled_panels(
            solver, cell_model.table1_panels
        )
        result.table2_panels = _extract_scheduled_panels(
            solver, cell_model.table2_panels
        )
        
        result.total_panels = len(result.table1_panels) + len(result.table2_panels)
        
        # Calculate idle times
        _calculate_idle_times(result)
        
        # Calculate total operator time
        result.total_operator_time = sum(
            p.operator_time for p in result.get_all_panels()
        )
    
    return result


def _build_table_data(
    assignments: list[JobAssignment],
    constants: CycleTimeConstants,
    summer_mode: bool
) -> list[tuple[Job, CalculatedFields, TaskTimes]]:
    """Build table data with task times for each panel.
    
    Args:
        assignments: Job assignments for the table.
        constants: Cycle time constants.
        summer_mode: Whether summer mode is active.
    
    Returns:
        List of (Job, CalculatedFields, TaskTimes) for each panel.
    """
    result = []
    prior_fixture = None
    
    for assignment in assignments:
        for panel_idx in range(assignment.panels_to_schedule):
            is_first_panel = (panel_idx == 0 and len(result) == 0)
            is_first_of_job = (panel_idx == 0)
            same_fixture = (assignment.job.fixture_id == prior_fixture)
            
            # ON_TABLE_TODAY only applies to first panel of first job
            is_on_table = assignment.is_on_table_today and is_first_of_job and is_first_panel
            starts_pour = assignment.starts_with_pour and is_first_of_job and is_first_panel
            
            times = calculate_task_times(
                job=assignment.job,
                calc=assignment.calc,
                constants=constants,
                summer_mode=summer_mode,
                is_first_panel=is_first_panel,
                same_fixture_as_prior=same_fixture and not is_first_panel,
                is_on_table_today=is_on_table,
                starts_with_pour=starts_pour
            )
            
            result.append((assignment.job, assignment.calc, times))
            prior_fixture = assignment.job.fixture_id
    
    return result


def _extract_scheduled_panels(
    solver: cp_model.CpSolver,
    panel_vars: list[PanelVariables]
) -> list[ScheduledPanel]:
    """Extract scheduled panels from solver solution.
    
    Args:
        solver: Solved CP-SAT solver.
        panel_vars: Panel variables to extract.
    
    Returns:
        List of ScheduledPanel with actual times.
    """
    result = []
    
    for panel_var in panel_vars:
        # Check if panel is scheduled (for optional panels)
        if panel_var.is_scheduled is not None:
            if not solver.BooleanValue(panel_var.is_scheduled):
                continue  # Panel not scheduled
        
        panel = ScheduledPanel(
            table_id=panel_var.table_id,
            panel_index=panel_var.panel_index,
            job_id=panel_var.job_id
        )
        
        # Extract task times
        for task_name in TASK_SEQUENCE:
            start = solver.Value(panel_var.task_starts[task_name])
            end = solver.Value(panel_var.task_ends[task_name])
            duration = getattr(panel_var.task_times, task_name.lower())
            
            panel.tasks[task_name] = ScheduledTask(
                task_name=task_name,
                start_time=start,
                end_time=end,
                duration=duration,
                requires_operator=(task_name != "CURE")
            )
        
        result.append(panel)
    
    return result


def _calculate_idle_times(result: CellScheduleResult) -> None:
    """Calculate FORCED_OPERATOR_IDLE and FORCED_TABLE_IDLE.
    
    Per CELL_RULES_SIMPLIFIED:
    - FORCED_TABLE_IDLE: Table waits for operator after CURE completes
    - FORCED_OPERATOR_IDLE: Operator waits for CURE to complete
    
    Args:
        result: CellScheduleResult to update with idle times.
    """
    table1_id = f"{result.cell_color}_1"
    table2_id = f"{result.cell_color}_2"
    
    result.forced_table_idle = {table1_id: 0, table2_id: 0}
    result.forced_operator_idle = 0
    
    # Get all panels sorted by their CURE end time
    all_panels = result.get_all_panels()
    
    for panel in all_panels:
        cure_end = panel.tasks["CURE"].end_time
        unload_start = panel.tasks["UNLOAD"].start_time
        
        # Gap between CURE end and UNLOAD start is table idle time
        # (table waiting for operator to return)
        gap = unload_start - cure_end
        if gap > 0:
            result.forced_table_idle[panel.table_id] += gap
    
    # FORCED_OPERATOR_IDLE is when operator has no work but is waiting
    # This happens when operator finishes on one table but CURE isn't done on the other
    # Calculate by looking at gaps in operator activity
    
    # Collect all operator task intervals
    operator_intervals = []
    for panel in all_panels:
        for task_name in ("SETUP", "LAYOUT", "POUR", "UNLOAD"):
            task = panel.tasks.get(task_name)
            if task and task.duration > 0:
                operator_intervals.append((task.start_time, task.end_time))
    
    # Sort by start time
    operator_intervals.sort()
    
    # Find gaps where operator is idle
    if operator_intervals:
        total_idle = 0
        prev_end = 0
        
        for start, end in operator_intervals:
            if start > prev_end:
                total_idle += (start - prev_end)
            prev_end = max(prev_end, end)
        
        result.forced_operator_idle = total_idle


def determine_start_conditions(
    table1_job: Job | None,
    table2_job: Job | None,
    constants: CycleTimeConstants
) -> tuple[bool, bool]:
    """Determine which table starts with POUR vs LAYOUT for ON_TABLE_TODAY.
    
    Per CELL_RULES_SIMPLIFIED:
    - If both tables have ON_TABLE_TODAY jobs:
      - Job with lowest EQUIVALENT starts with POUR
      - If tied, job with largest CURE starts with POUR
      - If still tied, job with largest SCHED_QTY starts with POUR
    - If only one table has ON_TABLE_TODAY:
      - That table starts with POUR
    
    Args:
        table1_job: Job on table 1 (or None).
        table2_job: Job on table 2 (or None).
        constants: Cycle time constants for CURE lookup.
    
    Returns:
        Tuple of (table1_starts_pour, table2_starts_pour).
    """
    if table1_job is None and table2_job is None:
        return (False, False)
    
    if table1_job is None:
        return (False, True)
    
    if table2_job is None:
        return (True, False)
    
    # Both have jobs - compare
    timing1 = constants.get_task_timing(table1_job.wire_diameter, table1_job.equivalent)
    timing2 = constants.get_task_timing(table2_job.wire_diameter, table2_job.equivalent)
    
    # Lower equivalent wins (starts with POUR)
    if table1_job.equivalent < table2_job.equivalent:
        return (True, False)
    elif table2_job.equivalent < table1_job.equivalent:
        return (False, True)
    
    # Tied - compare CURE (larger wins)
    if timing1.cure > timing2.cure:
        return (True, False)
    elif timing2.cure > timing1.cure:
        return (False, True)
    
    # Still tied - compare SCHED_QTY (larger wins)
    qty1 = table1_job.job_quantity_remaining or table1_job.prod_qty
    qty2 = table2_job.job_quantity_remaining or table2_job.prod_qty
    
    if qty1 >= qty2:
        return (True, False)
    else:
        return (False, True)


def create_simple_two_job_schedule(
    cell_color: CellColor,
    job1: Job,
    calc1: CalculatedFields,
    job2: Job,
    calc2: CalculatedFields,
    constants: CycleTimeConstants,
    shift_minutes: int = 440,
    summer_mode: bool = False
) -> CellScheduleResult:
    """Create a simple schedule with one job per table.
    
    Convenience function for basic scheduling scenarios.
    
    Args:
        cell_color: Cell to schedule.
        job1: Job for table 1.
        calc1: Calculated fields for job 1.
        job2: Job for table 2.
        calc2: Calculated fields for job 2.
        constants: Cycle time constants.
        shift_minutes: Shift duration.
        summer_mode: Summer mode flag.
    
    Returns:
        CellScheduleResult with the schedule.
    """
    assignment1 = JobAssignment(
        job=job1,
        calc=calc1,
        panels_to_schedule=calc1.sched_qty
    )
    
    assignment2 = JobAssignment(
        job=job2,
        calc=calc2,
        panels_to_schedule=calc2.sched_qty
    )
    
    return schedule_single_cell(
        cell_color=cell_color,
        shift_minutes=shift_minutes,
        table1_assignments=[assignment1],
        table2_assignments=[assignment2],
        constants=constants,
        summer_mode=summer_mode
    )
