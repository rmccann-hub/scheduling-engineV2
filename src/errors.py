# Custom exception hierarchy for the cell scheduling engine.
# Version: 1.0.0
# Provides structured error handling with field-level context and user-friendly messages.

from typing import Any


class SchedulingError(Exception):
    """Base exception for all scheduling engine errors.
    
    All custom exceptions inherit from this class to allow catching
    any scheduling-related error with a single except clause.
    
    Attributes:
        message: Human-readable error description.
        details: Additional context for debugging.
    """
    
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize the scheduling error.
        
        Args:
            message: Human-readable error description.
            details: Optional dictionary of additional context.
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Return formatted error message with details."""
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} [{detail_str}]"
        return self.message


class ValidationError(SchedulingError):
    """Raised when input data fails validation.
    
    Used for invalid field values, type mismatches, out-of-range values,
    and missing required fields in DAILY_PRODUCTION_LOAD or operator inputs.
    
    Attributes:
        field: Name of the field that failed validation.
        value: The invalid value that was provided.
        reason: Explanation of why the value is invalid.
        row: Optional row number in the data source.
    """
    
    def __init__(
        self, 
        field: str, 
        value: Any, 
        reason: str,
        row: int | None = None
    ) -> None:
        """Initialize the validation error.
        
        Args:
            field: Name of the field that failed validation.
            value: The invalid value provided.
            reason: Explanation of why validation failed.
            row: Optional row number (1-indexed) for spreadsheet errors.
        """
        self.field = field
        self.value = value
        self.reason = reason
        self.row = row
        
        details = {"field": field, "value": repr(value)}
        if row is not None:
            details["row"] = row
        
        location = f" in row {row}" if row else ""
        message = f"Invalid {field}{location}: {reason}. Got: {repr(value)}"
        super().__init__(message, details)


class ConfigurationError(SchedulingError):
    """Raised when configuration data is invalid or missing.
    
    Used for errors in CYCLE_TIME_CONSTANTS.xlsx including missing sheets,
    invalid task timing values, or malformed mold/fixture data.
    
    Attributes:
        config_source: Name of the configuration source (sheet name, file, etc.).
        issue: Description of the configuration problem.
    """
    
    def __init__(self, config_source: str, issue: str) -> None:
        """Initialize the configuration error.
        
        Args:
            config_source: Name of the configuration source.
            issue: Description of what's wrong with the configuration.
        """
        self.config_source = config_source
        self.issue = issue
        
        message = f"Configuration error in {config_source}: {issue}"
        super().__init__(message, {"source": config_source})


class InfeasibleScheduleError(SchedulingError):
    """Raised when no valid schedule exists for the given constraints.
    
    The solver could not find any solution that satisfies all hard constraints.
    This may occur when there are too many high-priority jobs, insufficient
    resources, or conflicting constraint requirements.
    
    Attributes:
        unscheduled_jobs: List of jobs that could not be scheduled.
        reason: Explanation of why scheduling failed.
    """
    
    def __init__(
        self, 
        unscheduled_jobs: list[str], 
        reason: str
    ) -> None:
        """Initialize the infeasible schedule error.
        
        Args:
            unscheduled_jobs: List of job IDs that could not be scheduled.
            reason: Explanation of why scheduling was infeasible.
        """
        self.unscheduled_jobs = unscheduled_jobs
        self.reason = reason
        
        job_count = len(unscheduled_jobs)
        message = f"Cannot create valid schedule: {reason}. {job_count} job(s) unscheduled."
        super().__init__(message, {"unscheduled_count": job_count, "reason": reason})


class ResourceExhaustedError(SchedulingError):
    """Raised when required resources (molds, fixtures) are unavailable.
    
    Indicates that a job cannot be scheduled because the molds or fixtures
    it requires are either not available in sufficient quantity or are
    already allocated to other jobs.
    
    Attributes:
        resource_type: Type of resource (MOLD, FIXTURE).
        resource_name: Specific resource identifier.
        required: Quantity required.
        available: Quantity currently available.
    """
    
    def __init__(
        self,
        resource_type: str,
        resource_name: str,
        required: int,
        available: int
    ) -> None:
        """Initialize the resource exhausted error.
        
        Args:
            resource_type: Type of resource (e.g., "MOLD", "FIXTURE").
            resource_name: Specific resource identifier.
            required: Number of units required.
            available: Number of units currently available.
        """
        self.resource_type = resource_type
        self.resource_name = resource_name
        self.required = required
        self.available = available
        
        message = (
            f"Insufficient {resource_type.lower()}s: need {required} {resource_name}, "
            f"only {available} available."
        )
        details = {
            "resource_type": resource_type,
            "resource_name": resource_name,
            "required": required,
            "available": available,
            "shortage": required - available
        }
        super().__init__(message, details)


class FileLoadError(SchedulingError):
    """Raised when a required file cannot be loaded.
    
    Covers file not found, permission denied, corrupted files, and
    unexpected file format issues.
    
    Attributes:
        filepath: Path to the file that failed to load.
        cause: The underlying exception that caused the failure.
    """
    
    def __init__(self, filepath: str, cause: Exception) -> None:
        """Initialize the file load error.
        
        Args:
            filepath: Path to the file that failed to load.
            cause: The underlying exception.
        """
        self.filepath = filepath
        self.cause = cause
        
        # Extract just the filename for cleaner messages
        filename = filepath.split("/")[-1].split("\\")[-1]
        cause_type = type(cause).__name__
        
        message = f"Failed to load {filename}: {cause_type} - {cause}"
        super().__init__(message, {"filepath": filepath, "cause_type": cause_type})


class ConstraintViolationError(SchedulingError):
    """Raised when a scheduling constraint is violated.
    
    Used internally when the solver attempts an assignment that would
    violate a hard constraint. This helps with debugging constraint issues.
    
    Attributes:
        constraint_id: Identifier for the constraint (e.g., "HC4").
        description: Human-readable description of the constraint.
        violation: What specifically violated the constraint.
    """
    
    def __init__(
        self,
        constraint_id: str,
        description: str,
        violation: str
    ) -> None:
        """Initialize the constraint violation error.
        
        Args:
            constraint_id: Constraint identifier (e.g., "HC1", "HC4").
            description: What the constraint requires.
            violation: How the constraint was violated.
        """
        self.constraint_id = constraint_id
        self.description = description
        self.violation = violation
        
        message = f"Constraint {constraint_id} violated: {description}. {violation}"
        super().__init__(
            message, 
            {"constraint_id": constraint_id, "description": description}
        )


class SolverTimeoutError(SchedulingError):
    """Raised when the OR-Tools solver exceeds its time limit.
    
    The solver was unable to find an optimal solution within the allowed
    time. A partial (best-found) solution may still be available.
    
    Attributes:
        timeout_seconds: The time limit that was exceeded.
        best_solution_found: Whether any feasible solution was found.
    """
    
    def __init__(
        self, 
        timeout_seconds: float, 
        best_solution_found: bool
    ) -> None:
        """Initialize the solver timeout error.
        
        Args:
            timeout_seconds: The time limit that was exceeded.
            best_solution_found: True if a feasible solution exists.
        """
        self.timeout_seconds = timeout_seconds
        self.best_solution_found = best_solution_found
        
        if best_solution_found:
            message = (
                f"Solver timed out after {timeout_seconds}s. "
                "Best-found solution is available but may not be optimal."
            )
        else:
            message = (
                f"Solver timed out after {timeout_seconds}s. "
                "No feasible solution found within time limit."
            )
        
        super().__init__(
            message, 
            {"timeout": timeout_seconds, "has_solution": best_solution_found}
        )
