# Calculate derived fields for jobs in the scheduling engine.
# Version: 1.0.0
# Computes SCHED_QTY, BUILD_LOAD, BUILD_DATE, PRIORITY, MOLD_DEPTH, SCHED_CLASS.

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil
from typing import Literal

from .constants import CycleTimeConstants, MoldDepth, SchedClass
from .data_loader import Job, DailyProductionLoad


# Priority levels
PRIORITY_PAST_DUE = 0      # Past due OR (today + expedite)
PRIORITY_TODAY = 1         # BUILD_DATE equals TODAY
PRIORITY_EXPEDITE = 2      # Future + expedite
PRIORITY_FUTURE = 3        # Future, no expedite

# SCHED_CLASS constants
SCHED_CLASS_A: SchedClass = "A"
SCHED_CLASS_B: SchedClass = "B"
SCHED_CLASS_C: SchedClass = "C"
SCHED_CLASS_D: SchedClass = "D"
SCHED_CLASS_E: SchedClass = "E"


@dataclass
class CalculatedFields:
    """Calculated fields for a single job.
    
    These fields are derived from the job's raw data and the cycle time constants.
    They are used by the scheduling algorithms to determine priority and capacity.
    
    Attributes:
        job_id: Reference to the job these calculations belong to.
        sched_qty: Quantity to schedule (PROD_QTY or JOB_QUANTITY_REMAINING).
        build_load: Estimated shifts to complete (SCHED_QTY × EQUIVALENT ÷ SCHED_CONSTANT).
        build_date: Target build date (REQ_BY minus lead time in business days).
        priority: Scheduling priority (0=past due, 1=today, 2=expedite, 3=future).
        fixture_id: Fixture identifier (PATTERN-OPENING_SIZE-WIRE_DIAMETER).
        mold_depth: Mold depth requirement (DEEP or STD).
        sched_class: Scheduling class from TASK sheet (A, B, C, D, or E).
        pull_ahead: Days pulled ahead for this job's class.
        sched_constant: Scheduling constant used in BUILD_LOAD calculation.
    """
    job_id: str
    sched_qty: int
    build_load: float
    build_date: date
    priority: int
    fixture_id: str
    mold_depth: MoldDepth
    sched_class: SchedClass
    pull_ahead: float
    sched_constant: int
    
    @property
    def is_past_due(self) -> bool:
        """Check if job is past due (priority 0)."""
        return self.priority == PRIORITY_PAST_DUE
    
    @property
    def is_due_today(self) -> bool:
        """Check if job is due today (priority 0 or 1)."""
        return self.priority <= PRIORITY_TODAY
    
    @property
    def priority_label(self) -> str:
        """Get human-readable priority label."""
        labels = {
            PRIORITY_PAST_DUE: "Past Due",
            PRIORITY_TODAY: "Due Today",
            PRIORITY_EXPEDITE: "Expedite",
            PRIORITY_FUTURE: "Future"
        }
        return labels.get(self.priority, f"Priority {self.priority}")


@dataclass
class JobWithCalculations:
    """Combines a Job with its calculated fields for convenience.
    
    Attributes:
        job: Original Job object.
        calc: Calculated fields for the job.
    """
    job: Job
    calc: CalculatedFields
    
    def __getattr__(self, name: str):
        """Allow accessing job attributes directly."""
        return getattr(self.job, name)


def calculate_fields_for_job(
    job: Job,
    constants: CycleTimeConstants,
    today: date
) -> CalculatedFields:
    """Calculate all derived fields for a single job.
    
    Args:
        job: Job to calculate fields for.
        constants: CycleTimeConstants for lookups.
        today: Current schedule date (for priority calculation).
    
    Returns:
        CalculatedFields with all derived values.
    """
    # Get task timing for this job's wire diameter and equivalent
    timing = constants.get_task_timing(job.wire_diameter, job.equivalent)
    
    # SCHED_QTY: Use remaining quantity if on table, otherwise full quantity
    sched_qty = (
        job.job_quantity_remaining 
        if job.on_table_today is not None and job.job_quantity_remaining is not None
        else job.prod_qty
    )
    
    # BUILD_LOAD: Estimated shifts required
    # Formula: SCHED_QTY × EQUIVALENT ÷ SCHED_CONSTANT
    build_load = (sched_qty * job.equivalent) / timing.sched_constant
    
    # BUILD_DATE: REQ_BY minus ROUNDUP(BUILD_LOAD + PULL_AHEAD) business days
    lead_time_days = ceil(build_load + timing.pull_ahead)
    build_date = subtract_business_days(job.req_by, lead_time_days, constants)
    
    # PRIORITY: Based on BUILD_DATE vs today and EXPEDITE flag
    priority = calculate_priority(build_date, today, job.expedite)
    
    # FIXTURE_ID: Already computed by job property
    fixture_id = job.fixture_id
    
    # MOLD_DEPTH: DEEP if wire >= 8, else STD
    mold_depth = constants.get_mold_depth(job.wire_diameter)
    
    # SCHED_CLASS: From task timing lookup
    sched_class = timing.sched_class
    
    return CalculatedFields(
        job_id=job.job_id,
        sched_qty=sched_qty,
        build_load=round(build_load, 2),
        build_date=build_date,
        priority=priority,
        fixture_id=fixture_id,
        mold_depth=mold_depth,
        sched_class=sched_class,
        pull_ahead=timing.pull_ahead,
        sched_constant=timing.sched_constant
    )


def calculate_all_fields(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    today: date
) -> dict[str, CalculatedFields]:
    """Calculate derived fields for all jobs in a production load.
    
    Args:
        load: DailyProductionLoad with jobs to process.
        constants: CycleTimeConstants for lookups.
        today: Current schedule date.
    
    Returns:
        Dictionary mapping job_id to CalculatedFields.
    """
    results = {}
    for job in load.jobs:
        results[job.job_id] = calculate_fields_for_job(job, constants, today)
    return results


def get_jobs_with_calculations(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    today: date
) -> list[JobWithCalculations]:
    """Get jobs combined with their calculated fields.
    
    Args:
        load: DailyProductionLoad with jobs to process.
        constants: CycleTimeConstants for lookups.
        today: Current schedule date.
    
    Returns:
        List of JobWithCalculations sorted by priority then build_date.
    """
    results = []
    for job in load.jobs:
        calc = calculate_fields_for_job(job, constants, today)
        results.append(JobWithCalculations(job=job, calc=calc))
    
    # Sort by priority (ascending), then by build_date (ascending)
    results.sort(key=lambda x: (x.calc.priority, x.calc.build_date))
    return results


def calculate_priority(build_date: date, today: date, expedite: bool) -> int:
    """Calculate scheduling priority for a job.
    
    Priority levels:
    - 0: Past due (BUILD_DATE < today) OR (BUILD_DATE == today AND expedite)
    - 1: Due today (BUILD_DATE == today, no expedite)
    - 2: Future with expedite (BUILD_DATE > today AND expedite)
    - 3: Future (BUILD_DATE > today, no expedite)
    
    Args:
        build_date: Calculated build date for the job.
        today: Current schedule date.
        expedite: Whether job is marked for expedite.
    
    Returns:
        Priority level (0-3, lower is higher priority).
    """
    if build_date < today:
        # Past due - always priority 0
        return PRIORITY_PAST_DUE
    elif build_date == today:
        if expedite:
            # Due today with expedite - priority 0
            return PRIORITY_PAST_DUE
        else:
            # Due today, no expedite - priority 1
            return PRIORITY_TODAY
    else:
        # Future
        if expedite:
            return PRIORITY_EXPEDITE
        else:
            return PRIORITY_FUTURE


def subtract_business_days(
    from_date: date,
    days: int,
    constants: CycleTimeConstants
) -> date:
    """Subtract business days from a date, skipping weekends and holidays.
    
    Args:
        from_date: Starting date.
        days: Number of business days to subtract.
        constants: CycleTimeConstants containing holiday list.
    
    Returns:
        Resulting date after subtracting business days.
    """
    if days <= 0:
        return from_date
    
    result = from_date
    remaining = days
    
    while remaining > 0:
        result = result - timedelta(days=1)
        
        # Skip weekends (Saturday=5, Sunday=6)
        if result.weekday() > 4:
            continue
        
        # Skip holidays
        if result in constants.holidays:
            continue
        
        remaining -= 1
    
    return result


def add_business_days(
    from_date: date,
    days: int,
    constants: CycleTimeConstants
) -> date:
    """Add business days to a date, skipping weekends and holidays.
    
    Args:
        from_date: Starting date.
        days: Number of business days to add.
        constants: CycleTimeConstants containing holiday list.
    
    Returns:
        Resulting date after adding business days.
    """
    if days <= 0:
        return from_date
    
    result = from_date
    remaining = days
    
    while remaining > 0:
        result = result + timedelta(days=1)
        
        # Skip weekends
        if result.weekday() > 4:
            continue
        
        # Skip holidays
        if result in constants.holidays:
            continue
        
        remaining -= 1
    
    return result


def count_business_days_between(
    start_date: date,
    end_date: date,
    constants: CycleTimeConstants
) -> int:
    """Count business days between two dates (exclusive of end_date).
    
    Args:
        start_date: Start date.
        end_date: End date.
        constants: CycleTimeConstants containing holiday list.
    
    Returns:
        Number of business days between the dates.
    """
    if start_date >= end_date:
        return 0
    
    count = 0
    current = start_date
    
    while current < end_date:
        current = current + timedelta(days=1)
        if current >= end_date:
            break
        
        # Count if weekday and not holiday
        if current.weekday() <= 4 and current not in constants.holidays:
            count += 1
    
    return count


def get_priority_summary(
    calculations: dict[str, CalculatedFields]
) -> dict[int, list[str]]:
    """Group job IDs by priority level.
    
    Args:
        calculations: Dictionary of job_id to CalculatedFields.
    
    Returns:
        Dictionary mapping priority level to list of job IDs.
    """
    summary: dict[int, list[str]] = {
        PRIORITY_PAST_DUE: [],
        PRIORITY_TODAY: [],
        PRIORITY_EXPEDITE: [],
        PRIORITY_FUTURE: []
    }
    
    for job_id, calc in calculations.items():
        if calc.priority in summary:
            summary[calc.priority].append(job_id)
    
    return summary


def get_sched_class_summary(
    calculations: dict[str, CalculatedFields]
) -> dict[str, list[str]]:
    """Group job IDs by scheduling class.
    
    Args:
        calculations: Dictionary of job_id to CalculatedFields.
    
    Returns:
        Dictionary mapping SCHED_CLASS to list of job IDs.
    """
    summary: dict[str, list[str]] = {"A": [], "B": [], "C": [], "D": [], "E": []}
    
    for job_id, calc in calculations.items():
        if calc.sched_class in summary:
            summary[calc.sched_class].append(job_id)
    
    return summary


def export_calculations_to_dict(
    job: Job,
    calc: CalculatedFields
) -> dict:
    """Export job and calculations to a flat dictionary for Excel output.
    
    Args:
        job: Original Job object.
        calc: Calculated fields for the job.
    
    Returns:
        Dictionary with all job fields plus calculated fields.
    """
    return {
        # Original job fields
        "REQ_BY": job.req_by,
        "JOB": job.job_id,
        "DESCRIPTION": job.description,
        "PATTERN": job.pattern,
        "OPENING_SIZE": job.opening_size,
        "WIRE_DIAMETER": job.wire_diameter,
        "MOLDS": job.molds,
        "MOLD_TYPE": job.mold_type,
        "PROD_QTY": job.prod_qty,
        "EQUIVALENT": job.equivalent,
        "ORANGE_ELIGIBLE": job.orange_eligible,
        # Operator inputs
        "ON_TABLE_TODAY": job.on_table_today or "",
        "JOB_QUANTITY_REMAINING": job.job_quantity_remaining or "",
        "EXPEDITE": job.expedite,
        # Calculated fields
        "SCHED_QTY": calc.sched_qty,
        "BUILD_LOAD": calc.build_load,
        "BUILD_DATE": calc.build_date,
        "PRIORITY": calc.priority,
        "PRIORITY_LABEL": calc.priority_label,
        "FIXTURE": calc.fixture_id,
        "MOLD_DEPTH": calc.mold_depth,
        "SCHED_CLASS": calc.sched_class,
        "SCHED_CONSTANT": calc.sched_constant,
        "PULL_AHEAD": calc.pull_ahead
    }


def export_all_to_dataframe(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    today: date
):
    """Export all jobs with calculations to a pandas DataFrame.
    
    Args:
        load: DailyProductionLoad with jobs.
        constants: CycleTimeConstants for lookups.
        today: Current schedule date.
    
    Returns:
        pandas DataFrame with all job and calculated fields.
    """
    import pandas as pd
    
    rows = []
    for job in load.jobs:
        calc = calculate_fields_for_job(job, constants, today)
        rows.append(export_calculations_to_dict(job, calc))
    
    return pd.DataFrame(rows)
