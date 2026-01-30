# Solution parser for extracting and formatting schedule results.
# Version: 1.0.0
# Converts solver output to structured data and generates summaries.

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .scheduler import CellScheduleResult, ScheduledPanel, ScheduledTask
from .constraints import TASK_SEQUENCE


@dataclass
class GanttTask:
    """A task formatted for Gantt chart display.
    
    Attributes:
        resource: Resource name (table or operator).
        task_type: Type of task (SETUP, LAYOUT, etc.).
        job_id: Job identifier.
        panel_index: Panel number.
        start: Start time in minutes.
        end: End time in minutes.
        color: Color for display.
    """
    resource: str
    task_type: str
    job_id: str
    panel_index: int
    start: int
    end: int
    color: str = ""
    
    @property
    def duration(self) -> int:
        """Task duration in minutes."""
        return self.end - self.start


@dataclass
class GanttData:
    """Data structure for Gantt chart generation.
    
    Attributes:
        cell_color: Cell identifier.
        shift_minutes: Total shift duration.
        tasks: List of GanttTask items.
        resources: Ordered list of resource names.
    """
    cell_color: str
    shift_minutes: int
    tasks: list[GanttTask] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)


# Task colors for Gantt display
TASK_COLORS = {
    "SETUP": "#4CAF50",      # Green
    "LAYOUT": "#2196F3",     # Blue
    "POUR": "#FF9800",       # Orange
    "CURE": "#9E9E9E",       # Gray (no operator)
    "UNLOAD": "#E91E63",     # Pink
    "IDLE": "#FFEB3B",       # Yellow
}


def extract_gantt_data(result: CellScheduleResult) -> GanttData:
    """Extract Gantt chart data from a cell schedule result.
    
    Creates tasks for both tables and the operator, showing when
    each resource is active and with what task.
    
    Args:
        result: CellScheduleResult from the scheduler.
    
    Returns:
        GanttData ready for chart generation.
    """
    table1_id = f"{result.cell_color}_1"
    table2_id = f"{result.cell_color}_2"
    operator_id = f"{result.cell_color}_OPERATOR"
    
    gantt = GanttData(
        cell_color=result.cell_color,
        shift_minutes=result.shift_minutes,
        resources=[table1_id, table2_id, operator_id]
    )
    
    # Add table 1 tasks
    for panel in result.table1_panels:
        _add_panel_tasks(gantt, panel, table1_id, operator_id)
    
    # Add table 2 tasks
    for panel in result.table2_panels:
        _add_panel_tasks(gantt, panel, table2_id, operator_id)
    
    # Sort tasks by start time
    gantt.tasks.sort(key=lambda t: (t.resource, t.start))
    
    return gantt


def _add_panel_tasks(
    gantt: GanttData,
    panel: ScheduledPanel,
    table_id: str,
    operator_id: str
) -> None:
    """Add tasks from a panel to the Gantt data.
    
    Args:
        gantt: GanttData to add tasks to.
        panel: ScheduledPanel with task times.
        table_id: Table resource identifier.
        operator_id: Operator resource identifier.
    """
    for task_name in TASK_SEQUENCE:
        task = panel.tasks.get(task_name)
        if task is None or task.duration == 0:
            continue
        
        # Add to table resource
        gantt.tasks.append(GanttTask(
            resource=table_id,
            task_type=task_name,
            job_id=panel.job_id,
            panel_index=panel.panel_index,
            start=task.start_time,
            end=task.end_time,
            color=TASK_COLORS.get(task_name, "#CCCCCC")
        ))
        
        # Add to operator resource (except CURE)
        if task.requires_operator:
            gantt.tasks.append(GanttTask(
                resource=operator_id,
                task_type=task_name,
                job_id=panel.job_id,
                panel_index=panel.panel_index,
                start=task.start_time,
                end=task.end_time,
                color=TASK_COLORS.get(task_name, "#CCCCCC")
            ))


def generate_text_gantt(gantt: GanttData, width: int = 80) -> str:
    """Generate a simple text-based Gantt chart.
    
    Args:
        gantt: GanttData with tasks.
        width: Character width for the time axis.
    
    Returns:
        Multi-line string with ASCII Gantt chart.
    """
    lines = []
    lines.append(f"=== {gantt.cell_color} Cell Schedule ===")
    lines.append(f"Shift: {gantt.shift_minutes} minutes")
    lines.append("")
    
    # Calculate scale
    chars_per_minute = width / gantt.shift_minutes
    
    # Generate time axis
    time_marks = list(range(0, gantt.shift_minutes + 1, 60))
    time_axis = "Time: "
    for mark in time_marks:
        pos = int(mark * chars_per_minute)
        time_axis = time_axis[:pos + 6] + f"{mark:>3}" + time_axis[pos + 9:]
    lines.append(time_axis[:width + 10])
    lines.append("      " + "-" * width)
    
    # Generate resource rows
    for resource in gantt.resources:
        resource_tasks = [t for t in gantt.tasks if t.resource == resource]
        
        # Create empty row
        row = [" "] * width
        
        # Fill in tasks
        for task in resource_tasks:
            start_pos = int(task.start * chars_per_minute)
            end_pos = int(task.end * chars_per_minute)
            
            # Use first letter of task type
            char = task.task_type[0]
            for i in range(start_pos, min(end_pos, width)):
                row[i] = char
        
        # Format resource name
        name = resource[-8:].ljust(6)  # Last 8 chars, padded
        lines.append(f"{name}|{''.join(row)}|")
    
    lines.append("      " + "-" * width)
    lines.append("")
    lines.append("Legend: S=SETUP L=LAYOUT P=POUR C=CURE U=UNLOAD")
    
    return "\n".join(lines)


def generate_schedule_summary(result: CellScheduleResult) -> str:
    """Generate a text summary of the schedule.
    
    Args:
        result: CellScheduleResult to summarize.
    
    Returns:
        Multi-line string with schedule summary.
    """
    lines = []
    lines.append(f"=== {result.cell_color} Cell Schedule Summary ===")
    lines.append(f"Status: {result.status}")
    lines.append(f"Solve time: {result.solve_time_seconds:.3f}s")
    lines.append("")
    
    if not result.is_feasible:
        lines.append("No feasible schedule found.")
        return "\n".join(lines)
    
    lines.append(f"Total panels scheduled: {result.total_panels}")
    lines.append(f"  Table 1: {len(result.table1_panels)} panels")
    lines.append(f"  Table 2: {len(result.table2_panels)} panels")
    lines.append("")
    
    lines.append(f"Operator time: {result.total_operator_time} minutes")
    lines.append(f"Forced operator idle: {result.forced_operator_idle} minutes")
    
    table1_id = f"{result.cell_color}_1"
    table2_id = f"{result.cell_color}_2"
    lines.append(f"Forced table idle:")
    lines.append(f"  {table1_id}: {result.forced_table_idle.get(table1_id, 0)} minutes")
    lines.append(f"  {table2_id}: {result.forced_table_idle.get(table2_id, 0)} minutes")
    lines.append("")
    
    # Panel details
    lines.append("--- Table 1 Panels ---")
    for panel in result.table1_panels:
        lines.append(_format_panel_line(panel))
    
    lines.append("")
    lines.append("--- Table 2 Panels ---")
    for panel in result.table2_panels:
        lines.append(_format_panel_line(panel))
    
    return "\n".join(lines)


def _format_panel_line(panel: ScheduledPanel) -> str:
    """Format a single panel as a summary line.
    
    Args:
        panel: ScheduledPanel to format.
    
    Returns:
        Single line string with panel summary.
    """
    tasks_str = " → ".join(
        f"{t.task_name}({t.start_time}-{t.end_time})"
        for t in [panel.tasks.get(name) for name in TASK_SEQUENCE]
        if t is not None and t.duration > 0
    )
    return f"  Panel {panel.panel_index}: Job {panel.job_id} | {tasks_str}"


def generate_detailed_timeline(result: CellScheduleResult) -> list[dict]:
    """Generate a detailed timeline of all events.
    
    Args:
        result: CellScheduleResult to process.
    
    Returns:
        List of event dictionaries sorted by time.
    """
    events = []
    
    for panel in result.get_all_panels():
        for task_name in TASK_SEQUENCE:
            task = panel.tasks.get(task_name)
            if task is None or task.duration == 0:
                continue
            
            events.append({
                "time": task.start_time,
                "event": "START",
                "table": panel.table_id,
                "task": task_name,
                "job": panel.job_id,
                "panel": panel.panel_index,
                "operator": task.requires_operator
            })
            
            events.append({
                "time": task.end_time,
                "event": "END",
                "table": panel.table_id,
                "task": task_name,
                "job": panel.job_id,
                "panel": panel.panel_index,
                "operator": task.requires_operator
            })
    
    # Sort by time, then by event type (END before START at same time)
    events.sort(key=lambda e: (e["time"], 0 if e["event"] == "END" else 1))
    
    return events


def validate_schedule(result: CellScheduleResult) -> list[str]:
    """Validate that the schedule doesn't violate constraints.
    
    Checks:
    1. Task sequence is correct (SETUP → LAYOUT → POUR → CURE → UNLOAD)
    2. Operator is never at two places at once
    3. All tasks complete within shift
    4. POUR doesn't start with <40 min remaining
    
    Args:
        result: CellScheduleResult to validate.
    
    Returns:
        List of violation messages (empty if valid).
    """
    violations = []
    
    if not result.is_feasible:
        return ["No feasible schedule to validate"]
    
    # Check task sequence within each panel
    for panel in result.get_all_panels():
        prev_end = 0
        for task_name in TASK_SEQUENCE:
            task = panel.tasks.get(task_name)
            if task is None:
                continue
            
            if task.start_time < prev_end:
                violations.append(
                    f"{panel.table_id} Panel {panel.panel_index}: "
                    f"{task_name} starts at {task.start_time} but previous task "
                    f"ends at {prev_end}"
                )
            prev_end = task.end_time
    
    # Check operator not in two places at once
    operator_tasks = []
    for panel in result.get_all_panels():
        for task_name in ("SETUP", "LAYOUT", "POUR", "UNLOAD"):
            task = panel.tasks.get(task_name)
            if task and task.duration > 0:
                operator_tasks.append({
                    "start": task.start_time,
                    "end": task.end_time,
                    "table": panel.table_id,
                    "task": task_name
                })
    
    operator_tasks.sort(key=lambda t: t["start"])
    
    for i in range(len(operator_tasks) - 1):
        current = operator_tasks[i]
        next_task = operator_tasks[i + 1]
        
        if current["end"] > next_task["start"]:
            violations.append(
                f"Operator overlap: {current['table']} {current['task']} "
                f"({current['start']}-{current['end']}) overlaps with "
                f"{next_task['table']} {next_task['task']} "
                f"({next_task['start']}-{next_task['end']})"
            )
    
    # Check all tasks within shift
    for panel in result.get_all_panels():
        for task_name, task in panel.tasks.items():
            if task.end_time > result.shift_minutes:
                violations.append(
                    f"{panel.table_id} Panel {panel.panel_index}: "
                    f"{task_name} ends at {task.end_time} but shift is "
                    f"{result.shift_minutes} minutes"
                )
    
    # Check POUR cutoff (40 min before shift end)
    cutoff = result.shift_minutes - 40
    for panel in result.get_all_panels():
        pour = panel.tasks.get("POUR")
        if pour and pour.start_time > cutoff:
            violations.append(
                f"{panel.table_id} Panel {panel.panel_index}: "
                f"POUR starts at {pour.start_time} but cutoff is {cutoff}"
            )
    
    return violations


def export_schedule_to_dict(result: CellScheduleResult) -> dict:
    """Export schedule to a dictionary for JSON serialization.
    
    Args:
        result: CellScheduleResult to export.
    
    Returns:
        Dictionary with complete schedule data.
    """
    return {
        "cell_color": result.cell_color,
        "shift_minutes": result.shift_minutes,
        "status": result.status,
        "is_feasible": result.is_feasible,
        "total_panels": result.total_panels,
        "total_operator_time": result.total_operator_time,
        "forced_operator_idle": result.forced_operator_idle,
        "forced_table_idle": result.forced_table_idle,
        "solve_time_seconds": result.solve_time_seconds,
        "table1_panels": [
            _export_panel(p) for p in result.table1_panels
        ],
        "table2_panels": [
            _export_panel(p) for p in result.table2_panels
        ]
    }


def _export_panel(panel: ScheduledPanel) -> dict:
    """Export a panel to dictionary format.
    
    Args:
        panel: ScheduledPanel to export.
    
    Returns:
        Dictionary with panel data.
    """
    return {
        "table_id": panel.table_id,
        "panel_index": panel.panel_index,
        "job_id": panel.job_id,
        "start_time": panel.start_time,
        "end_time": panel.end_time,
        "operator_time": panel.operator_time,
        "cure_time": panel.cure_time,
        "tasks": {
            name: {
                "start": task.start_time,
                "end": task.end_time,
                "duration": task.duration
            }
            for name, task in panel.tasks.items()
        }
    }
