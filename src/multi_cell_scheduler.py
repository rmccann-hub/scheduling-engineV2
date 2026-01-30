# Multi-cell scheduling coordinator.
# Version: 1.0.0
# Assigns jobs to cells and coordinates scheduling across all active cells.

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from .constants import CycleTimeConstants, CellColor, CELL_COLORS
from .data_loader import Job, DailyProductionLoad
from .calculated_fields import (
    CalculatedFields, 
    calculate_fields_for_job,
    PRIORITY_PAST_DUE,
    PRIORITY_TODAY,
    PRIORITY_EXPEDITE,
    PRIORITY_FUTURE
)
from .validator import OperatorInputs
from .resources import (
    ResourcePool,
    MoldAllocation,
    CellCapacity,
    create_resource_pool,
    allocate_molds_for_job,
    get_compliant_cells_for_job,
    calculate_cell_capacities,
    calculate_mold_requirement
)
from .scheduler import (
    CellScheduleResult,
    JobAssignment,
    schedule_single_cell,
    determine_start_conditions
)
from .errors import InfeasibleScheduleError


@dataclass
class JobCellAssignment:
    """Assignment of a job to a specific cell.
    
    Attributes:
        job: The job being assigned.
        calc: Calculated fields for the job.
        cell_color: Cell the job is assigned to.
        table_num: Table number (1 or 2), or None if not yet determined.
        mold_allocation: Mold allocation for this assignment.
        panels_to_schedule: Number of panels to schedule.
        is_on_table_today: Whether this is an ON_TABLE_TODAY job.
        starts_with_pour: Whether to start with POUR (not LAYOUT).
        assignment_reason: Why this cell was chosen.
    """
    job: Job
    calc: CalculatedFields
    cell_color: CellColor
    table_num: int | None = None
    mold_allocation: MoldAllocation | None = None
    panels_to_schedule: int = 0
    is_on_table_today: bool = False
    starts_with_pour: bool = False
    assignment_reason: str = ""


@dataclass
class MultiCellScheduleResult:
    """Result of scheduling across multiple cells.
    
    Attributes:
        schedule_date: Date being scheduled.
        shift_minutes: Shift duration.
        status: Overall status (OPTIMAL, FEASIBLE, PARTIAL, INFEASIBLE).
        cell_results: Dict of cell color to CellScheduleResult.
        job_assignments: List of all job assignments.
        unscheduled_jobs: Jobs that couldn't be scheduled (Job, CalculatedFields, reason).
        total_panels: Total panels scheduled across all cells.
        total_operator_minutes: Total operator minutes used.
        warnings: List of warning messages.
    """
    schedule_date: date
    shift_minutes: int
    status: str = "UNKNOWN"
    cell_results: dict[CellColor, CellScheduleResult] = field(default_factory=dict)
    job_assignments: list[JobCellAssignment] = field(default_factory=list)
    unscheduled_jobs: list[tuple] = field(default_factory=list)  # (Job, CalculatedFields|None, reason)
    total_panels: int = 0
    total_operator_minutes: int = 0
    warnings: list[str] = field(default_factory=list)
    
    @property
    def is_feasible(self) -> bool:
        """Check if at least some jobs were scheduled."""
        return self.status in ("OPTIMAL", "FEASIBLE", "PARTIAL")
    
    def get_scheduled_job_ids(self) -> set[str]:
        """Get set of job IDs that were scheduled."""
        return {a.job.job_id for a in self.job_assignments}


def schedule_all_cells(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    operator_inputs: OperatorInputs,
    timeout_per_cell: float = 30.0
) -> MultiCellScheduleResult:
    """Schedule jobs across all active cells.
    
    Main entry point for multi-cell scheduling. Steps:
    1. Calculate fields for all jobs
    2. Sort jobs by priority
    3. Handle ON_TABLE_TODAY jobs first
    4. Assign remaining jobs to cells based on priority and resource availability
    5. Schedule each cell
    6. Collect and return results
    
    Args:
        load: DailyProductionLoad with jobs.
        constants: CycleTimeConstants for lookups.
        operator_inputs: Operator configuration (active cells, shift, etc.).
        timeout_per_cell: Solver timeout per cell.
    
    Returns:
        MultiCellScheduleResult with all scheduling results.
    """
    result = MultiCellScheduleResult(
        schedule_date=operator_inputs.schedule_date,
        shift_minutes=operator_inputs.shift_minutes
    )
    
    # Early exit if no active cells
    if not operator_inputs.active_cells:
        result.status = "INFEASIBLE"
        result.warnings.append("No active cells configured")
        return result
    
    # Calculate fields for all jobs
    today = operator_inputs.schedule_date
    job_calcs = {
        job.job_id: calculate_fields_for_job(job, constants, today)
        for job in load.jobs
    }
    
    # Create resource pool
    pool = create_resource_pool(constants, operator_inputs.active_cells)
    
    # Get ON_TABLE_TODAY jobs
    jobs_on_tables = load.get_jobs_on_tables()
    
    # Calculate cell capacities
    capacities = calculate_cell_capacities(
        operator_inputs.active_cells,
        jobs_on_tables,
        constants,
        operator_inputs.shift_minutes
    )
    
    # Phase 1: Handle ON_TABLE_TODAY jobs
    on_table_assignments = _handle_on_table_today_jobs(
        jobs_on_tables, job_calcs, constants, pool, operator_inputs, result
    )
    
    # Phase 2: Sort remaining jobs by priority
    remaining_jobs = [
        job for job in load.jobs
        if job.job_id not in {a.job.job_id for a in on_table_assignments}
    ]
    
    # Sort by priority (ascending), then build_date (ascending)
    remaining_jobs.sort(
        key=lambda j: (job_calcs[j.job_id].priority, job_calcs[j.job_id].build_date)
    )
    
    # Phase 3: Assign remaining jobs to cells
    cell_assignments = _assign_jobs_to_cells(
        remaining_jobs,
        job_calcs,
        on_table_assignments,
        constants,
        pool,
        operator_inputs,
        capacities,
        result
    )
    
    # Combine all assignments
    all_assignments = on_table_assignments + cell_assignments
    result.job_assignments = all_assignments
    
    # Phase 4: Schedule each cell
    _schedule_all_active_cells(
        all_assignments,
        constants,
        operator_inputs,
        timeout_per_cell,
        result
    )
    
    # Calculate totals
    result.total_panels = sum(
        cr.total_panels for cr in result.cell_results.values()
    )
    result.total_operator_minutes = sum(
        cr.total_operator_time for cr in result.cell_results.values()
    )
    
    # Determine overall status
    if not result.cell_results:
        result.status = "INFEASIBLE"
    elif all(cr.status == "OPTIMAL" for cr in result.cell_results.values()):
        if not result.unscheduled_jobs:
            result.status = "OPTIMAL"
        else:
            result.status = "PARTIAL"
    elif any(cr.is_feasible for cr in result.cell_results.values()):
        result.status = "FEASIBLE" if not result.unscheduled_jobs else "PARTIAL"
    else:
        result.status = "INFEASIBLE"
    
    return result


def _handle_on_table_today_jobs(
    jobs_on_tables: dict[str, Job],
    job_calcs: dict[str, CalculatedFields],
    constants: CycleTimeConstants,
    pool: ResourcePool,
    operator_inputs: OperatorInputs,
    result: MultiCellScheduleResult
) -> list[JobCellAssignment]:
    """Handle jobs that are already on tables (ON_TABLE_TODAY).
    
    Args:
        jobs_on_tables: Dict of table_id to job.
        job_calcs: Dict of job_id to calculated fields.
        constants: CycleTimeConstants.
        pool: Resource pool.
        operator_inputs: Operator inputs.
        result: Result to add warnings to.
    
    Returns:
        List of JobCellAssignment for ON_TABLE_TODAY jobs.
    """
    assignments = []
    
    # Group by cell
    cell_tables: dict[CellColor, dict[int, Job]] = {}
    for table_id, job in jobs_on_tables.items():
        parts = table_id.rsplit("_", 1)
        cell_color = parts[0]
        table_num = int(parts[1])
        
        if cell_color not in cell_tables:
            cell_tables[cell_color] = {}
        cell_tables[cell_color][table_num] = job
    
    for cell_color, tables in cell_tables.items():
        # Check if cell is active
        if cell_color not in operator_inputs.active_cells:
            for table_num, job in tables.items():
                calc = job_calcs[job.job_id]
                # Per CELL_RULES: If priority <= 2 (past due, today, expedite),
                # must reschedule. Priority 3 (future) can wait.
                if calc.priority <= 2:
                    result.warnings.append(
                        f"Job {job.job_id} is on {cell_color}_{table_num} but "
                        f"cell is NOT ACTIVE. Job needs rescheduling."
                    )
                    # Don't add to assignments - will be rescheduled
                else:
                    result.warnings.append(
                        f"Job {job.job_id} is on {cell_color}_{table_num} (NOT ACTIVE) "
                        f"but priority is Future - can wait."
                    )
            continue
        
        # Determine start conditions (which table starts with POUR)
        table1_job = tables.get(1)
        table2_job = tables.get(2)
        
        t1_starts_pour, t2_starts_pour = determine_start_conditions(
            table1_job, table2_job, constants
        )
        
        # Create assignments
        for table_num, job in tables.items():
            calc = job_calcs[job.job_id]
            
            # Allocate molds
            allocation = allocate_molds_for_job(
                job, calc, cell_color, pool, constants
            )
            
            if not allocation.is_valid:
                result.warnings.append(
                    f"ON_TABLE_TODAY job {job.job_id} mold allocation failed: "
                    f"{allocation.error_message}"
                )
                continue
            
            # Reserve molds in pool
            for mold_name, count in allocation.mold_assignments.items():
                pool.reserve_molds(mold_name, count)
            
            # Reserve fixture
            pool.reserve_fixture(calc.fixture_id)
            
            starts_pour = t1_starts_pour if table_num == 1 else t2_starts_pour
            
            assignment = JobCellAssignment(
                job=job,
                calc=calc,
                cell_color=cell_color,
                table_num=table_num,
                mold_allocation=allocation,
                panels_to_schedule=calc.sched_qty,
                is_on_table_today=True,
                starts_with_pour=starts_pour,
                assignment_reason="ON_TABLE_TODAY"
            )
            assignments.append(assignment)
    
    return assignments


def _assign_jobs_to_cells(
    jobs: list[Job],
    job_calcs: dict[str, CalculatedFields],
    existing_assignments: list[JobCellAssignment],
    constants: CycleTimeConstants,
    pool: ResourcePool,
    operator_inputs: OperatorInputs,
    capacities: dict[CellColor, CellCapacity],
    result: MultiCellScheduleResult
) -> list[JobCellAssignment]:
    """Assign jobs to cells based on priority and resource availability.
    
    Assignment strategy:
    1. Get compliant cells for job (mold depth, ORANGE eligibility)
    2. Try to allocate molds on each compliant cell
    3. Choose cell with best fit (most available capacity)
    4. If no cell can accommodate, add to unscheduled
    
    Args:
        jobs: Jobs to assign (sorted by priority).
        job_calcs: Calculated fields for jobs.
        existing_assignments: Already assigned ON_TABLE_TODAY jobs.
        constants: CycleTimeConstants.
        pool: Resource pool.
        operator_inputs: Operator inputs.
        capacities: Cell capacity info.
        result: Result to add warnings/unscheduled to.
    
    Returns:
        List of new JobCellAssignment.
    """
    assignments = []
    
    # Track assignments per cell for balancing
    cell_job_counts: dict[CellColor, int] = {c: 0 for c in operator_inputs.active_cells}
    for a in existing_assignments:
        cell_job_counts[a.cell_color] = cell_job_counts.get(a.cell_color, 0) + 1
    
    for job in jobs:
        calc = job_calcs[job.job_id]
        
        # Get compliant cells
        compliant_cells = get_compliant_cells_for_job(
            job, calc, constants, operator_inputs.active_cells, operator_inputs
        )
        
        if not compliant_cells:
            reason = _get_no_cell_reason(job, calc, operator_inputs)
            result.unscheduled_jobs.append((job, calc, reason))
            continue
        
        # Try to allocate on each compliant cell
        best_assignment = None
        best_score = -1
        
        for cell_color in compliant_cells:
            # Check fixture limit
            if not pool.check_fixture_limit(job.pattern):
                continue
            
            # Try mold allocation
            allocation = allocate_molds_for_job(
                job, calc, cell_color, pool, constants
            )
            
            if not allocation.is_valid:
                continue
            
            # Score this assignment (prefer cells with fewer jobs)
            score = 100 - cell_job_counts.get(cell_color, 0)
            
            # Bonus for matching color molds (lower overhead)
            if cell_color != "ORANGE" and f"{cell_color}_MOLD" in allocation.mold_assignments:
                score += 10
            
            if score > best_score:
                best_score = score
                best_assignment = JobCellAssignment(
                    job=job,
                    calc=calc,
                    cell_color=cell_color,
                    mold_allocation=allocation,
                    panels_to_schedule=calc.sched_qty,
                    assignment_reason=f"Best fit (score={score})"
                )
        
        if best_assignment:
            # Reserve resources
            for mold_name, count in best_assignment.mold_allocation.mold_assignments.items():
                pool.reserve_molds(mold_name, count)
            pool.reserve_fixture(calc.fixture_id)
            
            assignments.append(best_assignment)
            cell_job_counts[best_assignment.cell_color] = (
                cell_job_counts.get(best_assignment.cell_color, 0) + 1
            )
        else:
            reason = "No cell has available resources (molds/fixtures)"
            result.unscheduled_jobs.append((job, calc, reason))
    
    return assignments


def _get_no_cell_reason(
    job: Job,
    calc: CalculatedFields,
    operator_inputs: OperatorInputs
) -> str:
    """Get reason why no cell is available for a job."""
    if not job.orange_eligible and "ORANGE" not in operator_inputs.active_cells:
        if calc.mold_depth == "DEEP":
            # DEEP molds not available on ORANGE anyway
            non_orange_active = operator_inputs.active_cells - {"ORANGE"}
            if not non_orange_active:
                return "Requires DEEP molds but only ORANGE cell is active"
    
    if calc.mold_depth == "DEEP":
        return "Requires DEEP molds but no compliant cell is active"
    
    if not job.orange_eligible:
        non_orange = operator_inputs.active_cells - {"ORANGE"}
        if not non_orange:
            return "Not ORANGE_ELIGIBLE and only ORANGE cell is active"
    
    return "No compliant cell available"


def _schedule_all_active_cells(
    assignments: list[JobCellAssignment],
    constants: CycleTimeConstants,
    operator_inputs: OperatorInputs,
    timeout_per_cell: float,
    result: MultiCellScheduleResult
) -> None:
    """Schedule each active cell with its assigned jobs.
    
    Args:
        assignments: All job assignments.
        constants: CycleTimeConstants.
        operator_inputs: Operator inputs.
        timeout_per_cell: Solver timeout.
        result: Result to populate with cell results.
    """
    # Group assignments by cell
    cell_assignments: dict[CellColor, list[JobCellAssignment]] = {}
    for a in assignments:
        if a.cell_color not in cell_assignments:
            cell_assignments[a.cell_color] = []
        cell_assignments[a.cell_color].append(a)
    
    # Schedule each cell
    for cell_color in operator_inputs.active_cells:
        cell_jobs = cell_assignments.get(cell_color, [])
        
        if not cell_jobs:
            # No jobs assigned to this cell
            result.cell_results[cell_color] = CellScheduleResult(
                cell_color=cell_color,
                shift_minutes=operator_inputs.shift_minutes,
                status="OPTIMAL",
                total_panels=0
            )
            continue
        
        # Separate into tables
        table1_jobs = [a for a in cell_jobs if a.table_num == 1 or a.table_num is None]
        table2_jobs = [a for a in cell_jobs if a.table_num == 2]
        
        # If jobs don't have table assignments, distribute them
        if any(a.table_num is None for a in table1_jobs):
            table1_jobs, table2_jobs = _distribute_jobs_to_tables(
                [a for a in cell_jobs if a.table_num is None],
                [a for a in cell_jobs if a.table_num == 1],
                [a for a in cell_jobs if a.table_num == 2]
            )
        
        # Convert to JobAssignment for single cell scheduler
        t1_assignments = [
            JobAssignment(
                job=a.job,
                calc=a.calc,
                panels_to_schedule=a.panels_to_schedule,
                is_on_table_today=a.is_on_table_today,
                starts_with_pour=a.starts_with_pour
            )
            for a in table1_jobs
        ]
        
        t2_assignments = [
            JobAssignment(
                job=a.job,
                calc=a.calc,
                panels_to_schedule=a.panels_to_schedule,
                is_on_table_today=a.is_on_table_today,
                starts_with_pour=a.starts_with_pour
            )
            for a in table2_jobs
        ]
        
        # Schedule the cell
        cell_result = schedule_single_cell(
            cell_color=cell_color,
            shift_minutes=operator_inputs.shift_minutes,
            table1_assignments=t1_assignments,
            table2_assignments=t2_assignments,
            constants=constants,
            summer_mode=operator_inputs.summer_mode,
            timeout_seconds=timeout_per_cell
        )
        
        result.cell_results[cell_color] = cell_result


def _distribute_jobs_to_tables(
    unassigned: list[JobCellAssignment],
    table1_fixed: list[JobCellAssignment],
    table2_fixed: list[JobCellAssignment]
) -> tuple[list[JobCellAssignment], list[JobCellAssignment]]:
    """Distribute unassigned jobs between tables for balance.
    
    Simple alternating assignment, prioritizing balance.
    
    Args:
        unassigned: Jobs without table assignment.
        table1_fixed: Jobs already assigned to table 1.
        table2_fixed: Jobs already assigned to table 2.
    
    Returns:
        Tuple of (table1_jobs, table2_jobs).
    """
    table1 = list(table1_fixed)
    table2 = list(table2_fixed)
    
    for job in unassigned:
        # Assign to table with fewer jobs
        if len(table1) <= len(table2):
            job.table_num = 1
            table1.append(job)
        else:
            job.table_num = 2
            table2.append(job)
    
    return table1, table2


def get_schedule_summary(result: MultiCellScheduleResult) -> str:
    """Generate a text summary of the multi-cell schedule.
    
    Args:
        result: MultiCellScheduleResult to summarize.
    
    Returns:
        Multi-line summary string.
    """
    lines = []
    lines.append(f"=== Multi-Cell Schedule Summary ===")
    lines.append(f"Date: {result.schedule_date}")
    lines.append(f"Shift: {result.shift_minutes} minutes")
    lines.append(f"Status: {result.status}")
    lines.append("")
    
    lines.append(f"Total panels scheduled: {result.total_panels}")
    lines.append(f"Total operator minutes: {result.total_operator_minutes}")
    lines.append("")
    
    # Cell breakdown
    lines.append("--- Cell Results ---")
    for cell_color, cell_result in sorted(result.cell_results.items()):
        lines.append(
            f"  {cell_color}: {cell_result.total_panels} panels, "
            f"status={cell_result.status}"
        )
    lines.append("")
    
    # Job assignments
    lines.append("--- Job Assignments ---")
    for assignment in result.job_assignments:
        lines.append(
            f"  {assignment.job.job_id} → {assignment.cell_color} "
            f"({assignment.panels_to_schedule} panels)"
        )
    lines.append("")
    
    # Unscheduled jobs
    if result.unscheduled_jobs:
        lines.append("--- Unscheduled Jobs ---")
        for item in result.unscheduled_jobs:
            job = item[0]
            reason = item[-1]  # Reason is always last
            lines.append(f"  {job.job_id}: {reason}")
        lines.append("")
    
    # Warnings
    if result.warnings:
        lines.append("--- Warnings ---")
        for warning in result.warnings:
            lines.append(f"  {warning}")
    
    return "\n".join(lines)
