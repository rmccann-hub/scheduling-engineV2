# Method Variants for Cell Scheduling.
# Version: 1.0.0
# Implements 4 scheduling methods × 2 variants (job-first, table-first).

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Callable
from enum import Enum

from .constants import CycleTimeConstants, CellColor, CELL_COLORS
from .data_loader import Job, DailyProductionLoad
from .calculated_fields import (
    CalculatedFields,
    calculate_fields_for_job,
    SCHED_CLASS_A, SCHED_CLASS_B, SCHED_CLASS_C, SCHED_CLASS_D, SCHED_CLASS_E
)
from .validator import OperatorInputs
from .resources import (
    ResourcePool,
    create_resource_pool,
    allocate_molds_for_job,
    get_compliant_cells_for_job
)
from .multi_cell_scheduler import (
    MultiCellScheduleResult,
    JobCellAssignment,
    schedule_all_cells,
    get_schedule_summary
)
from .cell_scheduler import schedule_cell, JobAssignment, CellScheduleResult


class SchedulingMethod(Enum):
    """The four scheduling methods."""
    PRIORITY_FIRST = 1
    MINIMUM_FORCED_IDLE = 2
    MAXIMUM_OUTPUT = 3
    MOST_RESTRICTED_MIX = 4


class SchedulingVariant(Enum):
    """The three scheduling variants."""
    JOB_FIRST = 1
    TABLE_FIRST = 2
    FIXTURE_FIRST = 3  # Optimize for fixture reuse to minimize SETUP time


# Weekday-based table ordering (0=Monday, 4=Friday)
WEEKDAY_TABLE_ORDER: dict[int, list[CellColor]] = {
    0: ["BLUE", "GREEN", "RED", "BLACK", "PURPLE", "ORANGE"],  # Monday
    1: ["GREEN", "RED", "BLACK", "PURPLE", "BLUE", "ORANGE"],  # Tuesday
    2: ["RED", "BLACK", "PURPLE", "BLUE", "GREEN", "ORANGE"],  # Wednesday
    3: ["BLACK", "PURPLE", "BLUE", "GREEN", "RED", "ORANGE"],  # Thursday
    4: ["PURPLE", "BLUE", "GREEN", "RED", "BLACK", "ORANGE"],  # Friday
}


@dataclass
class TableState:
    """State of a table during scheduling.
    
    Attributes:
        cell_color: Cell this table belongs to.
        table_num: Table number (1 or 2).
        when_available: Minutes into shift when next SETUP can start.
        remaining_capacity: Minutes remaining in shift.
        assigned_jobs: Jobs assigned to this table.
        current_sched_class: SCHED_CLASS of most recent job (for pairing rules).
        panels_assigned: Total panels assigned.
        last_fixture: Fixture ID of most recent job (for SETUP skip).
        current_mold_allocation: Molds currently in use on this table.
    """
    cell_color: CellColor
    table_num: int
    when_available: int = 0
    remaining_capacity: int = 440
    assigned_jobs: list[tuple[Job, CalculatedFields, int]] = field(default_factory=list)
    current_sched_class: str | None = None
    panels_assigned: int = 0
    last_fixture: str | None = None
    current_mold_allocation: dict[str, int] = field(default_factory=dict)
    
    @property
    def table_id(self) -> str:
        return f"{self.cell_color}_{self.table_num}"
    
    def can_fit_job(self, rough_time: int) -> bool:
        """Check if job fits in remaining capacity."""
        return rough_time <= self.remaining_capacity
    
    def assign_job(self, job: Job, calc: CalculatedFields, panels: int, rough_time: int) -> None:
        """Assign a job to this table."""
        self.assigned_jobs.append((job, calc, panels))
        self.when_available += rough_time
        self.remaining_capacity -= rough_time
        self.current_sched_class = calc.sched_class
        self.panels_assigned += panels
        self.last_fixture = calc.fixture_id
    
    def set_mold_allocation(self, allocation: dict[str, int]) -> None:
        """Set current mold allocation for this table."""
        self.current_mold_allocation = allocation.copy()
    
    def get_mold_allocation(self) -> dict[str, int]:
        """Get current mold allocation."""
        return self.current_mold_allocation.copy()


@dataclass
class CellState:
    """State of a cell during scheduling.
    
    Attributes:
        cell_color: Cell identifier.
        is_active: Whether cell is active.
        table1: State of table 1.
        table2: State of table 2.
    """
    cell_color: CellColor
    is_active: bool
    table1: TableState
    table2: TableState
    
    @property
    def total_remaining_capacity(self) -> int:
        return self.table1.remaining_capacity + self.table2.remaining_capacity
    
    def get_opposite_table(self, table_num: int) -> TableState:
        """Get the opposite table."""
        return self.table2 if table_num == 1 else self.table1
    
    def has_concurrent_conflict(self, sched_class: str, table_num: int) -> bool:
        """Check if assigning this class would create a conflict.
        
        Conflicts:
        - C opposite C
        - D opposite D/E
        - E opposite D/E
        """
        opposite = self.get_opposite_table(table_num)
        opp_class = opposite.current_sched_class
        
        if opp_class is None:
            return False
        
        # C-C conflict
        if sched_class == SCHED_CLASS_C and opp_class == SCHED_CLASS_C:
            return True
        
        # D/E opposite D/E conflict
        de_classes = {SCHED_CLASS_D, SCHED_CLASS_E}
        if sched_class in de_classes and opp_class in de_classes:
            return True
        
        return False


@dataclass
class SchedulingState:
    """Overall scheduling state.
    
    Attributes:
        schedule_date: Date being scheduled.
        shift_minutes: Shift duration.
        cells: Dict of cell color to CellState.
        unscheduled_jobs: Jobs not yet scheduled.
        scheduled_jobs: Jobs that have been scheduled.
        pool: Resource pool for molds/fixtures.
    """
    schedule_date: date
    shift_minutes: int
    cells: dict[CellColor, CellState] = field(default_factory=dict)
    unscheduled_jobs: list[tuple[Job, CalculatedFields]] = field(default_factory=list)
    scheduled_jobs: list[tuple[Job, CalculatedFields, CellColor, int, int]] = field(default_factory=list)
    pool: ResourcePool = None


def get_table_order(schedule_date: date, active_cells: set[CellColor]) -> list[CellColor]:
    """Get table ordering for the day.
    
    Args:
        schedule_date: Date being scheduled.
        active_cells: Set of active cells.
    
    Returns:
        List of cell colors in order for the day.
    """
    weekday = schedule_date.weekday()
    if weekday > 4:  # Weekend - use Friday order
        weekday = 4
    
    base_order = WEEKDAY_TABLE_ORDER[weekday]
    return [c for c in base_order if c in active_cells]


def estimate_rough_time(
    job: Job,
    calc: CalculatedFields,
    constants: CycleTimeConstants,
    panels: int,
    needs_setup: bool,
    summer_mode: bool
) -> int:
    """Estimate rough time for a job's panels on ONE TABLE.
    
    This accounts for alternation with another table - during CURE on this table,
    the operator works on the other table, so effective cycle time depends on
    the balance between operator work and CURE time.
    
    Args:
        job: Job to estimate.
        calc: Calculated fields.
        constants: Cycle time constants.
        panels: Number of panels on THIS table.
        needs_setup: Whether SETUP is needed.
        summer_mode: Whether summer mode is active.
    
    Returns:
        Estimated minutes for the job on one table.
    """
    timing = constants.get_task_timing(job.wire_diameter, job.equivalent)
    
    setup = timing.setup if needs_setup else 0
    layout = timing.layout
    pour = int(timing.pour * job.molds)
    cure_mult = 1.5 if summer_mode else 1.0
    cure = int(timing.cure * cure_mult)
    unload = timing.unload
    
    # Operator work per panel (excluding setup after first)
    operator_work_first = setup + layout + pour  # + unload happens after cure
    operator_work_subsequent = layout + pour
    
    # With 2-table alternation:
    # - Work T1 (operator_work), then switch to T2
    # - During T2's operator_work, T1 is curing
    # - Return to T1: if cure done, do unload, then next panel
    # 
    # Effective cycle per panel = max(operator_work, cure) + unload
    # Because while we work T2, T1 cures in parallel
    
    effective_cycle_first = max(operator_work_first, cure) + unload
    effective_cycle_subsequent = max(operator_work_subsequent, cure) + unload
    
    # For single-table operation (no alternation), use sequential time
    # This is a conservative estimate; actual time with alternation is less
    if panels == 1:
        return effective_cycle_first
    else:
        # First panel + subsequent panels
        # Add some buffer for transition overhead between tables
        transition_overhead = 5  # minutes per panel for switching context
        return effective_cycle_first + (panels - 1) * (effective_cycle_subsequent + transition_overhead)


def calculate_max_panels_that_fit(
    job: Job,
    calc: CalculatedFields,
    constants: CycleTimeConstants,
    available_minutes: int,
    needs_setup: bool,
    summer_mode: bool
) -> int:
    """Calculate maximum panels that fit in available time on ONE TABLE.
    
    Uses a single-table model where effective cycle time is limited by
    the slower of operator work or cure time (operator can work on other
    table during cure).
    
    Args:
        job: Job to fit.
        calc: Calculated fields.
        constants: Cycle time constants.
        available_minutes: Minutes available on the table.
        needs_setup: Whether SETUP is needed.
        summer_mode: Whether summer mode is active.
    
    Returns:
        Maximum number of panels that fit (0 if none fit).
    """
    if available_minutes <= 0:
        return 0
    
    timing = constants.get_task_timing(job.wire_diameter, job.equivalent)
    
    setup = timing.setup if needs_setup else 0
    layout = timing.layout
    pour = int(timing.pour * job.molds)
    cure_mult = 1.5 if summer_mode else 1.0
    cure = int(timing.cure * cure_mult)
    unload = timing.unload
    
    # Operator work per panel
    operator_work_first = setup + layout + pour
    operator_work_subsequent = layout + pour
    
    # Effective cycle: during cure, operator can work on other table
    # So cycle = max(operator_work, cure) + unload + transition_overhead
    effective_cycle_first = max(operator_work_first, cure) + unload
    effective_cycle_subsequent = max(operator_work_subsequent, cure) + unload
    transition_overhead = 5
    
    # Check if even 1 panel fits
    if effective_cycle_first > available_minutes:
        return 0
    
    # Calculate how many subsequent panels fit after the first
    remaining_after_first = available_minutes - effective_cycle_first
    cycle_with_overhead = effective_cycle_subsequent + transition_overhead
    additional_panels = remaining_after_first // cycle_with_overhead if cycle_with_overhead > 0 else 0
    
    return 1 + additional_panels
    return 1 + additional_panels


def initialize_state(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> SchedulingState:
    """Initialize scheduling state from inputs.
    
    Args:
        load: Daily production load.
        constants: Cycle time constants.
        inputs: Operator inputs.
    
    Returns:
        Initialized SchedulingState.
    """
    state = SchedulingState(
        schedule_date=inputs.schedule_date,
        shift_minutes=inputs.shift_minutes,
        pool=create_resource_pool(constants, inputs.active_cells)
    )
    
    # Initialize cells
    for cell_color in CELL_COLORS:
        is_active = cell_color in inputs.active_cells
        state.cells[cell_color] = CellState(
            cell_color=cell_color,
            is_active=is_active,
            table1=TableState(cell_color, 1, remaining_capacity=inputs.shift_minutes),
            table2=TableState(cell_color, 2, remaining_capacity=inputs.shift_minutes)
        )
    
    # Calculate fields and add to unscheduled
    jobs_on_tables = load.get_jobs_on_tables()
    
    for job in load.jobs:
        calc = calculate_fields_for_job(job, constants, inputs.schedule_date)
        
        # Handle ON_TABLE_TODAY jobs
        if job.on_table_today:
            parts = job.on_table_today.rsplit("_", 1)
            cell_color = parts[0]
            table_num = int(parts[1])
            
            cell_state = state.cells.get(cell_color)
            if cell_state and cell_state.is_active:
                table = cell_state.table1 if table_num == 1 else cell_state.table2
                rough_time = estimate_rough_time(
                    job, calc, constants, calc.sched_qty, 
                    needs_setup=False, summer_mode=inputs.summer_mode
                )
                table.assign_job(job, calc, calc.sched_qty, rough_time)
                state.scheduled_jobs.append((job, calc, cell_color, table_num, calc.sched_qty))
            else:
                # Cell not active, need to reschedule
                state.unscheduled_jobs.append((job, calc))
        else:
            state.unscheduled_jobs.append((job, calc))
    
    return state


# =============================================================================
# METHOD 1: PRIORITY FIRST
# =============================================================================

def method1_priority_first_job_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 1, Variant 1: Priority First - Job First.
    
    CRITICAL RULES:
    - All Priority 0 jobs must be scheduled before any higher priority
    - Once all 0 are scheduled, priority 1 must be scheduled before higher
    
    GENERAL RULES:
    - Both tables should not have SCHED_CLASS C concurrently
    - Both tables should not have (D OR E) concurrently
    
    Variant: Select job first, then find best table.
    """
    state = initialize_state(load, constants, inputs)
    
    # Sort jobs by priority (ascending), then build_date
    state.unscheduled_jobs.sort(key=lambda x: (x[1].priority, x[1].build_date))
    
    # Get table order for the day
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    # Schedule jobs in priority order
    still_unscheduled = []
    
    # Track remaining panels for each job (for splitting across tables)
    remaining_panels = {job.job_id: calc.sched_qty for job, calc in state.unscheduled_jobs}
    job_lookup = {job.job_id: (job, calc) for job, calc in state.unscheduled_jobs}
    
    # Group jobs by priority (CRITICAL RULE: P0 must complete before P1, P1 before P2, etc.)
    priority_groups = {}
    for job, calc in state.unscheduled_jobs:
        p = calc.priority
        if p not in priority_groups:
            priority_groups[p] = []
        priority_groups[p].append(job.job_id)
    
    # Process each priority level completely before moving to next
    for priority in sorted(priority_groups.keys()):
        job_ids_in_priority = priority_groups[priority]
        
        # Keep scheduling jobs in this priority until no more progress
        made_progress = True
        while made_progress:
            made_progress = False
            
            for job_id in job_ids_in_priority:
                if remaining_panels[job_id] <= 0:
                    continue
                
                job, calc = job_lookup[job_id]
                panels_needed = remaining_panels[job_id]
                
                best_table = None
                best_score = -1
                best_panels = 0
                
                # Find best table for this job (or partial panels)
                compliant_cells = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
                
                for cell_color in table_order:
                    if cell_color not in compliant_cells:
                        continue
                    
                    cell_state = state.cells[cell_color]
                    
                    for table_num in [1, 2]:
                        table = cell_state.table1 if table_num == 1 else cell_state.table2
                        
                        # Calculate how many panels can fit
                        available_time = inputs.shift_minutes - table.when_available
                        
                        # Check if fixture is already on this table (no setup needed)
                        needs_setup = table.last_fixture != calc.fixture_id
                        
                        max_panels = calculate_max_panels_that_fit(
                            job, calc, constants, available_time,
                            needs_setup=needs_setup, summer_mode=inputs.summer_mode
                        )
                        
                        if max_panels <= 0:
                            continue
                        
                        # Limit to what we need
                        panels_to_assign = min(max_panels, panels_needed)
                        
                        # Check mold allocation
                        allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
                        if not allocation.is_valid:
                            continue
                        
                        # Check GENERAL RULES (concurrent class conflicts)
                        has_conflict = cell_state.has_concurrent_conflict(calc.sched_class, table_num)
                        
                        # Score: prefer no conflict, prefer more panels, prefer earlier availability
                        score = 1000 if not has_conflict else 0
                        score += panels_to_assign * 100  # Prefer assigning more panels
                        score += (inputs.shift_minutes - table.when_available)
                        
                        if score > best_score:
                            best_score = score
                            best_table = (cell_color, table_num, table, allocation, panels_to_assign, needs_setup)
                            best_panels = panels_to_assign
                
                if best_table:
                    cell_color, table_num, table, allocation, panels_to_assign, needs_setup = best_table
                    
                    # Release previous molds from this table (molds become available when job finishes)
                    prev_molds = table.get_mold_allocation()
                    for mold_name, count in prev_molds.items():
                        state.pool.release_molds(mold_name, count)
                    
                    # Reserve new molds
                    for mold_name, count in allocation.mold_assignments.items():
                        state.pool.reserve_molds(mold_name, count)
                    
                    # Track molds on this table
                    table.set_mold_allocation(allocation.mold_assignments)
                    
                    state.pool.reserve_fixture(calc.fixture_id)
                    
                    # Calculate rough time for assigned panels
                    rough_time = estimate_rough_time(
                        job, calc, constants, panels_to_assign,
                        needs_setup=needs_setup, summer_mode=inputs.summer_mode
                    )
                    
                    # Assign to table
                    table.assign_job(job, calc, panels_to_assign, rough_time)
                    state.scheduled_jobs.append((job, calc, cell_color, table_num, panels_to_assign))
                    
                    # Update remaining panels
                    remaining_panels[job_id] -= panels_to_assign
                    made_progress = True
    
    # Add jobs with remaining panels to unscheduled
    for job_id, panels_left in remaining_panels.items():
        if panels_left > 0:
            job, calc = job_lookup[job_id]
            still_unscheduled.append((job, calc))
    
    # Convert state to MultiCellScheduleResult
    return _state_to_result(state, still_unscheduled, constants, inputs)


def method1_priority_first_table_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 1, Variant 2: Priority First - Table First.
    
    Variant: Select table first (by weekday order), then find best job.
    """
    state = initialize_state(load, constants, inputs)
    
    # Sort jobs by priority for selection
    state.unscheduled_jobs.sort(key=lambda x: (x[1].priority, x[1].build_date))
    
    # Get table order for the day
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    # Continue until no more assignments possible
    changed = True
    while changed:
        changed = False
        
        for cell_color in table_order:
            cell_state = state.cells[cell_color]
            if not cell_state.is_active:
                continue
            
            for table_num in [1, 2]:
                table = cell_state.table1 if table_num == 1 else cell_state.table2
                
                # Find best job for this table
                best_job_idx = None
                best_score = -1
                best_allocation = None
                best_rough_time = 0
                
                for idx, (job, calc) in enumerate(state.unscheduled_jobs):
                    # Check cell compliance
                    compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
                    if cell_color not in compliant:
                        continue
                    
                    # Check fit
                    rough_time = estimate_rough_time(
                        job, calc, constants, calc.sched_qty,
                        needs_setup=True, summer_mode=inputs.summer_mode
                    )
                    if not table.can_fit_job(rough_time):
                        continue
                    
                    # Check molds
                    allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
                    if not allocation.is_valid:
                        continue
                    
                    # Check conflicts (general rule)
                    has_conflict = cell_state.has_concurrent_conflict(calc.sched_class, table_num)
                    
                    # Score: lowest priority wins, then no conflict, then earliest build_date
                    score = (10 - calc.priority) * 1000
                    score += 500 if not has_conflict else 0
                    score += (100 - calc.build_date.toordinal() % 100)
                    
                    if score > best_score:
                        best_score = score
                        best_job_idx = idx
                        best_allocation = allocation
                        best_rough_time = rough_time
                
                if best_job_idx is not None:
                    job, calc = state.unscheduled_jobs.pop(best_job_idx)
                    
                    # Reserve resources
                    for mold_name, count in best_allocation.mold_assignments.items():
                        state.pool.reserve_molds(mold_name, count)
                    state.pool.reserve_fixture(calc.fixture_id)
                    
                    # Assign
                    table.assign_job(job, calc, calc.sched_qty, best_rough_time)
                    state.scheduled_jobs.append((job, calc, cell_color, table_num, calc.sched_qty))
                    changed = True
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)


def method1_priority_first_fixture_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 1, Variant 3: Priority First - Fixture First.
    
    Optimizes for fixture reuse to minimize SETUP time:
    - Groups jobs by fixture_id
    - Tries to schedule all jobs of the same fixture on the same table
    - When table fills, moves to next available table
    - Saves 10 min SETUP for each additional job using same fixture
    
    Priority order within fixture groups:
    1. Priority 0 jobs first
    2. Then by REQ_BY date (earliest first)
    """
    state = initialize_state(load, constants, inputs)
    
    # Group jobs by fixture
    fixture_groups: dict[str, list[tuple[Job, CalculatedFields]]] = {}
    for job, calc in state.unscheduled_jobs:
        fixture = calc.fixture_id
        if fixture not in fixture_groups:
            fixture_groups[fixture] = []
        fixture_groups[fixture].append((job, calc))
    
    # Sort jobs within each fixture group by priority and REQ_BY
    for fixture in fixture_groups:
        fixture_groups[fixture].sort(key=lambda x: (x[1].priority, x[0].req_by))
    
    # Sort fixture groups: prioritize groups with Priority 0 jobs, then by earliest REQ_BY
    def fixture_priority(fixture: str) -> tuple:
        jobs = fixture_groups[fixture]
        has_priority_0 = any(calc.priority == 0 for job, calc in jobs)
        earliest_req_by = min(job.req_by for job, calc in jobs)
        total_panels = sum(calc.sched_qty for job, calc in jobs)
        return (0 if has_priority_0 else 1, earliest_req_by, -total_panels)
    
    sorted_fixtures = sorted(fixture_groups.keys(), key=fixture_priority)
    
    # Clear unscheduled (we'll rebuild from fixture groups)
    state.unscheduled_jobs.clear()
    
    # Track remaining panels per job
    remaining_panels: dict[str, int] = {}
    job_lookup: dict[str, tuple[Job, CalculatedFields]] = {}
    
    for fixture in sorted_fixtures:
        for job, calc in fixture_groups[fixture]:
            remaining_panels[job.job_id] = calc.sched_qty
            job_lookup[job.job_id] = (job, calc)
    
    # Get table order for this day
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    def find_best_table_for_job(job: Job, calc: CalculatedFields, prefer_fixture: str | None = None):
        """Find best table for a job, optionally preferring a specific fixture."""
        compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
        
        best_table = None
        best_cell = None
        best_table_num = None
        best_score = -1
        
        for cell_color in table_order:
            if cell_color not in compliant:
                continue
            
            cell_state = state.cells[cell_color]
            
            for table_num in [1, 2]:
                table = cell_state.table1 if table_num == 1 else cell_state.table2
                
                available_time = inputs.shift_minutes - table.when_available
                if available_time < constants.pour_cutoff_minutes:
                    continue
                
                needs_setup = table.last_fixture != calc.fixture_id
                max_panels = calculate_max_panels_that_fit(
                    job, calc, constants, available_time,
                    needs_setup=needs_setup, summer_mode=inputs.summer_mode
                )
                
                if max_panels <= 0:
                    continue
                
                # Check mold availability
                allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
                if not allocation.is_valid:
                    continue
                
                # Score: prefer same fixture (saves SETUP), then more available time
                score = 0
                if prefer_fixture and table.last_fixture == prefer_fixture:
                    score = 1000  # Same fixture - no SETUP needed
                elif table.last_fixture is None:
                    score = 500  # Empty table
                else:
                    score = 100  # Different fixture
                
                score += available_time + max_panels * 10
                
                if score > best_score:
                    best_score = score
                    best_table = table
                    best_cell = cell_color
                    best_table_num = table_num
        
        return best_table, best_cell, best_table_num
    
    # Process each fixture group
    for fixture in sorted_fixtures:
        jobs_in_group = fixture_groups[fixture]
        
        for job, calc in jobs_in_group:
            panels_needed = remaining_panels[job.job_id]
            if panels_needed <= 0:
                continue
            
            # Keep trying to schedule until all panels done or no more capacity
            while panels_needed > 0:
                # Find best table, preferring same fixture
                best_table, best_cell, best_table_num = find_best_table_for_job(job, calc, fixture)
                
                if best_table is None:
                    break  # No more capacity
                
                available_time = inputs.shift_minutes - best_table.when_available
                needs_setup = best_table.last_fixture != calc.fixture_id
                
                max_panels = calculate_max_panels_that_fit(
                    job, calc, constants, available_time,
                    needs_setup=needs_setup, summer_mode=inputs.summer_mode
                )
                
                if max_panels <= 0:
                    break
                
                allocation = allocate_molds_for_job(job, calc, best_cell, state.pool, constants)
                if not allocation.is_valid:
                    break
                
                panels_to_assign = min(max_panels, panels_needed)
                rough_time = estimate_rough_time(
                    job, calc, constants, panels_to_assign,
                    needs_setup=needs_setup, summer_mode=inputs.summer_mode
                )
                
                # Reserve resources
                for mold_name, count in allocation.mold_assignments.items():
                    state.pool.reserve_molds(mold_name, count)
                state.pool.reserve_fixture(calc.fixture_id)
                
                # Assign
                best_table.assign_job(job, calc, panels_to_assign, rough_time)
                state.scheduled_jobs.append((job, calc, best_cell, best_table_num, panels_to_assign))
                
                panels_needed -= panels_to_assign
                remaining_panels[job.job_id] = panels_needed
            
            # If still have remaining panels, add to unscheduled
            if remaining_panels[job.job_id] > 0:
                state.unscheduled_jobs.append((job, calc))
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)


# =============================================================================
# METHOD 2: MINIMUM FORCED IDLE
# =============================================================================

def method2_min_idle_job_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 2, Variant 1: Minimum Forced Idle - Job First.
    
    CRITICAL RULES:
    - Both tables should not have SCHED_CLASS C concurrently
    - Both tables should not have (D OR E) concurrently
    
    GENERAL RULES:
    - Assign Priority 0 and 1 before Priority 2
    - Priority 2 jobs by highest BUILD_LOAD to earliest WHEN_AVAILABLE
    
    PREFERENCES:
    - Fit job in REMAINING_CAPACITY preserving most capacity
    """
    state = initialize_state(load, constants, inputs)
    
    # Separate by priority
    priority_01 = [(j, c) for j, c in state.unscheduled_jobs if c.priority <= 1]
    priority_2_plus = [(j, c) for j, c in state.unscheduled_jobs if c.priority > 1]
    
    # Sort priority 0-1 by priority, build_date
    priority_01.sort(key=lambda x: (x[1].priority, x[1].build_date))
    
    # Sort priority 2+ by BUILD_LOAD descending
    priority_2_plus.sort(key=lambda x: -x[1].build_load)
    
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    still_unscheduled = []
    
    # Schedule priority 0-1 first
    for job, calc in priority_01:
        best = _find_best_table_min_idle(job, calc, state, constants, inputs, table_order)
        if best:
            _assign_to_table(job, calc, best, state)
        else:
            still_unscheduled.append((job, calc))
    
    # Then priority 2+
    for job, calc in priority_2_plus:
        best = _find_best_table_min_idle(job, calc, state, constants, inputs, table_order)
        if best:
            _assign_to_table(job, calc, best, state)
        else:
            still_unscheduled.append((job, calc))
    
    return _state_to_result(state, still_unscheduled, constants, inputs)


def _find_best_table_min_idle(
    job: Job,
    calc: CalculatedFields,
    state: SchedulingState,
    constants: CycleTimeConstants,
    inputs: OperatorInputs,
    table_order: list[CellColor]
) -> tuple | None:
    """Find best table for minimum idle method."""
    compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
    best = None
    best_score = -1
    
    for cell_color in table_order:
        if cell_color not in compliant:
            continue
        
        cell_state = state.cells[cell_color]
        
        for table_num in [1, 2]:
            table = cell_state.table1 if table_num == 1 else cell_state.table2
            
            rough_time = estimate_rough_time(
                job, calc, constants, calc.sched_qty,
                needs_setup=True, summer_mode=inputs.summer_mode
            )
            
            if not table.can_fit_job(rough_time):
                continue
            
            allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
            if not allocation.is_valid:
                continue
            
            # CRITICAL: No C-C or D/E-D/E
            has_conflict = cell_state.has_concurrent_conflict(calc.sched_class, table_num)
            if has_conflict:
                continue  # Critical rule - cannot violate
            
            # PREFERENCE: Preserve most remaining capacity
            new_remaining = table.remaining_capacity - rough_time
            score = new_remaining  # Higher remaining = better
            
            if score > best_score:
                best_score = score
                best = (cell_color, table_num, table, allocation, rough_time)
    
    return best


def method2_min_idle_table_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 2, Variant 2: Minimum Forced Idle - Table First."""
    state = initialize_state(load, constants, inputs)
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    changed = True
    while changed:
        changed = False
        
        # Select table by earliest WHEN_AVAILABLE
        all_tables = []
        for cell_color in table_order:
            cell_state = state.cells[cell_color]
            if not cell_state.is_active:
                continue
            all_tables.append((cell_color, 1, cell_state.table1))
            all_tables.append((cell_color, 2, cell_state.table2))
        
        all_tables.sort(key=lambda x: x[2].when_available)
        
        for cell_color, table_num, table in all_tables:
            cell_state = state.cells[cell_color]
            
            # Find best fitting job
            best_idx = None
            best_score = -1
            best_allocation = None
            best_rough_time = 0
            
            for idx, (job, calc) in enumerate(state.unscheduled_jobs):
                compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
                if cell_color not in compliant:
                    continue
                
                rough_time = estimate_rough_time(
                    job, calc, constants, calc.sched_qty,
                    needs_setup=True, summer_mode=inputs.summer_mode
                )
                if not table.can_fit_job(rough_time):
                    continue
                
                allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
                if not allocation.is_valid:
                    continue
                
                # CRITICAL: No conflicts
                if cell_state.has_concurrent_conflict(calc.sched_class, table_num):
                    continue
                
                # Score: priority (lower better), then fit (preserve capacity)
                score = (10 - calc.priority) * 1000
                score += (table.remaining_capacity - rough_time)
                
                if score > best_score:
                    best_score = score
                    best_idx = idx
                    best_allocation = allocation
                    best_rough_time = rough_time
            
            if best_idx is not None:
                job, calc = state.unscheduled_jobs.pop(best_idx)
                _assign_to_table(job, calc, (cell_color, table_num, table, best_allocation, best_rough_time), state)
                changed = True
                break  # Re-evaluate table order
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)


def method2_min_idle_fixture_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 2, Variant 3: Minimum Forced Idle - Fixture First.
    
    Combines fixture optimization with idle minimization:
    - Groups jobs by fixture_id to minimize SETUP time
    - Within fixture groups, orders by forced idle impact
    """
    state = initialize_state(load, constants, inputs)
    
    # Group jobs by fixture
    fixture_groups: dict[str, list[tuple[Job, CalculatedFields]]] = {}
    for job, calc in state.unscheduled_jobs:
        fixture = calc.fixture_id
        if fixture not in fixture_groups:
            fixture_groups[fixture] = []
        fixture_groups[fixture].append((job, calc))
    
    # Sort within groups by priority and build_date
    for fixture in fixture_groups:
        fixture_groups[fixture].sort(key=lambda x: (x[1].priority, x[1].build_date))
    
    # Sort fixture groups by priority (has P0 first) then total panels
    def fixture_priority(fixture: str) -> tuple:
        jobs = fixture_groups[fixture]
        has_priority_0 = any(calc.priority == 0 for job, calc in jobs)
        total_panels = sum(calc.sched_qty for job, calc in jobs)
        return (0 if has_priority_0 else 1, -total_panels)
    
    sorted_fixtures = sorted(fixture_groups.keys(), key=fixture_priority)
    state.unscheduled_jobs.clear()
    
    remaining_panels: dict[str, int] = {}
    for fixture in sorted_fixtures:
        for job, calc in fixture_groups[fixture]:
            remaining_panels[job.job_id] = calc.sched_qty
    
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    # Process fixture groups
    for fixture in sorted_fixtures:
        for job, calc in fixture_groups[fixture]:
            panels_needed = remaining_panels[job.job_id]
            
            while panels_needed > 0:
                # Find table with minimum forced idle, preferring same fixture
                best = _find_best_table_fixture_aware(
                    job, calc, state, constants, inputs, table_order, fixture
                )
                
                if best is None:
                    break
                
                cell_color, table_num, table, allocation, max_panels = best
                panels_to_assign = min(max_panels, panels_needed)
                
                needs_setup = table.last_fixture != calc.fixture_id
                rough_time = estimate_rough_time(
                    job, calc, constants, panels_to_assign,
                    needs_setup=needs_setup, summer_mode=inputs.summer_mode
                )
                
                for mold_name, count in allocation.mold_assignments.items():
                    state.pool.reserve_molds(mold_name, count)
                state.pool.reserve_fixture(calc.fixture_id)
                
                table.assign_job(job, calc, panels_to_assign, rough_time)
                state.scheduled_jobs.append((job, calc, cell_color, table_num, panels_to_assign))
                
                panels_needed -= panels_to_assign
                remaining_panels[job.job_id] = panels_needed
            
            if remaining_panels[job.job_id] > 0:
                state.unscheduled_jobs.append((job, calc))
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)


def _find_best_table_fixture_aware(
    job: Job,
    calc: CalculatedFields,
    state: SchedulingState,
    constants: CycleTimeConstants,
    inputs: OperatorInputs,
    table_order: list[CellColor],
    prefer_fixture: str | None
) -> tuple | None:
    """Find best table for job, preferring same fixture to save SETUP."""
    compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
    
    best = None
    best_score = -1
    
    for cell_color in table_order:
        if cell_color not in compliant:
            continue
        
        cell_state = state.cells[cell_color]
        
        for table_num in [1, 2]:
            table = cell_state.table1 if table_num == 1 else cell_state.table2
            
            available_time = inputs.shift_minutes - table.when_available
            if available_time < constants.pour_cutoff_minutes:
                continue
            
            needs_setup = table.last_fixture != calc.fixture_id
            max_panels = calculate_max_panels_that_fit(
                job, calc, constants, available_time,
                needs_setup=needs_setup, summer_mode=inputs.summer_mode
            )
            
            if max_panels <= 0:
                continue
            
            allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
            if not allocation.is_valid:
                continue
            
            # Score: same fixture bonus + available time + panels
            score = 0
            if prefer_fixture and table.last_fixture == prefer_fixture:
                score = 1000  # Same fixture - saves SETUP
            elif table.last_fixture is None:
                score = 500
            else:
                score = 100
            
            score += available_time + max_panels * 10
            
            if score > best_score:
                best_score = score
                best = (cell_color, table_num, table, allocation, max_panels)
    
    return best


# =============================================================================
# METHOD 3: MAXIMUM OUTPUT
# =============================================================================

def method3_max_output_job_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 3, Variant 1: Maximum Output - Job First.
    
    CRITICAL RULES:
    - Dedicate cells to SCHED_CLASS A if surplus >= 16 (2 cells) or surplus > 0 (1 cell)
    
    GENERAL RULES:
    - On non-A tables, pair B opposite other classes (avoid B-B)
    - Schedule by lowest priority first
    
    PREFERENCES:
    - Keep all E on one table
    """
    state = initialize_state(load, constants, inputs)
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    # Calculate A surplus
    a_jobs = [(j, c) for j, c in state.unscheduled_jobs if c.sched_class == SCHED_CLASS_A]
    non_a_jobs = [(j, c) for j, c in state.unscheduled_jobs if c.sched_class != SCHED_CLASS_A]
    
    a_qty = sum(c.sched_qty for _, c in a_jobs)
    non_a_qty = sum(c.sched_qty for _, c in non_a_jobs)
    surplus = a_qty - non_a_qty
    
    # Determine A-dedicated cells
    a_cells_count = 0
    if surplus >= 16:
        a_cells_count = 2
    elif surplus > 0:
        a_cells_count = 1
    
    # Select cells with highest remaining capacity for A
    if a_cells_count > 0:
        cell_capacities = [
            (c, state.cells[c].total_remaining_capacity)
            for c in table_order if state.cells[c].is_active
        ]
        cell_capacities.sort(key=lambda x: -x[1])
        a_dedicated_cells = {c for c, _ in cell_capacities[:a_cells_count]}
    else:
        a_dedicated_cells = set()
    
    still_unscheduled = []
    
    # Schedule A jobs to A-dedicated cells first
    a_jobs.sort(key=lambda x: (x[1].priority, x[1].build_date))
    for job, calc in a_jobs:
        best = _find_table_for_max_output(
            job, calc, state, constants, inputs, table_order,
            preferred_cells=a_dedicated_cells if a_dedicated_cells else None,
            avoid_bb=True
        )
        if best:
            _assign_to_table(job, calc, best, state)
        else:
            still_unscheduled.append((job, calc))
    
    # Schedule non-A jobs, avoiding B-B pairing
    non_a_jobs.sort(key=lambda x: (x[1].priority, x[1].build_date))
    
    # Try to keep E jobs on one table
    e_jobs = [(j, c) for j, c in non_a_jobs if c.sched_class == SCHED_CLASS_E]
    other_jobs = [(j, c) for j, c in non_a_jobs if c.sched_class != SCHED_CLASS_E]
    
    # Schedule E jobs first, trying to cluster
    e_table = None
    for job, calc in e_jobs:
        best = _find_table_for_max_output(
            job, calc, state, constants, inputs, table_order,
            preferred_cells=None,
            avoid_bb=True,
            prefer_table=e_table
        )
        if best:
            _assign_to_table(job, calc, best, state)
            e_table = (best[0], best[1])  # Remember table for E clustering
        else:
            still_unscheduled.append((job, calc))
    
    # Schedule remaining jobs
    for job, calc in other_jobs:
        best = _find_table_for_max_output(
            job, calc, state, constants, inputs, table_order,
            preferred_cells=None,
            avoid_bb=True
        )
        if best:
            _assign_to_table(job, calc, best, state)
        else:
            still_unscheduled.append((job, calc))
    
    return _state_to_result(state, still_unscheduled, constants, inputs)


def _find_table_for_max_output(
    job: Job,
    calc: CalculatedFields,
    state: SchedulingState,
    constants: CycleTimeConstants,
    inputs: OperatorInputs,
    table_order: list[CellColor],
    preferred_cells: set[CellColor] | None = None,
    avoid_bb: bool = True,
    prefer_table: tuple[CellColor, int] | None = None
) -> tuple | None:
    """Find best table for maximum output method."""
    compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
    best = None
    best_score = -1
    
    for cell_color in table_order:
        if cell_color not in compliant:
            continue
        
        if preferred_cells and cell_color not in preferred_cells:
            continue
        
        cell_state = state.cells[cell_color]
        
        for table_num in [1, 2]:
            table = cell_state.table1 if table_num == 1 else cell_state.table2
            
            rough_time = estimate_rough_time(
                job, calc, constants, calc.sched_qty,
                needs_setup=True, summer_mode=inputs.summer_mode
            )
            
            if not table.can_fit_job(rough_time):
                continue
            
            allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
            if not allocation.is_valid:
                continue
            
            # Check B-B pairing (general rule)
            opposite = cell_state.get_opposite_table(table_num)
            is_bb = (calc.sched_class == SCHED_CLASS_B and 
                     opposite.current_sched_class == SCHED_CLASS_B)
            
            if avoid_bb and is_bb:
                # Try to avoid but don't make critical
                pass
            
            # Score calculation
            score = 0
            
            # Prefer the specific table for E clustering
            if prefer_table and (cell_color, table_num) == prefer_table:
                score += 500
            
            # Avoid B-B
            if not is_bb:
                score += 200
            
            # Earlier available
            score += (inputs.shift_minutes - table.when_available)
            
            if score > best_score:
                best_score = score
                best = (cell_color, table_num, table, allocation, rough_time)
    
    return best


def method3_max_output_table_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 3, Variant 2: Maximum Output - Table First."""
    state = initialize_state(load, constants, inputs)
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    # Same A-cell dedication logic
    a_jobs = [(j, c) for j, c in state.unscheduled_jobs if c.sched_class == SCHED_CLASS_A]
    non_a_jobs = [(j, c) for j, c in state.unscheduled_jobs if c.sched_class != SCHED_CLASS_A]
    
    a_qty = sum(c.sched_qty for _, c in a_jobs)
    non_a_qty = sum(c.sched_qty for _, c in non_a_jobs)
    surplus = a_qty - non_a_qty
    
    a_cells_count = 2 if surplus >= 16 else (1 if surplus > 0 else 0)
    
    if a_cells_count > 0:
        cell_capacities = [
            (c, state.cells[c].total_remaining_capacity)
            for c in table_order if state.cells[c].is_active
        ]
        cell_capacities.sort(key=lambda x: -x[1])
        a_dedicated_cells = {c for c, _ in cell_capacities[:a_cells_count]}
    else:
        a_dedicated_cells = set()
    
    changed = True
    while changed:
        changed = False
        
        for cell_color in table_order:
            cell_state = state.cells[cell_color]
            if not cell_state.is_active:
                continue
            
            is_a_cell = cell_color in a_dedicated_cells
            
            for table_num in [1, 2]:
                table = cell_state.table1 if table_num == 1 else cell_state.table2
                
                # Find best job
                best_idx = None
                best_score = -1
                best_allocation = None
                best_rough_time = 0
                
                for idx, (job, calc) in enumerate(state.unscheduled_jobs):
                    # A-cells only take A jobs
                    if is_a_cell and calc.sched_class != SCHED_CLASS_A:
                        continue
                    
                    compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
                    if cell_color not in compliant:
                        continue
                    
                    rough_time = estimate_rough_time(
                        job, calc, constants, calc.sched_qty,
                        needs_setup=True, summer_mode=inputs.summer_mode
                    )
                    if not table.can_fit_job(rough_time):
                        continue
                    
                    allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
                    if not allocation.is_valid:
                        continue
                    
                    # Avoid B-B
                    opposite = cell_state.get_opposite_table(table_num)
                    is_bb = (calc.sched_class == SCHED_CLASS_B and 
                             opposite.current_sched_class == SCHED_CLASS_B)
                    
                    # Score: priority, avoid B-B
                    score = (10 - calc.priority) * 100
                    if not is_bb:
                        score += 50
                    
                    if score > best_score:
                        best_score = score
                        best_idx = idx
                        best_allocation = allocation
                        best_rough_time = rough_time
                
                if best_idx is not None:
                    job, calc = state.unscheduled_jobs.pop(best_idx)
                    _assign_to_table(job, calc, (cell_color, table_num, table, best_allocation, best_rough_time), state)
                    changed = True
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)


def method3_max_output_fixture_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 3, Variant 3: Maximum Output - Fixture First.
    
    Combines fixture optimization with output maximization:
    - Groups jobs by fixture_id to minimize SETUP time
    - Within fixture groups, orders by panels/time efficiency
    """
    state = initialize_state(load, constants, inputs)
    
    # Group jobs by fixture
    fixture_groups: dict[str, list[tuple[Job, CalculatedFields]]] = {}
    for job, calc in state.unscheduled_jobs:
        fixture = calc.fixture_id
        if fixture not in fixture_groups:
            fixture_groups[fixture] = []
        fixture_groups[fixture].append((job, calc))
    
    # Sort within groups by panels (most first for max output)
    for fixture in fixture_groups:
        fixture_groups[fixture].sort(key=lambda x: (-x[1].sched_qty, x[1].priority))
    
    # Sort fixture groups by total panels (most first)
    def fixture_priority(fixture: str) -> tuple:
        jobs = fixture_groups[fixture]
        has_priority_0 = any(calc.priority == 0 for job, calc in jobs)
        total_panels = sum(calc.sched_qty for job, calc in jobs)
        return (0 if has_priority_0 else 1, -total_panels)
    
    sorted_fixtures = sorted(fixture_groups.keys(), key=fixture_priority)
    state.unscheduled_jobs.clear()
    
    remaining_panels: dict[str, int] = {}
    for fixture in sorted_fixtures:
        for job, calc in fixture_groups[fixture]:
            remaining_panels[job.job_id] = calc.sched_qty
    
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    for fixture in sorted_fixtures:
        for job, calc in fixture_groups[fixture]:
            panels_needed = remaining_panels[job.job_id]
            
            while panels_needed > 0:
                best = _find_best_table_fixture_aware(
                    job, calc, state, constants, inputs, table_order, fixture
                )
                
                if best is None:
                    break
                
                cell_color, table_num, table, allocation, max_panels = best
                panels_to_assign = min(max_panels, panels_needed)
                
                needs_setup = table.last_fixture != calc.fixture_id
                rough_time = estimate_rough_time(
                    job, calc, constants, panels_to_assign,
                    needs_setup=needs_setup, summer_mode=inputs.summer_mode
                )
                
                for mold_name, count in allocation.mold_assignments.items():
                    state.pool.reserve_molds(mold_name, count)
                state.pool.reserve_fixture(calc.fixture_id)
                
                table.assign_job(job, calc, panels_to_assign, rough_time)
                state.scheduled_jobs.append((job, calc, cell_color, table_num, panels_to_assign))
                
                panels_needed -= panels_to_assign
                remaining_panels[job.job_id] = panels_needed
            
            if remaining_panels[job.job_id] > 0:
                state.unscheduled_jobs.append((job, calc))
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)


# =============================================================================
# METHOD 4: MOST RESTRICTED MIX
# =============================================================================

def method4_restricted_mix_job_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 4, Variant 1: Most Restricted Mix - Job First.
    
    CRITICAL RULES:
    - Pair D and E opposite C until all D/E scheduled
    - If no C available, pair D/E opposite B
    
    GENERAL RULES:
    - Lower priority as tie-breaker
    - Higher BUILD_LOAD as tie-breaker
    
    Supports job splitting across multiple tables when job doesn't fit on single table.
    """
    state = initialize_state(load, constants, inputs)
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    # Track remaining panels for each job
    remaining_panels = {job.job_id: calc.sched_qty for job, calc in state.unscheduled_jobs}
    job_lookup = {job.job_id: (job, calc) for job, calc in state.unscheduled_jobs}
    
    # Separate by class
    de_jobs = [(j, c) for j, c in state.unscheduled_jobs 
               if c.sched_class in {SCHED_CLASS_D, SCHED_CLASS_E}]
    c_jobs = [(j, c) for j, c in state.unscheduled_jobs if c.sched_class == SCHED_CLASS_C]
    b_jobs = [(j, c) for j, c in state.unscheduled_jobs if c.sched_class == SCHED_CLASS_B]
    a_jobs = [(j, c) for j, c in state.unscheduled_jobs if c.sched_class == SCHED_CLASS_A]
    
    # Sort by priority, then BUILD_LOAD descending
    for job_list in [de_jobs, c_jobs, b_jobs, a_jobs]:
        job_list.sort(key=lambda x: (x[1].priority, -x[1].build_load))
    
    def schedule_job_list(job_list, prefer_opposite, fallback_opposite):
        """Schedule jobs from a list, allowing partial assignments."""
        made_progress = True
        while made_progress:
            made_progress = False
            for job, calc in job_list:
                if remaining_panels[job.job_id] <= 0:
                    continue
                
                best = _find_table_restricted_mix(
                    job, calc, state, constants, inputs, table_order,
                    prefer_opposite=prefer_opposite,
                    fallback_opposite=fallback_opposite,
                    panels_needed=remaining_panels[job.job_id]
                )
                if best:
                    panels_assigned = _assign_to_table(job, calc, best, state)
                    remaining_panels[job.job_id] -= panels_assigned
                    made_progress = True
    
    # Schedule D/E first, pairing opposite C
    schedule_job_list(de_jobs, prefer_opposite={SCHED_CLASS_C}, fallback_opposite={SCHED_CLASS_B})
    
    # Schedule C jobs (prefer opposite D/E or B)
    schedule_job_list(c_jobs, prefer_opposite={SCHED_CLASS_D, SCHED_CLASS_E}, fallback_opposite={SCHED_CLASS_B})
    
    # Schedule B jobs
    schedule_job_list(b_jobs, prefer_opposite=None, fallback_opposite=None)
    
    # Schedule A jobs
    schedule_job_list(a_jobs, prefer_opposite=None, fallback_opposite=None)
    
    # Build unscheduled list (jobs with remaining panels)
    still_unscheduled = []
    for job_id, panels_left in remaining_panels.items():
        if panels_left > 0:
            job, calc = job_lookup[job_id]
            still_unscheduled.append((job, calc))
    
    return _state_to_result(state, still_unscheduled, constants, inputs)


def _find_table_restricted_mix(
    job: Job,
    calc: CalculatedFields,
    state: SchedulingState,
    constants: CycleTimeConstants,
    inputs: OperatorInputs,
    table_order: list[CellColor],
    prefer_opposite: set[str] | None,
    fallback_opposite: set[str] | None,
    panels_needed: int | None = None
) -> tuple | None:
    """Find table for restricted mix method.
    
    Args:
        panels_needed: If specified, find table for this many panels (may be partial job).
                      If None, uses calc.sched_qty (full job).
    """
    compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
    candidates = []
    
    if panels_needed is None:
        panels_needed = calc.sched_qty
    
    for cell_color in table_order:
        if cell_color not in compliant:
            continue
        
        cell_state = state.cells[cell_color]
        
        for table_num in [1, 2]:
            table = cell_state.table1 if table_num == 1 else cell_state.table2
            
            available_time = inputs.shift_minutes - table.when_available
            needs_setup = table.last_fixture != calc.fixture_id
            
            # Calculate max panels that fit
            max_panels = calculate_max_panels_that_fit(
                job, calc, constants, available_time,
                needs_setup=needs_setup, summer_mode=inputs.summer_mode
            )
            
            if max_panels <= 0:
                continue
            
            allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
            if not allocation.is_valid:
                continue
            
            panels_to_assign = min(max_panels, panels_needed)
            
            rough_time = estimate_rough_time(
                job, calc, constants, panels_to_assign,
                needs_setup=needs_setup, summer_mode=inputs.summer_mode
            )
            
            opposite = cell_state.get_opposite_table(table_num)
            opp_class = opposite.current_sched_class
            
            # Score based on opposite pairing
            score = 0
            if prefer_opposite and opp_class in prefer_opposite:
                score = 1000
            elif fallback_opposite and opp_class in fallback_opposite:
                score = 500
            elif opp_class is None:
                score = 250  # Empty opposite is acceptable
            
            # Prefer assignments that schedule more panels
            score += panels_to_assign * 10
            
            # Tie-breakers
            score += (inputs.shift_minutes - table.when_available) // 10
            
            candidates.append((score, cell_color, table_num, table, allocation, rough_time, panels_to_assign))
    
    if not candidates:
        return None
    
    candidates.sort(key=lambda x: -x[0])
    _, cell_color, table_num, table, allocation, rough_time, panels_to_assign = candidates[0]
    return (cell_color, table_num, table, allocation, rough_time, panels_to_assign)


def method4_restricted_mix_table_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 4, Variant 2: Most Restricted Mix - Table First."""
    state = initialize_state(load, constants, inputs)
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    changed = True
    while changed:
        changed = False
        
        for cell_color in table_order:
            cell_state = state.cells[cell_color]
            if not cell_state.is_active:
                continue
            
            for table_num in [1, 2]:
                table = cell_state.table1 if table_num == 1 else cell_state.table2
                opposite = cell_state.get_opposite_table(table_num)
                opp_class = opposite.current_sched_class
                
                # Determine preferred classes based on opposite
                if opp_class == SCHED_CLASS_C:
                    preferred = {SCHED_CLASS_D, SCHED_CLASS_E}
                elif opp_class in {SCHED_CLASS_D, SCHED_CLASS_E}:
                    preferred = {SCHED_CLASS_C, SCHED_CLASS_B}
                else:
                    preferred = None
                
                best_idx = None
                best_score = -1
                best_allocation = None
                best_rough_time = 0
                
                for idx, (job, calc) in enumerate(state.unscheduled_jobs):
                    compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
                    if cell_color not in compliant:
                        continue
                    
                    rough_time = estimate_rough_time(
                        job, calc, constants, calc.sched_qty,
                        needs_setup=True, summer_mode=inputs.summer_mode
                    )
                    if not table.can_fit_job(rough_time):
                        continue
                    
                    allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
                    if not allocation.is_valid:
                        continue
                    
                    # Score: preferred class, then priority, then BUILD_LOAD
                    score = 0
                    if preferred and calc.sched_class in preferred:
                        score += 1000
                    score += (10 - calc.priority) * 100
                    score += calc.build_load * 10
                    
                    if score > best_score:
                        best_score = score
                        best_idx = idx
                        best_allocation = allocation
                        best_rough_time = rough_time
                
                if best_idx is not None:
                    job, calc = state.unscheduled_jobs.pop(best_idx)
                    _assign_to_table(job, calc, (cell_color, table_num, table, best_allocation, best_rough_time), state)
                    changed = True
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _assign_to_table(
    job: Job,
    calc: CalculatedFields,
    assignment: tuple,
    state: SchedulingState,
    panels: int | None = None
) -> int:
    """Assign a job (or partial job) to a table.
    
    Args:
        job: Job to assign.
        calc: Calculated fields.
        assignment: Tuple from find_table functions.
        state: Scheduling state.
        panels: Number of panels to assign. If None, uses calc.sched_qty.
                If assignment has 6 elements, uses the 6th as panels.
    
    Returns:
        Number of panels actually assigned.
    """
    # Handle both old 5-element and new 6-element assignment tuples
    if len(assignment) == 6:
        cell_color, table_num, table, allocation, rough_time, panels_from_tuple = assignment
        if panels is None:
            panels = panels_from_tuple
    else:
        cell_color, table_num, table, allocation, rough_time = assignment
        if panels is None:
            panels = calc.sched_qty
    
    # Release previous molds from this table (molds become available when job finishes)
    prev_molds = table.get_mold_allocation()
    for mold_name, count in prev_molds.items():
        state.pool.release_molds(mold_name, count)
    
    # Reserve new molds
    for mold_name, count in allocation.mold_assignments.items():
        state.pool.reserve_molds(mold_name, count)
    
    # Track molds on this table
    table.set_mold_allocation(allocation.mold_assignments)
    
    state.pool.reserve_fixture(calc.fixture_id)
    
    # Assign to table
    table.assign_job(job, calc, panels, rough_time)
    state.scheduled_jobs.append((job, calc, cell_color, table_num, panels))
    
    return panels


def _state_to_result(
    state: SchedulingState,
    unscheduled: list[tuple[Job, CalculatedFields]],
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Convert scheduling state to MultiCellScheduleResult by running solver.
    
    The heuristic methods determine job-to-cell assignments.
    We then BALANCE jobs between the two tables in each cell and run the scheduler.
    This ensures the operator can alternate efficiently between tables.
    """
    result = MultiCellScheduleResult(
        schedule_date=state.schedule_date,
        shift_minutes=state.shift_minutes
    )
    
    # Group scheduled jobs by cell (ignoring original table assignment)
    cell_jobs: dict[CellColor, list[tuple[Job, CalculatedFields, int]]] = {}
    
    for job, calc, cell_color, table_num, panels in state.scheduled_jobs:
        if cell_color not in cell_jobs:
            cell_jobs[cell_color] = []
        cell_jobs[cell_color].append((job, calc, panels))
    
    # Schedule each cell with balanced table distribution
    for cell_color in inputs.active_cells:
        if cell_color not in cell_jobs:
            # No jobs on this cell
            result.cell_results[cell_color] = CellScheduleResult(
                cell_color=cell_color,
                shift_minutes=inputs.shift_minutes,
                status="OPTIMAL",
                total_panels=0
            )
            continue
        
        jobs_list = cell_jobs[cell_color]
        
        # Separate ON_TABLE_TODAY jobs (they stay on their assigned table)
        on_table_t1 = []
        on_table_t2 = []
        regular_jobs = []
        
        for job, calc, panels in jobs_list:
            if job.on_table_today:
                parts = job.on_table_today.rsplit("_", 1)
                if len(parts) == 2 and parts[0] == cell_color:
                    table_num = int(parts[1])
                    if table_num == 1:
                        on_table_t1.append((job, calc, panels))
                    else:
                        on_table_t2.append((job, calc, panels))
                else:
                    regular_jobs.append((job, calc, panels))
            else:
                regular_jobs.append((job, calc, panels))
        
        # Balance regular jobs between tables using alternating assignment
        # This ensures both tables have work for efficient operator alternation
        t1_jobs = list(on_table_t1)
        t2_jobs = list(on_table_t2)
        
        # Sort regular jobs by SCHED_CLASS for efficient grouping on same table
        # But alternate assignment to balance load
        regular_jobs.sort(key=lambda x: (x[1].sched_class, x[1].priority, x[1].build_date))
        
        # Estimate total panels per table and balance
        t1_panels = sum(p for _, _, p in t1_jobs)
        t2_panels = sum(p for _, _, p in t2_jobs)
        
        for job, calc, panels in regular_jobs:
            # Assign to table with fewer panels
            if t1_panels <= t2_panels:
                t1_jobs.append((job, calc, panels))
                t1_panels += panels
            else:
                t2_jobs.append((job, calc, panels))
                t2_panels += panels
        
        # Convert to JobAssignments
        t1_assignments = [
            JobAssignment(
                job=job,
                calc=calc,
                panels_to_schedule=panels,
                is_on_table_today=bool(job.on_table_today),
                starts_with_pour=bool(job.on_table_today)
            )
            for job, calc, panels in t1_jobs
        ]
        
        t2_assignments = [
            JobAssignment(
                job=job,
                calc=calc,
                panels_to_schedule=panels,
                is_on_table_today=bool(job.on_table_today),
                starts_with_pour=bool(job.on_table_today)
            )
            for job, calc, panels in t2_jobs
        ]
        
        # Schedule the cell
        cell_result = schedule_cell(
            cell_color=cell_color,
            shift_minutes=inputs.shift_minutes,
            table1_assignments=t1_assignments,
            table2_assignments=t2_assignments,
            constants=constants,
            summer_mode=inputs.summer_mode,
            pour_cutoff=constants.pour_cutoff_minutes
        )
        
        result.cell_results[cell_color] = cell_result
        
        # Create job assignments (record actual table assignments)
        for job, calc, panels in t1_jobs:
            result.job_assignments.append(JobCellAssignment(
                job=job,
                calc=calc,
                cell_color=cell_color,
                table_num=1,
                panels_to_schedule=panels,
                is_on_table_today=bool(job.on_table_today)
            ))
        
        for job, calc, panels in t2_jobs:
            result.job_assignments.append(JobCellAssignment(
                job=job,
                calc=calc,
                cell_color=cell_color,
                table_num=2,
                panels_to_schedule=panels,
                is_on_table_today=bool(job.on_table_today)
            ))
    
    # Add unscheduled jobs (include calc fields for reporting)
    for job, calc in unscheduled:
        result.unscheduled_jobs.append((job, calc, "No viable table assignment"))
    
    # Calculate totals
    result.total_panels = sum(cr.total_panels for cr in result.cell_results.values())
    result.total_operator_minutes = sum(cr.total_operator_time for cr in result.cell_results.values())
    
    # Determine status
    if not result.cell_results:
        result.status = "INFEASIBLE"
    elif all(cr.status == "OPTIMAL" for cr in result.cell_results.values()):
        result.status = "OPTIMAL" if not result.unscheduled_jobs else "PARTIAL"
    elif any(cr.is_feasible for cr in result.cell_results.values()):
        result.status = "FEASIBLE" if not result.unscheduled_jobs else "PARTIAL"
    else:
        result.status = "INFEASIBLE"
    
    return result


def method4_restricted_mix_fixture_first(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Method 4, Variant 3: Most Restricted Mix - Fixture First.
    
    Combines fixture optimization with restricted mix constraints:
    - Groups jobs by fixture_id to minimize SETUP time
    - Maintains D/E-C pairing preference as soft constraint
    """
    state = initialize_state(load, constants, inputs)
    
    # Separate jobs by class first
    de_jobs = []
    c_jobs = []
    b_jobs = []
    a_jobs = []
    
    for job, calc in state.unscheduled_jobs:
        if calc.sched_class in {SCHED_CLASS_D, SCHED_CLASS_E}:
            de_jobs.append((job, calc))
        elif calc.sched_class == SCHED_CLASS_C:
            c_jobs.append((job, calc))
        elif calc.sched_class == SCHED_CLASS_B:
            b_jobs.append((job, calc))
        else:
            a_jobs.append((job, calc))
    
    # Group each class by fixture
    def group_by_fixture(jobs):
        groups = {}
        for job, calc in jobs:
            f = calc.fixture_id
            if f not in groups:
                groups[f] = []
            groups[f].append((job, calc))
        # Sort fixtures by total panels
        return sorted(groups.items(), key=lambda x: -sum(c.sched_qty for j, c in x[1]))
    
    de_fixture_groups = group_by_fixture(de_jobs)
    c_fixture_groups = group_by_fixture(c_jobs)
    b_fixture_groups = group_by_fixture(b_jobs)
    a_fixture_groups = group_by_fixture(a_jobs)
    
    state.unscheduled_jobs.clear()
    remaining_panels: dict[str, int] = {}
    
    for groups in [de_fixture_groups, c_fixture_groups, b_fixture_groups, a_fixture_groups]:
        for fixture, jobs in groups:
            for job, calc in jobs:
                remaining_panels[job.job_id] = calc.sched_qty
    
    table_order = get_table_order(inputs.schedule_date, inputs.active_cells)
    
    def schedule_fixture_group(fixture: str, jobs: list, prefer_opposite: set | None):
        for job, calc in jobs:
            panels_needed = remaining_panels[job.job_id]
            
            while panels_needed > 0:
                best = _find_table_restricted_fixture(
                    job, calc, state, constants, inputs, table_order,
                    fixture, prefer_opposite
                )
                
                if best is None:
                    break
                
                cell_color, table_num, table, allocation, max_panels = best
                panels_to_assign = min(max_panels, panels_needed)
                
                needs_setup = table.last_fixture != calc.fixture_id
                rough_time = estimate_rough_time(
                    job, calc, constants, panels_to_assign,
                    needs_setup=needs_setup, summer_mode=inputs.summer_mode
                )
                
                for mold_name, count in allocation.mold_assignments.items():
                    state.pool.reserve_molds(mold_name, count)
                state.pool.reserve_fixture(calc.fixture_id)
                
                table.assign_job(job, calc, panels_to_assign, rough_time)
                state.scheduled_jobs.append((job, calc, cell_color, table_num, panels_to_assign))
                
                panels_needed -= panels_to_assign
                remaining_panels[job.job_id] = panels_needed
            
            if remaining_panels[job.job_id] > 0:
                state.unscheduled_jobs.append((job, calc))
    
    # Schedule D/E first (prefer opposite C)
    for fixture, jobs in de_fixture_groups:
        schedule_fixture_group(fixture, jobs, {SCHED_CLASS_C})
    
    # Schedule C (prefer opposite D/E)
    for fixture, jobs in c_fixture_groups:
        schedule_fixture_group(fixture, jobs, {SCHED_CLASS_D, SCHED_CLASS_E})
    
    # Schedule B and A
    for fixture, jobs in b_fixture_groups:
        schedule_fixture_group(fixture, jobs, None)
    for fixture, jobs in a_fixture_groups:
        schedule_fixture_group(fixture, jobs, None)
    
    return _state_to_result(state, state.unscheduled_jobs, constants, inputs)


def _find_table_restricted_fixture(
    job: Job,
    calc: CalculatedFields,
    state: SchedulingState,
    constants: CycleTimeConstants,
    inputs: OperatorInputs,
    table_order: list[CellColor],
    prefer_fixture: str | None,
    prefer_opposite: set | None
) -> tuple | None:
    """Find best table for restricted mix with fixture preference."""
    compliant = get_compliant_cells_for_job(job, calc, constants, inputs.active_cells, inputs)
    
    best = None
    best_score = -1
    
    for cell_color in table_order:
        if cell_color not in compliant:
            continue
        
        cell_state = state.cells[cell_color]
        
        for table_num in [1, 2]:
            table = cell_state.table1 if table_num == 1 else cell_state.table2
            
            available_time = inputs.shift_minutes - table.when_available
            if available_time < constants.pour_cutoff_minutes:
                continue
            
            needs_setup = table.last_fixture != calc.fixture_id
            max_panels = calculate_max_panels_that_fit(
                job, calc, constants, available_time,
                needs_setup=needs_setup, summer_mode=inputs.summer_mode
            )
            
            if max_panels <= 0:
                continue
            
            allocation = allocate_molds_for_job(job, calc, cell_color, state.pool, constants)
            if not allocation.is_valid:
                continue
            
            # Score based on: fixture match, opposite class preference, time
            score = 0
            
            # Fixture matching bonus (saves SETUP)
            if prefer_fixture and table.last_fixture == prefer_fixture:
                score += 1000
            elif table.last_fixture is None:
                score += 500
            else:
                score += 100
            
            # Opposite class pairing bonus
            if prefer_opposite:
                opposite = cell_state.get_opposite_table(table_num)
                if opposite.current_sched_class in prefer_opposite:
                    score += 500
                elif opposite.current_sched_class == SCHED_CLASS_B:
                    score += 250  # B is acceptable fallback
            
            score += available_time + max_panels * 10
            
            if score > best_score:
                best_score = score
                best = (cell_color, table_num, table, allocation, max_panels)
    
    return best


# =============================================================================
# MAIN API
# =============================================================================

def run_method(
    method: SchedulingMethod,
    variant: SchedulingVariant,
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> MultiCellScheduleResult:
    """Run a specific scheduling method and variant.
    
    Args:
        method: The scheduling method (1-4).
        variant: The variant (job-first or table-first).
        load: Daily production load.
        constants: Cycle time constants.
        inputs: Operator inputs.
    
    Returns:
        MultiCellScheduleResult with the schedule.
    """
    method_map = {
        (SchedulingMethod.PRIORITY_FIRST, SchedulingVariant.JOB_FIRST): method1_priority_first_job_first,
        (SchedulingMethod.PRIORITY_FIRST, SchedulingVariant.TABLE_FIRST): method1_priority_first_table_first,
        (SchedulingMethod.PRIORITY_FIRST, SchedulingVariant.FIXTURE_FIRST): method1_priority_first_fixture_first,
        (SchedulingMethod.MINIMUM_FORCED_IDLE, SchedulingVariant.JOB_FIRST): method2_min_idle_job_first,
        (SchedulingMethod.MINIMUM_FORCED_IDLE, SchedulingVariant.TABLE_FIRST): method2_min_idle_table_first,
        (SchedulingMethod.MINIMUM_FORCED_IDLE, SchedulingVariant.FIXTURE_FIRST): method2_min_idle_fixture_first,
        (SchedulingMethod.MAXIMUM_OUTPUT, SchedulingVariant.JOB_FIRST): method3_max_output_job_first,
        (SchedulingMethod.MAXIMUM_OUTPUT, SchedulingVariant.TABLE_FIRST): method3_max_output_table_first,
        (SchedulingMethod.MAXIMUM_OUTPUT, SchedulingVariant.FIXTURE_FIRST): method3_max_output_fixture_first,
        (SchedulingMethod.MOST_RESTRICTED_MIX, SchedulingVariant.JOB_FIRST): method4_restricted_mix_job_first,
        (SchedulingMethod.MOST_RESTRICTED_MIX, SchedulingVariant.TABLE_FIRST): method4_restricted_mix_table_first,
        (SchedulingMethod.MOST_RESTRICTED_MIX, SchedulingVariant.FIXTURE_FIRST): method4_restricted_mix_fixture_first,
    }
    
    func = method_map.get((method, variant))
    if not func:
        raise ValueError(f"Unknown method/variant: {method}, {variant}")
    
    return func(load, constants, inputs)


def run_all_methods(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    inputs: OperatorInputs
) -> dict[tuple[SchedulingMethod, SchedulingVariant], MultiCellScheduleResult]:
    """Run all 8 method/variant combinations.
    
    Args:
        load: Daily production load.
        constants: Cycle time constants.
        inputs: Operator inputs.
    
    Returns:
        Dict mapping (method, variant) to result.
    """
    results = {}
    
    for method in SchedulingMethod:
        for variant in SchedulingVariant:
            results[(method, variant)] = run_method(method, variant, load, constants, inputs)
    
    return results
