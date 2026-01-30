# Cell Scheduler - Simulation-based scheduling with proper table alternation.
# Version: 1.0.0
# Simulates operator workflow: work T1 to POUR, move to T2, return for UNLOAD, etc.

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional
from enum import Enum

from .constants import CycleTimeConstants, CellColor
from .data_loader import Job
from .calculated_fields import CalculatedFields


class TaskType(Enum):
    """Task types in sequence order."""
    SETUP = 0
    LAYOUT = 1
    POUR = 2
    CURE = 3
    UNLOAD = 4


@dataclass
class ScheduledTask:
    """A scheduled task with timing."""
    task_name: str
    start_time: int
    end_time: int
    duration: int
    requires_operator: bool
    
    @property
    def is_complete(self) -> bool:
        return self.end_time > self.start_time


@dataclass
class ScheduledPanel:
    """A completed panel with all task times."""
    table_id: str
    panel_index: int
    job_id: str
    tasks: dict[str, ScheduledTask] = field(default_factory=dict)
    
    @property
    def start_time(self) -> int:
        return self.tasks["SETUP"].start_time if "SETUP" in self.tasks else 0
    
    @property
    def end_time(self) -> int:
        return self.tasks["UNLOAD"].end_time if "UNLOAD" in self.tasks else 0


@dataclass
class JobAssignment:
    """A job assigned to a table."""
    job: Job
    calc: CalculatedFields
    panels_to_schedule: int
    is_on_table_today: bool = False
    starts_with_pour: bool = False  # True if LAYOUT already done (ON_TABLE_TODAY)


@dataclass
class TaskTimes:
    """Task durations for a panel."""
    setup: int  # 0 if same fixture as prior
    layout: int
    pour: int  # Already multiplied by molds
    cure: int  # Already multiplied by summer factor
    unload: int
    
    @property
    def operator_time_to_pour(self) -> int:
        """Time for operator to complete SETUP + LAYOUT + POUR."""
        return self.setup + self.layout + self.pour
    
    @property
    def operator_time_after_cure(self) -> int:
        """Time for UNLOAD."""
        return self.unload


@dataclass
class TableState:
    """Tracks state of a single table during scheduling."""
    table_id: str
    assignments: list[JobAssignment]
    
    # Current position
    current_job_idx: int = 0
    current_panel_in_job: int = 0  # Panel within current job (0-based)
    total_panels_done: int = 0
    
    # Task state for current panel
    current_task: Optional[TaskType] = None
    task_start_time: int = 0
    
    # Timing
    cure_end_time: Optional[int] = None  # When current CURE will finish
    current_times: Optional[TaskTimes] = None  # Task times for current panel
    
    # Completed panels
    completed_panels: list[ScheduledPanel] = field(default_factory=list)
    
    # Current panel being built
    current_panel_tasks: dict[str, ScheduledTask] = field(default_factory=dict)
    
    # Fixture tracking
    last_fixture: Optional[str] = None
    
    @property
    def is_done(self) -> bool:
        """True if no more jobs to schedule."""
        return self.current_job_idx >= len(self.assignments)
    
    @property
    def current_assignment(self) -> Optional[JobAssignment]:
        if self.current_job_idx < len(self.assignments):
            return self.assignments[self.current_job_idx]
        return None
    
    @property
    def waiting_for_cure(self) -> bool:
        """True if table is in CURE and waiting for it to complete."""
        return self.current_task == TaskType.CURE and self.cure_end_time is not None
    
    @property
    def ready_for_unload(self) -> bool:
        """True if CURE is done and waiting for UNLOAD."""
        return self.current_task == TaskType.CURE and self.cure_end_time is not None
    
    def needs_setup(self) -> bool:
        """Check if next panel needs SETUP (different fixture)."""
        if self.current_job_idx >= len(self.assignments):
            return False
        assignment = self.assignments[self.current_job_idx]
        current_fixture = assignment.job.fixture_id
        return current_fixture != self.last_fixture


@dataclass
class EndOfDayPrepPanel:
    """A panel prepared at end of day - SETUP and LAYOUT done, ready for POUR tomorrow.
    
    This panel will become ON_TABLE_TODAY for the next day's schedule.
    """
    table_id: str
    job_id: str
    job: Job
    calc: CalculatedFields
    setup_task: ScheduledTask
    layout_task: ScheduledTask
    
    @property
    def end_time(self) -> int:
        """Time when LAYOUT completed."""
        return self.layout_task.end_time


@dataclass 
class CellScheduleResult:
    """Result of scheduling a single cell."""
    cell_color: str
    shift_minutes: int
    status: str
    table1_panels: list[ScheduledPanel] = field(default_factory=list)
    table2_panels: list[ScheduledPanel] = field(default_factory=list)
    total_panels: int = 0
    total_operator_time: int = 0
    forced_operator_idle: int = 0
    forced_table_idle: dict[str, int] = field(default_factory=dict)
    # End-of-day prep panels (SETUP+LAYOUT done, ready for POUR tomorrow)
    table1_prep: Optional[EndOfDayPrepPanel] = None
    table2_prep: Optional[EndOfDayPrepPanel] = None
    
    @property
    def is_feasible(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")


def calculate_task_times(
    job: Job,
    calc: CalculatedFields,
    constants: CycleTimeConstants,
    summer_mode: bool,
    needs_setup: bool
) -> TaskTimes:
    """Calculate task durations for a panel.
    
    Args:
        job: The job being scheduled.
        calc: Calculated fields for the job.
        constants: Cycle time constants.
        summer_mode: Whether summer CURE multiplier applies.
        needs_setup: Whether SETUP is needed (False if same fixture).
    
    Returns:
        TaskTimes with all durations.
    """
    timing = constants.get_task_timing(job.wire_diameter, job.equivalent)
    
    setup = timing.setup if needs_setup else 0
    layout = timing.layout
    pour = int(timing.pour * job.molds)
    cure = int(timing.cure * (1.5 if summer_mode else 1.0))
    unload = timing.unload
    
    return TaskTimes(
        setup=setup,
        layout=layout,
        pour=pour,
        cure=cure,
        unload=unload
    )


def schedule_cell(
    cell_color: str,
    shift_minutes: int,
    table1_assignments: list[JobAssignment],
    table2_assignments: list[JobAssignment],
    constants: CycleTimeConstants,
    summer_mode: bool = False,
    pour_cutoff: int = 40
) -> CellScheduleResult:
    """Schedule a cell using simulation-based approach with DYNAMIC table assignment.
    
    The operator alternates between tables. Panels are dynamically assigned to 
    whichever table is ready next, ensuring both tables stay busy.
    
    ON_TABLE_TODAY jobs are pinned to their assigned table.
    Regular jobs are assigned to whichever table completes CURE first.
    
    Pattern:
    1. Work T1: SETUP → LAYOUT → POUR (CURE starts, operator leaves)
    2. Work T2: SETUP → LAYOUT → POUR (CURE starts, operator leaves)
    3. Return to whichever table has CURE done first: UNLOAD, then next panel
    4. Continue alternating, always going to the table that's ready
    
    Args:
        cell_color: Cell identifier (RED, BLUE, etc.)
        shift_minutes: Available minutes (440 or 500)
        table1_assignments: Jobs pinned to table 1 (ON_TABLE_TODAY)
        table2_assignments: Jobs pinned to table 2 (ON_TABLE_TODAY)
        constants: Cycle time constants
        summer_mode: Summer CURE multiplier
        pour_cutoff: Minimum minutes needed to start POUR (default 40)
    
    Returns:
        CellScheduleResult with scheduled panels and metrics.
    """
    # Build panel queues from all assignments
    # ON_TABLE_TODAY jobs are pinned to their assigned table
    # Other jobs go to their table's queue (can be dynamically balanced)
    
    pinned_t1_panels = []  # [(job, calc, starts_with_pour)]
    pinned_t2_panels = []
    t1_panel_queue = []  # Jobs assigned to T1
    t2_panel_queue = []  # Jobs assigned to T2
    
    # Extract panels from T1 assignments
    for assignment in table1_assignments:
        if assignment.is_on_table_today:
            pinned_t1_panels.append((assignment.job, assignment.calc, True))  # starts_with_pour=True
        else:
            for _ in range(assignment.panels_to_schedule):
                t1_panel_queue.append((assignment.job, assignment.calc))
    
    # Extract panels from T2 assignments
    for assignment in table2_assignments:
        if assignment.is_on_table_today:
            pinned_t2_panels.append((assignment.job, assignment.calc, True))
        else:
            for _ in range(assignment.panels_to_schedule):
                t2_panel_queue.append((assignment.job, assignment.calc))
    
    # Initialize table states
    t1 = _DynamicTableState(table_id=f"{cell_color}_1")
    t2 = _DynamicTableState(table_id=f"{cell_color}_2")
    
    # Add pinned panels to their tables (these can't move)
    for job, calc, starts_pour in pinned_t1_panels:
        t1.panel_queue.append((job, calc, starts_pour))
    for job, calc, starts_pour in pinned_t2_panels:
        t2.panel_queue.append((job, calc, starts_pour))
    
    result = CellScheduleResult(
        cell_color=cell_color,
        shift_minutes=shift_minutes,
        status="FEASIBLE",
        forced_table_idle={f"{cell_color}_1": 0, f"{cell_color}_2": 0}
    )
    
    current_time = 0
    forced_operator_idle = 0
    
    # Track end-of-day prep panels (SETUP+LAYOUT done, ready for tomorrow)
    t1_prep_panel: Optional[EndOfDayPrepPanel] = None
    t2_prep_panel: Optional[EndOfDayPrepPanel] = None
    
    # Helper function to get next panel for a table
    def get_next_panel_for_table(table: _DynamicTableState, primary_queue: list, secondary_queue: list):
        """Get next panel - try table's own queue first, then other table's queue for balancing."""
        if table.panel_queue:
            return table.panel_queue.pop(0), True  # (job, calc, starts_pour), is_pinned
        elif primary_queue:
            job, calc = primary_queue.pop(0)
            return (job, calc, False), False
        elif secondary_queue:
            job, calc = secondary_queue.pop(0)
            return (job, calc, False), False
        return None, False
    
    # === INITIAL SETUP: Get both tables started ===
    
    # Start T1 with first panel
    panel_data, _ = get_next_panel_for_table(t1, t1_panel_queue, t2_panel_queue)
    if panel_data:
        job, calc, starts_pour = panel_data
        current_time = _start_panel_on_table(t1, job, calc, starts_pour, current_time, constants, summer_mode, shift_minutes, pour_cutoff)
    
    # Start T2 with first panel  
    panel_data, _ = get_next_panel_for_table(t2, t2_panel_queue, t1_panel_queue)
    if panel_data:
        job, calc, starts_pour = panel_data
        current_time = _start_panel_on_table(t2, job, calc, starts_pour, current_time, constants, summer_mode, shift_minutes, pour_cutoff)
    
    # === MAIN LOOP: Alternate between tables, dynamically assigning panels ===
    
    iteration = 0
    max_iterations = 200
    
    while iteration < max_iterations and current_time < shift_minutes:
        iteration += 1
        
        # Determine which table to process next (whichever has CURE ending first)
        t1_ready = t1.cure_end_time if t1.waiting_for_cure else float('inf')
        t2_ready = t2.cure_end_time if t2.waiting_for_cure else float('inf')
        
        # Check if we're done
        no_work_in_progress = (t1_ready == float('inf') and t2_ready == float('inf'))
        no_panels_left = (not t1.panel_queue and not t2.panel_queue and 
                          not t1_panel_queue and not t2_panel_queue)
        
        if no_work_in_progress and no_panels_left:
            # Nothing in progress and nothing left to schedule
            break
        
        # If neither table has work in progress but we have panels, start one
        if no_work_in_progress and not no_panels_left:
            remaining = shift_minutes - current_time
            if remaining >= pour_cutoff:
                # Try to start a panel on T1
                panel_data, _ = get_next_panel_for_table(t1, t1_panel_queue, t2_panel_queue)
                if panel_data:
                    job, calc, starts_pour = panel_data
                    current_time = _start_panel_on_table(t1, job, calc, starts_pour, current_time, constants, summer_mode, shift_minutes, pour_cutoff)
                continue
            else:
                # Not enough time for POUR - but try to prep panels for tomorrow
                # Per CELL_RULES_SIMPLIFIED: operator can do SETUP+LAYOUT with < 40 min remaining
                if not t1_prep_panel:
                    panel_data, _ = get_next_panel_for_table(t1, t1_panel_queue, t2_panel_queue)
                    if panel_data:
                        job, calc, starts_pour = panel_data
                        if not starts_pour:
                            prep, new_time = _create_prep_panel_for_tomorrow(
                                t1, job, calc, current_time, constants, summer_mode, shift_minutes
                            )
                            if prep:
                                t1_prep_panel = prep
                                current_time = new_time
                
                # Also try T2 if T1 didn't use all time
                remaining = shift_minutes - current_time
                if remaining > 0 and not t2_prep_panel:
                    panel_data, _ = get_next_panel_for_table(t2, t2_panel_queue, t1_panel_queue)
                    if panel_data:
                        job, calc, starts_pour = panel_data
                        if not starts_pour:
                            prep, new_time = _create_prep_panel_for_tomorrow(
                                t2, job, calc, current_time, constants, summer_mode, shift_minutes
                            )
                            if prep:
                                t2_prep_panel = prep
                                current_time = new_time
                
                break
        
        # Process the table that's ready first
        if t1_ready <= t2_ready and t1.waiting_for_cure:
            # Wait for T1 CURE to complete
            if t1.cure_end_time > current_time:
                wait_time = t1.cure_end_time - current_time
                forced_operator_idle += wait_time
                current_time = t1.cure_end_time
            
            # UNLOAD T1
            current_time = _do_unload_dynamic(t1, current_time)
            
            # Check if we have time for another panel
            remaining = shift_minutes - current_time
            if remaining >= pour_cutoff:
                # Get next panel for T1 (T1's queue first, then T2's queue)
                panel_data, from_queue = get_next_panel_for_table(t1, t1_panel_queue, t2_panel_queue)
                if panel_data:
                    job, calc, starts_pour = panel_data
                    old_time = current_time
                    current_time = _start_panel_on_table(t1, job, calc, starts_pour, current_time, constants, summer_mode, shift_minutes, pour_cutoff)
                    if current_time == old_time:
                        # Panel didn't fit - put it back and try prep instead
                        if from_queue:
                            t1.panel_queue.insert(0, (job, calc, starts_pour))
                        else:
                            t1_panel_queue.insert(0, (job, calc))
                        # Fall through to prep logic below
                        remaining = shift_minutes - current_time
            
            # Try prep if we didn't schedule a full panel OR if remaining < pour_cutoff
            # BUT only if the OTHER table doesn't have work in progress (pending UNLOAD)
            if remaining < pour_cutoff and not t1_prep_panel and not t2.waiting_for_cure:
                # Not enough time for POUR, but check if we can do SETUP+LAYOUT for tomorrow
                panel_data, from_queue = get_next_panel_for_table(t1, t1_panel_queue, t2_panel_queue)
                if panel_data:
                    job, calc, starts_pour = panel_data
                    if not starts_pour:  # Don't prep ON_TABLE_TODAY jobs (already prepped)
                        prep, new_time = _create_prep_panel_for_tomorrow(
                            t1, job, calc, current_time, constants, summer_mode, shift_minutes
                        )
                        if prep:
                            t1_prep_panel = prep
                            current_time = new_time
                        else:
                            # Couldn't prep T1 - put panel back and try T2
                            t1_panel_queue.insert(0, (job, calc))
                
                # Also try T2 prep if we have time and haven't prepped it yet
                remaining = shift_minutes - current_time
                if remaining > 0 and not t2_prep_panel:
                    panel_data, from_queue = get_next_panel_for_table(t2, t2_panel_queue, t1_panel_queue)
                    if panel_data:
                        job, calc, starts_pour = panel_data
                        if not starts_pour:
                            prep, new_time = _create_prep_panel_for_tomorrow(
                                t2, job, calc, current_time, constants, summer_mode, shift_minutes
                            )
                            if prep:
                                t2_prep_panel = prep
                                current_time = new_time
                            else:
                                # Couldn't prep - put panel back
                                t2_panel_queue.insert(0, (job, calc))
        
        elif t2.waiting_for_cure:
            # Wait for T2 CURE to complete
            if t2.cure_end_time > current_time:
                wait_time = t2.cure_end_time - current_time
                forced_operator_idle += wait_time
                current_time = t2.cure_end_time
            
            # UNLOAD T2
            current_time = _do_unload_dynamic(t2, current_time)
            
            # Check if we have time for another panel
            remaining = shift_minutes - current_time
            if remaining >= pour_cutoff:
                # Get next panel for T2 (T2's queue first, then T1's queue)
                panel_data, from_queue = get_next_panel_for_table(t2, t2_panel_queue, t1_panel_queue)
                if panel_data:
                    job, calc, starts_pour = panel_data
                    old_time = current_time
                    current_time = _start_panel_on_table(t2, job, calc, starts_pour, current_time, constants, summer_mode, shift_minutes, pour_cutoff)
                    if current_time == old_time:
                        # Panel didn't fit - put it back and try prep instead
                        if from_queue:
                            t2.panel_queue.insert(0, (job, calc, starts_pour))
                        else:
                            t2_panel_queue.insert(0, (job, calc))
                        # Fall through to prep logic below
                        remaining = shift_minutes - current_time
            
            # Try prep if we didn't schedule a full panel OR if remaining < pour_cutoff
            # BUT only if the OTHER table doesn't have work in progress (pending UNLOAD)
            if remaining < pour_cutoff and not t2_prep_panel and not t1.waiting_for_cure:
                # Not enough time for POUR, but check if we can do SETUP+LAYOUT for tomorrow
                panel_data, from_queue = get_next_panel_for_table(t2, t2_panel_queue, t1_panel_queue)
                if panel_data:
                    job, calc, starts_pour = panel_data
                    if not starts_pour:  # Don't prep ON_TABLE_TODAY jobs (already prepped)
                        prep, new_time = _create_prep_panel_for_tomorrow(
                            t2, job, calc, current_time, constants, summer_mode, shift_minutes
                        )
                        if prep:
                            t2_prep_panel = prep
                            current_time = new_time
                        else:
                            # Couldn't prep T2 - put panel back and try T1
                            t2_panel_queue.insert(0, (job, calc))
                
                # Also try T1 prep if we have time and haven't prepped it yet
                remaining = shift_minutes - current_time
                if remaining > 0 and not t1_prep_panel:
                    panel_data, from_queue = get_next_panel_for_table(t1, t1_panel_queue, t2_panel_queue)
                    if panel_data:
                        job, calc, starts_pour = panel_data
                        if not starts_pour:
                            prep, new_time = _create_prep_panel_for_tomorrow(
                                t1, job, calc, current_time, constants, summer_mode, shift_minutes
                            )
                            if prep:
                                t1_prep_panel = prep
                                current_time = new_time
                            else:
                                # Couldn't prep - put panel back
                                t1_panel_queue.insert(0, (job, calc))
    
    # Calculate forced table idle
    forced_table_idle_t1 = 0
    forced_table_idle_t2 = 0
    
    for panel in t1.completed_panels:
        cure = panel.tasks.get("CURE")
        unload = panel.tasks.get("UNLOAD")
        if cure and unload and unload.start_time > cure.end_time:
            forced_table_idle_t1 += unload.start_time - cure.end_time
    
    for panel in t2.completed_panels:
        cure = panel.tasks.get("CURE")
        unload = panel.tasks.get("UNLOAD")
        if cure and unload and unload.start_time > cure.end_time:
            forced_table_idle_t2 += unload.start_time - cure.end_time
    
    # Calculate total operator time
    total_operator_time = 0
    for panel in t1.completed_panels + t2.completed_panels:
        for task_name, task in panel.tasks.items():
            if task.requires_operator and task.duration > 0:
                total_operator_time += task.duration
    
    # Add operator time for prep panels
    if t1_prep_panel:
        total_operator_time += t1_prep_panel.setup_task.duration + t1_prep_panel.layout_task.duration
    if t2_prep_panel:
        total_operator_time += t2_prep_panel.setup_task.duration + t2_prep_panel.layout_task.duration
    
    result.table1_panels = t1.completed_panels
    result.table2_panels = t2.completed_panels
    result.table1_prep = t1_prep_panel
    result.table2_prep = t2_prep_panel
    result.total_panels = len(t1.completed_panels) + len(t2.completed_panels)
    result.total_operator_time = total_operator_time
    result.forced_operator_idle = forced_operator_idle
    result.forced_table_idle = {
        f"{cell_color}_1": forced_table_idle_t1,
        f"{cell_color}_2": forced_table_idle_t2
    }
    result.status = "OPTIMAL" if result.total_panels > 0 else "INFEASIBLE"
    
    return result


@dataclass
class _DynamicTableState:
    """State for a table during dynamic scheduling."""
    table_id: str
    panel_queue: list = field(default_factory=list)  # [(job, calc, starts_with_pour)]
    completed_panels: list = field(default_factory=list)
    current_panel: Optional[ScheduledPanel] = None
    cure_end_time: int = 0
    waiting_for_cure: bool = False
    last_fixture: Optional[str] = None
    panel_index: int = 0


def _start_panel_on_table(
    table: _DynamicTableState,
    job: Job,
    calc: CalculatedFields,
    starts_with_pour: bool,
    current_time: int,
    constants: CycleTimeConstants,
    summer_mode: bool,
    shift_minutes: int,
    pour_cutoff: int
) -> int:
    """Start a panel on a table (SETUP → LAYOUT → POUR → CURE starts).
    
    Returns the time after POUR (CURE is running).
    """
    # Calculate durations
    needs_setup = table.last_fixture != calc.fixture_id
    timing = constants.get_task_timing(job.wire_diameter, job.equivalent)
    
    setup_dur = timing.setup if needs_setup else 0
    layout_dur = timing.layout
    pour_dur = int(timing.pour * job.molds)
    cure_dur = int(timing.cure * (1.5 if summer_mode else 1.0))
    
    # Check if we have enough time for this panel
    # We need time for the panel tasks through UNLOAD
    unload_dur = 5  # Standard unload time
    if starts_with_pour:
        time_needed = pour_dur + cure_dur + unload_dur
    else:
        time_needed = setup_dur + layout_dur + pour_dur + cure_dur + unload_dur
    
    # Don't start if we can't complete everything before shift ends
    if current_time + time_needed > shift_minutes:
        return current_time
    
    # Create panel
    panel = ScheduledPanel(
        table_id=table.table_id,
        panel_index=table.panel_index,
        job_id=job.job_id
    )
    
    if starts_with_pour:
        # Skip SETUP and LAYOUT (already done yesterday)
        panel.tasks["SETUP"] = ScheduledTask("SETUP", current_time, current_time, 0, True)
        panel.tasks["LAYOUT"] = ScheduledTask("LAYOUT", current_time, current_time, 0, True)
    else:
        # SETUP
        setup_end = current_time + setup_dur
        panel.tasks["SETUP"] = ScheduledTask("SETUP", current_time, setup_end, setup_dur, True)
        current_time = setup_end
        
        # LAYOUT
        layout_end = current_time + layout_dur
        panel.tasks["LAYOUT"] = ScheduledTask("LAYOUT", current_time, layout_end, layout_dur, True)
        current_time = layout_end
    
    # POUR
    pour_end = current_time + pour_dur
    panel.tasks["POUR"] = ScheduledTask("POUR", current_time, pour_end, pour_dur, True)
    current_time = pour_end
    
    # CURE starts (no operator)
    cure_end = current_time + cure_dur
    panel.tasks["CURE"] = ScheduledTask("CURE", current_time, cure_end, cure_dur, False)
    
    # Update table state
    table.current_panel = panel
    table.cure_end_time = cure_end
    table.waiting_for_cure = True
    table.last_fixture = calc.fixture_id
    table.panel_index += 1
    
    return current_time


def _do_unload_dynamic(table: _DynamicTableState, current_time: int) -> int:
    """Do UNLOAD and complete the current panel.
    
    Returns time after UNLOAD.
    """
    if not table.current_panel:
        return current_time
    
    panel = table.current_panel
    
    # Standard unload time
    unload_dur = 5  # TODO: Get from constants
    unload_end = current_time + unload_dur
    
    panel.tasks["UNLOAD"] = ScheduledTask("UNLOAD", current_time, unload_end, unload_dur, True)
    
    # Complete panel
    table.completed_panels.append(panel)
    table.current_panel = None
    table.waiting_for_cure = False
    
    return unload_end


def _work_table_to_cure(
    table: TableState,
    current_time: int,
    constants: CycleTimeConstants,
    summer_mode: bool,
    starts_with_pour: bool,
    shift_minutes: int,
    pour_cutoff: int
) -> int:
    """Work a table from current state up to CURE (POUR complete).
    
    Does SETUP (if needed) → LAYOUT → POUR, then CURE starts.
    Returns the time after POUR completes (CURE is running).
    """
    if table.is_done:
        return current_time
    
    assignment = table.current_assignment
    if not assignment:
        return current_time
    
    # Calculate task times
    needs_setup = table.needs_setup() and not starts_with_pour
    times = calculate_task_times(
        assignment.job, assignment.calc, constants, summer_mode, needs_setup
    )
    
    # Store times for later UNLOAD
    table.current_times = times
    
    # Check if we have enough time for POUR
    if starts_with_pour:
        # Only need POUR time
        time_to_pour = times.pour
    else:
        # Need SETUP + LAYOUT + POUR
        time_to_pour = times.setup + times.layout + times.pour
    
    remaining = shift_minutes - current_time
    if remaining < pour_cutoff:
        # Not enough time to start POUR
        return current_time
    
    # Initialize panel
    table.current_panel_tasks = {}
    panel_start = current_time
    
    if starts_with_pour:
        # SETUP and LAYOUT already done (ON_TABLE_TODAY)
        table.current_panel_tasks["SETUP"] = ScheduledTask(
            task_name="SETUP", start_time=0, end_time=0, duration=0, requires_operator=True
        )
        table.current_panel_tasks["LAYOUT"] = ScheduledTask(
            task_name="LAYOUT", start_time=0, end_time=0, duration=0, requires_operator=True
        )
    else:
        # Do SETUP
        setup_start = current_time
        setup_end = current_time + times.setup
        table.current_panel_tasks["SETUP"] = ScheduledTask(
            task_name="SETUP",
            start_time=setup_start,
            end_time=setup_end,
            duration=times.setup,
            requires_operator=True
        )
        current_time = setup_end
        
        # Do LAYOUT
        layout_start = current_time
        layout_end = current_time + times.layout
        table.current_panel_tasks["LAYOUT"] = ScheduledTask(
            task_name="LAYOUT",
            start_time=layout_start,
            end_time=layout_end,
            duration=times.layout,
            requires_operator=True
        )
        current_time = layout_end
    
    # Do POUR
    pour_start = current_time
    pour_end = current_time + times.pour
    table.current_panel_tasks["POUR"] = ScheduledTask(
        task_name="POUR",
        start_time=pour_start,
        end_time=pour_end,
        duration=times.pour,
        requires_operator=True
    )
    current_time = pour_end
    
    # Start CURE (no operator needed)
    cure_start = current_time
    cure_end = current_time + times.cure
    table.current_panel_tasks["CURE"] = ScheduledTask(
        task_name="CURE",
        start_time=cure_start,
        end_time=cure_end,
        duration=times.cure,
        requires_operator=False
    )
    
    # Update table state
    table.current_task = TaskType.CURE
    table.cure_end_time = cure_end
    table.last_fixture = assignment.job.fixture_id
    
    # Store times for UNLOAD (will be set when we return to this table)
    table.task_start_time = current_time  # When CURE started
    
    return current_time


def _do_pour_and_start_cure(
    table: TableState,
    current_time: int,
    constants: CycleTimeConstants,
    summer_mode: bool
) -> int:
    """Do POUR on a table that already has LAYOUT done (ON_TABLE_TODAY starts_with_pour).
    
    Returns time after POUR completes.
    """
    if table.is_done:
        return current_time
    
    assignment = table.current_assignment
    if not assignment:
        return current_time
    
    times = calculate_task_times(
        assignment.job, assignment.calc, constants, summer_mode, False
    )
    
    # Store times for later UNLOAD
    table.current_times = times
    
    # Initialize panel - SETUP and LAYOUT already done
    table.current_panel_tasks = {}
    table.current_panel_tasks["SETUP"] = ScheduledTask(
        task_name="SETUP", start_time=0, end_time=0, duration=0, requires_operator=True
    )
    table.current_panel_tasks["LAYOUT"] = ScheduledTask(
        task_name="LAYOUT", start_time=0, end_time=0, duration=0, requires_operator=True
    )
    
    # Do POUR
    pour_start = current_time
    pour_end = current_time + times.pour
    table.current_panel_tasks["POUR"] = ScheduledTask(
        task_name="POUR",
        start_time=pour_start,
        end_time=pour_end,
        duration=times.pour,
        requires_operator=True
    )
    current_time = pour_end
    
    # Start CURE
    cure_start = current_time
    cure_end = current_time + times.cure
    table.current_panel_tasks["CURE"] = ScheduledTask(
        task_name="CURE",
        start_time=cure_start,
        end_time=cure_end,
        duration=times.cure,
        requires_operator=False
    )
    
    table.current_task = TaskType.CURE
    table.cure_end_time = cure_end
    table.last_fixture = assignment.job.fixture_id
    
    return current_time


def _do_unload(table: TableState, current_time: int) -> int:
    """Do UNLOAD task on a table after CURE is complete.
    
    Returns time after UNLOAD completes.
    """
    if not table.current_assignment:
        return current_time
    
    # Get UNLOAD duration from stored task times
    unload_duration = 5  # Default fallback
    if table.current_times:
        unload_duration = table.current_times.unload
    
    unload_start = current_time
    unload_end = current_time + unload_duration
    
    table.current_panel_tasks["UNLOAD"] = ScheduledTask(
        task_name="UNLOAD",
        start_time=unload_start,
        end_time=unload_end,
        duration=unload_duration,
        requires_operator=True
    )
    
    table.current_task = TaskType.UNLOAD
    table.cure_end_time = None
    
    return unload_end


def _finalize_panel(table: TableState) -> None:
    """Finalize current panel and advance to next."""
    if not table.current_panel_tasks:
        return
    
    assignment = table.current_assignment
    if not assignment:
        return
    
    # Create completed panel
    panel = ScheduledPanel(
        table_id=table.table_id,
        panel_index=table.total_panels_done,
        job_id=assignment.job.job_id,
        tasks=dict(table.current_panel_tasks)
    )
    
    table.completed_panels.append(panel)
    table.total_panels_done += 1
    table.current_panel_in_job += 1
    
    # Check if job is complete
    if table.current_panel_in_job >= assignment.panels_to_schedule:
        # Move to next job
        table.current_job_idx += 1
        table.current_panel_in_job = 0
    
    # Reset panel state
    table.current_panel_tasks = {}
    table.current_task = None
    table.cure_end_time = None
    table.current_times = None


def _create_prep_panel_for_tomorrow(
    table: _DynamicTableState,
    job: Job,
    calc: CalculatedFields,
    current_time: int,
    constants: CycleTimeConstants,
    summer_mode: bool,
    shift_minutes: int
) -> tuple[Optional[EndOfDayPrepPanel], int]:
    """Create end-of-day prep panel (SETUP+LAYOUT only, no POUR).
    
    Per CELL_RULES_SIMPLIFIED: When < 40 min remaining, operator CAN do SETUP+LAYOUT
    on a table to prepare it for tomorrow. This panel will be ON_TABLE_TODAY tomorrow.
    
    Args:
        table: The table state
        job: Job to prep
        calc: Calculated fields
        current_time: Current time in shift
        constants: Timing constants
        summer_mode: Whether summer mode is active
        shift_minutes: Total shift minutes
        
    Returns:
        Tuple of (EndOfDayPrepPanel or None, time after LAYOUT completes)
    """
    # Check if we need SETUP (different fixture)
    needs_setup = job.fixture_id != table.last_fixture
    
    # Calculate times
    timing = constants.get_task_timing(job.wire_diameter, job.equivalent)
    setup_time = timing.setup if needs_setup else 0
    layout_time = timing.layout
    
    # Check if we have time for SETUP + LAYOUT
    remaining = shift_minutes - current_time
    required_time = setup_time + layout_time
    
    if remaining < required_time:
        # Not enough time even for prep
        return None, current_time
    
    # Do SETUP
    setup_start = current_time
    setup_end = current_time + setup_time
    setup_task = ScheduledTask(
        task_name="SETUP",
        start_time=setup_start,
        end_time=setup_end,
        duration=setup_time,
        requires_operator=True
    )
    current_time = setup_end
    
    # Do LAYOUT
    layout_start = current_time
    layout_end = current_time + layout_time
    layout_task = ScheduledTask(
        task_name="LAYOUT",
        start_time=layout_start,
        end_time=layout_end,
        duration=layout_time,
        requires_operator=True
    )
    current_time = layout_end
    
    # Update table's last fixture
    table.last_fixture = job.fixture_id
    
    # Create prep panel
    prep_panel = EndOfDayPrepPanel(
        table_id=table.table_id,
        job_id=job.job_id,
        job=job,
        calc=calc,
        setup_task=setup_task,
        layout_task=layout_task
    )
    
    return prep_panel, current_time
