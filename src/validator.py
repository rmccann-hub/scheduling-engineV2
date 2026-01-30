# Business rule validation for the scheduling engine.
# Version: 1.0.0
# Validates jobs against CELL_RULES_SIMPLIFIED constraints and cross-field rules.

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from .constants import CycleTimeConstants, CELL_COLORS, CellColor
from .data_loader import DailyProductionLoad, Job, VALID_TABLES
from .errors import ValidationError


@dataclass
class ValidationWarning:
    """A non-fatal validation issue that should be reported but doesn't block scheduling.
    
    Attributes:
        job_id: Job identifier.
        field: Field name related to the warning.
        message: Human-readable warning message.
    """
    job_id: str
    field: str
    message: str


@dataclass
class ValidationResult:
    """Result of validating the daily production load.
    
    Attributes:
        is_valid: True if no blocking errors found.
        errors: List of ValidationError exceptions.
        warnings: List of non-blocking ValidationWarning instances.
        valid_jobs: List of jobs that passed validation.
        invalid_job_ids: Set of job IDs that failed validation.
    """
    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)
    valid_jobs: list[Job] = field(default_factory=list)
    invalid_job_ids: set[str] = field(default_factory=set)
    
    def add_error(self, error: ValidationError, job_id: str | None = None) -> None:
        """Add a validation error.
        
        Args:
            error: ValidationError to add.
            job_id: Optional job ID to mark as invalid.
        """
        self.errors.append(error)
        self.is_valid = False
        if job_id:
            self.invalid_job_ids.add(job_id)
    
    def add_warning(self, warning: ValidationWarning) -> None:
        """Add a validation warning.
        
        Args:
            warning: ValidationWarning to add.
        """
        self.warnings.append(warning)


@dataclass
class OperatorInputs:
    """Operator inputs set via UI before scheduling.
    
    Attributes:
        active_cells: Set of cell colors that are staffed and active.
        shift_type: "standard" (440 min) or "overtime" (500 min).
        orange_enabled: Whether ORANGE cell can be scheduled.
        summer_mode: Whether SUMMER cure time multiplier applies.
        schedule_date: Date to schedule (defaults to today, must be weekday).
        orange_allow_3inurethane: Allow 3INURETHANE mold on ORANGE (default False).
        orange_allow_double2cc: Allow DOUBLE2CC_MOLD on ORANGE (default False).
        orange_allow_deep_double2cc: Allow DEEP_DOUBLE2CC_MOLD on ORANGE (default False).
    """
    active_cells: set[CellColor] = field(default_factory=set)
    shift_type: Literal["standard", "overtime"] = "standard"
    orange_enabled: bool = False
    summer_mode: bool = False
    schedule_date: date = field(default_factory=date.today)
    orange_allow_3inurethane: bool = False
    orange_allow_double2cc: bool = False
    orange_allow_deep_double2cc: bool = False
    
    @property
    def shift_minutes(self) -> int:
        """Get available shift minutes based on shift type."""
        return 500 if self.shift_type == "overtime" else 440
    
    def is_cell_active(self, cell_color: CellColor) -> bool:
        """Check if a cell is active.
        
        Args:
            cell_color: Cell color to check.
        
        Returns:
            True if cell is in active_cells set.
        """
        return cell_color in self.active_cells
    
    def is_job_allowed_on_orange(self, mold_type: str) -> bool:
        """Check if a job's mold type is allowed on ORANGE cell.
        
        Args:
            mold_type: The mold type from the job.
            
        Returns:
            True if mold type is allowed on ORANGE.
        """
        if mold_type == "3INURETHANE":
            return self.orange_allow_3inurethane
        elif mold_type == "DOUBLE2CC_MOLD":
            return self.orange_allow_double2cc
        elif mold_type == "DEEP_DOUBLE2CC_MOLD":
            return self.orange_allow_deep_double2cc
        return True  # Other mold types allowed by default


def validate_production_load(
    load: DailyProductionLoad,
    constants: CycleTimeConstants,
    operator_inputs: OperatorInputs
) -> ValidationResult:
    """Validate all jobs in the production load.
    
    Performs validation checks:
    1. Job field validation (already done in data_loader, but cross-checked)
    2. Cross-field validation (e.g., MOLD_TYPE vs MOLDS count)
    3. Resource existence validation (fixtures, molds exist in constants)
    4. ON_TABLE_TODAY consistency with active cells
    5. Schedule date validation (must be business day)
    
    Args:
        load: DailyProductionLoad with jobs to validate.
        constants: CycleTimeConstants for resource lookups.
        operator_inputs: Operator inputs for context-dependent validation.
    
    Returns:
        ValidationResult with errors, warnings, and valid jobs.
    """
    result = ValidationResult()
    
    # Validate schedule date first
    _validate_schedule_date(operator_inputs, constants, result)
    
    # Validate operator inputs consistency
    _validate_operator_inputs(operator_inputs, result)
    
    # Track tables used by ON_TABLE_TODAY to detect duplicates
    tables_in_use: dict[str, str] = {}  # table_id -> job_id
    
    for job in load.jobs:
        job_valid = True
        
        # Validate task timing exists for this job's wire/equivalent
        if not _validate_task_timing(job, constants, result):
            job_valid = False
        
        # Validate mold requirements can be satisfied
        if not _validate_mold_requirements(job, constants, result):
            job_valid = False
        
        # Validate fixture pattern is valid
        if not _validate_fixture(job, constants, result):
            job_valid = False
        
        # Validate MOLD_TYPE vs MOLDS count (DOUBLE2CC needs at least 2)
        if not _validate_mold_type_count(job, result):
            job_valid = False
        
        # Validate ON_TABLE_TODAY if set
        if job.on_table_today is not None:
            if not _validate_on_table_today(
                job, operator_inputs, tables_in_use, result
            ):
                job_valid = False
        
        # Check ORANGE eligibility warnings
        _check_orange_warnings(job, operator_inputs, result)
        
        if job_valid:
            result.valid_jobs.append(job)
        else:
            result.invalid_job_ids.add(job.job_id)
    
    return result


def _validate_schedule_date(
    inputs: OperatorInputs,
    constants: CycleTimeConstants,
    result: ValidationResult
) -> None:
    """Validate the schedule date is a valid business day.
    
    Args:
        inputs: Operator inputs containing schedule_date.
        constants: CycleTimeConstants with holiday list.
        result: ValidationResult to add errors to.
    """
    sched_date = inputs.schedule_date
    
    # Check if weekend
    if sched_date.weekday() > 4:
        day_name = ["Monday", "Tuesday", "Wednesday", "Thursday", 
                    "Friday", "Saturday", "Sunday"][sched_date.weekday()]
        result.add_error(
            ValidationError(
                field="schedule_date",
                value=sched_date,
                reason=f"Cannot schedule on {day_name}. Must be a weekday."
            )
        )
        return
    
    # Check if holiday
    if sched_date in constants.holidays:
        result.add_error(
            ValidationError(
                field="schedule_date",
                value=sched_date,
                reason=f"{sched_date} is a company holiday. Choose another date."
            )
        )


def _validate_operator_inputs(
    inputs: OperatorInputs,
    result: ValidationResult
) -> None:
    """Validate operator inputs are consistent.
    
    Args:
        inputs: Operator inputs to validate.
        result: ValidationResult to add errors/warnings to.
    """
    # If ORANGE is enabled, it should be in active_cells
    if inputs.orange_enabled and "ORANGE" not in inputs.active_cells:
        result.add_warning(
            ValidationWarning(
                job_id="",
                field="orange_enabled",
                message="ORANGE is enabled but not in active cells. "
                        "ORANGE jobs won't be scheduled."
            )
        )
    
    # At least one cell should be active
    if not inputs.active_cells:
        result.add_error(
            ValidationError(
                field="active_cells",
                value=set(),
                reason="At least one cell must be active to schedule"
            )
        )
    
    # Validate all active cells are valid colors
    for cell in inputs.active_cells:
        if cell not in CELL_COLORS:
            result.add_error(
                ValidationError(
                    field="active_cells",
                    value=cell,
                    reason=f"Invalid cell color. Must be one of: {', '.join(CELL_COLORS)}"
                )
            )


def _validate_task_timing(
    job: Job,
    constants: CycleTimeConstants,
    result: ValidationResult
) -> bool:
    """Validate task timing exists for this job's wire diameter and equivalent.
    
    Args:
        job: Job to validate.
        constants: CycleTimeConstants with task timing lookup.
        result: ValidationResult to add errors to.
    
    Returns:
        True if timing exists, False otherwise.
    """
    try:
        constants.get_task_timing(job.wire_diameter, job.equivalent)
        return True
    except Exception:
        result.add_error(
            ValidationError(
                field="WIRE_DIAMETER/EQUIVALENT",
                value=f"{job.wire_diameter}/{job.equivalent}",
                reason="No task timing defined for this combination",
                row=job.row_number
            ),
            job.job_id
        )
        return False


def _validate_mold_requirements(
    job: Job,
    constants: CycleTimeConstants,
    result: ValidationResult
) -> bool:
    """Validate that molds exist for this job's requirements.
    
    Args:
        job: Job to validate.
        constants: CycleTimeConstants with mold info.
        result: ValidationResult to add errors to.
    
    Returns:
        True if molds can be satisfied, False otherwise.
    """
    mold_depth = constants.get_mold_depth(job.wire_diameter)
    
    # Check that required mold types exist
    if mold_depth == "DEEP":
        if "DEEP_MOLD" not in constants.molds:
            result.add_error(
                ValidationError(
                    field="MOLDS",
                    value=job.molds,
                    reason="DEEP_MOLD not defined in configuration",
                    row=job.row_number
                ),
                job.job_id
            )
            return False
        
        if job.mold_type in ("DOUBLE2CC", "3INURETHANE"):
            if "DEEP_DOUBLE2CC_MOLD" not in constants.molds:
                result.add_error(
                    ValidationError(
                        field="MOLD_TYPE",
                        value=job.mold_type,
                        reason="DEEP_DOUBLE2CC_MOLD not defined in configuration",
                        row=job.row_number
                    ),
                    job.job_id
                )
                return False
    else:
        # STD depth - need color molds and potentially specialty molds
        if job.mold_type == "DOUBLE2CC":
            if "DOUBLE2CC_MOLD" not in constants.molds:
                result.add_error(
                    ValidationError(
                        field="MOLD_TYPE",
                        value=job.mold_type,
                        reason="DOUBLE2CC_MOLD not defined in configuration",
                        row=job.row_number
                    ),
                    job.job_id
                )
                return False
        
        if job.mold_type == "3INURETHANE":
            if "3INURETHANE_MOLD" not in constants.molds:
                result.add_error(
                    ValidationError(
                        field="MOLD_TYPE",
                        value=job.mold_type,
                        reason="3INURETHANE_MOLD not defined in configuration",
                        row=job.row_number
                    ),
                    job.job_id
                )
                return False
    
    return True


def _validate_fixture(
    job: Job,
    constants: CycleTimeConstants,
    result: ValidationResult
) -> bool:
    """Validate fixture pattern is valid.
    
    Args:
        job: Job to validate.
        constants: CycleTimeConstants with fixture limits.
        result: ValidationResult to add errors to.
    
    Returns:
        True if fixture pattern is valid, False otherwise.
    """
    if job.pattern not in constants.fixtures:
        result.add_error(
            ValidationError(
                field="PATTERN",
                value=job.pattern,
                reason=f"Unknown pattern. Valid patterns: {', '.join(constants.fixtures.keys())}",
                row=job.row_number
            ),
            job.job_id
        )
        return False
    return True


def _validate_mold_type_count(job: Job, result: ValidationResult) -> bool:
    """Validate MOLD_TYPE requirements match MOLDS count.
    
    Per CELL_RULES_SIMPLIFIED:
    - DOUBLE2CC requires MOLDS >= 2 (uses MOLDS-2 color molds + 1 DOUBLE2CC)
    - 3INURETHANE requires MOLDS >= 1 (uses MOLDS-1 color molds + 1 3INURETHANE)
    
    Args:
        job: Job to validate.
        result: ValidationResult to add errors to.
    
    Returns:
        True if valid, False otherwise.
    """
    if job.mold_type == "DOUBLE2CC" and job.molds < 2:
        result.add_error(
            ValidationError(
                field="MOLDS",
                value=job.molds,
                reason="DOUBLE2CC mold type requires at least 2 molds",
                row=job.row_number
            ),
            job.job_id
        )
        return False
    
    # 3INURETHANE only needs 1 mold minimum, which is already validated
    return True


def _validate_on_table_today(
    job: Job,
    inputs: OperatorInputs,
    tables_in_use: dict[str, str],
    result: ValidationResult
) -> bool:
    """Validate ON_TABLE_TODAY assignment.
    
    Checks:
    1. Table is not already assigned to another job
    2. ORANGE tables respect ORANGE_ENABLED setting
    3. Jobs on NOT ACTIVE cells are flagged for rescheduling
    
    Args:
        job: Job to validate.
        inputs: Operator inputs for cell status.
        tables_in_use: Dict tracking table -> job_id assignments.
        result: ValidationResult to add errors/warnings to.
    
    Returns:
        True if valid, False if blocking error.
    """
    table_id = job.on_table_today
    
    # Check for duplicate table assignment
    if table_id in tables_in_use:
        existing_job = tables_in_use[table_id]
        result.add_error(
            ValidationError(
                field="ON_TABLE_TODAY",
                value=table_id,
                reason=f"Table already assigned to job {existing_job}",
                row=job.row_number
            ),
            job.job_id
        )
        return False
    
    # Register this table
    tables_in_use[table_id] = job.job_id
    
    # Extract cell color from table_id (e.g., "RED_1" -> "RED")
    cell_color = table_id.rsplit("_", 1)[0]
    
    # Check ORANGE table with ORANGE not enabled
    if cell_color == "ORANGE" and not inputs.orange_enabled:
        result.add_warning(
            ValidationWarning(
                job_id=job.job_id,
                field="ON_TABLE_TODAY",
                message=f"Job is on {table_id} but ORANGE is not enabled. "
                        "Job will need to be rescheduled."
            )
        )
    
    # Check if cell is active
    if cell_color not in inputs.active_cells:
        result.add_warning(
            ValidationWarning(
                job_id=job.job_id,
                field="ON_TABLE_TODAY",
                message=f"Job is on {table_id} but {cell_color} cell is NOT ACTIVE. "
                        "Job will need to be rescheduled if priority <= 2."
            )
        )
    
    return True


def _check_orange_warnings(
    job: Job,
    inputs: OperatorInputs,
    result: ValidationResult
) -> None:
    """Check for ORANGE-related warnings.
    
    Args:
        job: Job to check.
        inputs: Operator inputs for ORANGE status.
        result: ValidationResult to add warnings to.
    """
    # Warn if ORANGE is enabled but job is not ORANGE_ELIGIBLE
    # and job is high priority (might want it on ORANGE for capacity)
    if (inputs.orange_enabled and 
        "ORANGE" in inputs.active_cells and
        not job.orange_eligible):
        
        # Only warn for high-mold-count jobs that could benefit from ORANGE
        if job.molds >= 6:
            result.add_warning(
                ValidationWarning(
                    job_id=job.job_id,
                    field="ORANGE_ELIGIBLE",
                    message=f"Job has {job.molds} molds but is not ORANGE_ELIGIBLE. "
                            "Consider if ORANGE cell could be used."
                )
            )
    
    # Warn about DEEP mold jobs that are ORANGE_ELIGIBLE
    # Per MOLDS sheet, DEEP molds are not ORANGE_COMPLIANT
    mold_depth = "DEEP" if job.wire_diameter >= 8 else "STD"
    if job.orange_eligible and mold_depth == "DEEP":
        result.add_warning(
            ValidationWarning(
                job_id=job.job_id,
                field="ORANGE_ELIGIBLE",
                message=f"Job requires DEEP molds (WIRE_DIAMETER={job.wire_diameter}) "
                        "which are not ORANGE compliant. Will be scheduled on other cells."
            )
        )


def validate_single_job(
    job: Job,
    constants: CycleTimeConstants
) -> list[ValidationError]:
    """Validate a single job without operator context.
    
    Useful for validating a job before adding it to the load.
    
    Args:
        job: Job to validate.
        constants: CycleTimeConstants for lookups.
    
    Returns:
        List of ValidationErrors (empty if valid).
    """
    errors = []
    
    # Check task timing exists
    try:
        constants.get_task_timing(job.wire_diameter, job.equivalent)
    except Exception:
        errors.append(
            ValidationError(
                field="WIRE_DIAMETER/EQUIVALENT",
                value=f"{job.wire_diameter}/{job.equivalent}",
                reason="No task timing defined for this combination",
                row=job.row_number
            )
        )
    
    # Check fixture pattern
    if job.pattern not in constants.fixtures:
        errors.append(
            ValidationError(
                field="PATTERN",
                value=job.pattern,
                reason=f"Unknown pattern. Valid: {', '.join(constants.fixtures.keys())}",
                row=job.row_number
            )
        )
    
    # Check mold type vs count
    if job.mold_type == "DOUBLE2CC" and job.molds < 2:
        errors.append(
            ValidationError(
                field="MOLDS",
                value=job.molds,
                reason="DOUBLE2CC requires at least 2 molds",
                row=job.row_number
            )
        )
    
    return errors
