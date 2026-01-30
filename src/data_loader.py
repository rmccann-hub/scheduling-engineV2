# Load DAILY_PRODUCTION_LOAD Excel data for the scheduling engine.
# Version: 1.0.0
# Parses job data from Excel and structures it for scheduling.

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from .errors import FileLoadError, ValidationError


# Type aliases
TableId = Literal[
    "RED_1", "RED_2", "BLUE_1", "BLUE_2", "GREEN_1", "GREEN_2",
    "BLACK_1", "BLACK_2", "PURPLE_1", "PURPLE_2", "ORANGE_1", "ORANGE_2"
]
Pattern = Literal["D", "S", "V"]
MoldType = Literal["STANDARD", "DOUBLE2CC", "3INURETHANE"]

# Valid table identifiers for ON_TABLE_TODAY
VALID_TABLES: frozenset[str] = frozenset({
    "RED_1", "RED_2", "BLUE_1", "BLUE_2", "GREEN_1", "GREEN_2",
    "BLACK_1", "BLACK_2", "PURPLE_1", "PURPLE_2", "ORANGE_1", "ORANGE_2"
})

# Valid patterns
VALID_PATTERNS: frozenset[str] = frozenset({"D", "S", "V", "W"})

# Valid mold types
VALID_MOLD_TYPES: frozenset[str] = frozenset({"STANDARD", "DOUBLE2CC", "3INURETHANE"})


@dataclass
class Job:
    """Represents a job from DAILY_PRODUCTION_LOAD.
    
    Contains both the raw data loaded from Excel and fields added by
    the operator during daily setup.
    
    Attributes:
        req_by: Required ship date.
        job_id: Unique job identifier (format: 123456-01-1).
        description: Job description for reports.
        pattern: Fixture pattern (D, S, or V).
        opening_size: Fixture opening size.
        wire_diameter: Wire diameter for task time lookups.
        molds: Number of molds required.
        mold_type: Type of molds needed (STANDARD, DOUBLE2CC, 3INURETHANE).
        prod_qty: Total production quantity required.
        equivalent: Difficulty factor for scheduling.
        orange_eligible: Whether job can run on ORANGE cell.
        on_table_today: Table where job is currently set up (operator input).
        job_quantity_remaining: Panels remaining if on_table_today is set.
        expedite: Whether to expedite regardless of calculated priority.
        row_number: Original row number in Excel (for error messages).
    """
    # Fields from Excel (required)
    req_by: date
    job_id: str
    description: str
    pattern: Pattern
    opening_size: float
    wire_diameter: float
    molds: int
    mold_type: MoldType
    prod_qty: int
    equivalent: float
    orange_eligible: bool
    
    # Fields added by operator (optional, populated during daily setup)
    on_table_today: TableId | None = None
    job_quantity_remaining: int | None = None
    expedite: bool = False
    
    # Metadata
    row_number: int = 0
    
    def __post_init__(self) -> None:
        """Validate job ID format after initialization."""
        # Job ID format: 6 digits - 1-2 digits - 1 digit
        # Example: 099457-1-1 or 099471-2-1
        self.job_id = str(self.job_id).strip()
    
    @property
    def fixture_id(self) -> str:
        """Generate fixture identifier from pattern, opening, and wire diameter.
        
        Returns:
            Fixture ID string (e.g., "D-0.0938-1.4").
        """
        return f"{self.pattern}-{self.opening_size}-{self.wire_diameter}"
    
    def set_on_table(
        self, 
        table_id: str | None, 
        quantity_remaining: int | None
    ) -> None:
        """Set the ON_TABLE_TODAY and JOB_QUANTITY_REMAINING fields.
        
        Called from UI when operator indicates a job is already set up on a table.
        
        Args:
            table_id: Table identifier (e.g., "RED_1") or None to clear.
            quantity_remaining: Panels remaining to produce, or None to clear.
        
        Raises:
            ValidationError: If values are invalid or inconsistent.
        """
        # Allow clearing both
        if table_id is None and quantity_remaining is None:
            self.on_table_today = None
            self.job_quantity_remaining = None
            return
        
        # Validate table_id
        if table_id is not None:
            table_id = str(table_id).strip().upper()
            if table_id not in VALID_TABLES:
                raise ValidationError(
                    field="ON_TABLE_TODAY",
                    value=table_id,
                    reason=f"Must be one of: {', '.join(sorted(VALID_TABLES))}",
                    row=self.row_number
                )
            
            # Check ORANGE table restrictions
            if table_id.startswith("ORANGE") and not self.orange_eligible:
                # Per PROGRAM_REQUIREMENTS: accept with warning, don't reject
                import logging
                logging.warning(
                    f"Job {self.job_id} has ORANGE_ELIGIBLE=false but is on {table_id}"
                )
        
        # Validate quantity_remaining
        if table_id is not None and quantity_remaining is None:
            raise ValidationError(
                field="JOB_QUANTITY_REMAINING",
                value=None,
                reason="Required when ON_TABLE_TODAY is set",
                row=self.row_number
            )
        
        if quantity_remaining is not None:
            if not isinstance(quantity_remaining, int) or quantity_remaining <= 0:
                raise ValidationError(
                    field="JOB_QUANTITY_REMAINING",
                    value=quantity_remaining,
                    reason="Must be a positive integer",
                    row=self.row_number
                )
            if quantity_remaining > self.prod_qty:
                raise ValidationError(
                    field="JOB_QUANTITY_REMAINING",
                    value=quantity_remaining,
                    reason=f"Cannot exceed PROD_QTY ({self.prod_qty})",
                    row=self.row_number
                )
        
        self.on_table_today = table_id
        self.job_quantity_remaining = quantity_remaining
    
    def set_expedite(self, expedite: bool) -> None:
        """Set the EXPEDITE flag for this job.
        
        Called from UI when operator needs to expedite a job.
        
        Args:
            expedite: True to expedite, False to clear expedite.
        """
        self.expedite = bool(expedite)
    
    def __hash__(self) -> int:
        """Allow jobs to be used in sets and as dict keys."""
        return hash(self.job_id)
    
    def __eq__(self, other: object) -> bool:
        """Compare jobs by job_id."""
        if not isinstance(other, Job):
            return NotImplemented
        return self.job_id == other.job_id


@dataclass
class DailyProductionLoad:
    """Container for all jobs loaded from DAILY_PRODUCTION_LOAD.
    
    Attributes:
        jobs: List of all jobs.
        load_timestamp: When the data was loaded.
        source_file: Path to the source Excel file.
    """
    jobs: list[Job] = field(default_factory=list)
    load_timestamp: datetime = field(default_factory=datetime.now)
    source_file: str = ""
    
    def __len__(self) -> int:
        """Return number of jobs."""
        return len(self.jobs)
    
    def __iter__(self):
        """Iterate over jobs."""
        return iter(self.jobs)
    
    def get_job(self, job_id: str) -> Job | None:
        """Find a job by ID.
        
        Args:
            job_id: Job identifier to find.
        
        Returns:
            Job if found, None otherwise.
        """
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        return None
    
    def get_jobs_on_tables(self) -> dict[str, Job]:
        """Get jobs that are currently on tables (ON_TABLE_TODAY set).
        
        Returns:
            Dictionary mapping table ID to job.
        """
        return {
            job.on_table_today: job 
            for job in self.jobs 
            if job.on_table_today is not None
        }
    
    def get_orange_eligible_jobs(self) -> list[Job]:
        """Get jobs that can run on ORANGE cell.
        
        Returns:
            List of jobs with orange_eligible=True.
        """
        return [job for job in self.jobs if job.orange_eligible]


def load_daily_production(filepath: str | Path) -> DailyProductionLoad:
    """Load DAILY_PRODUCTION_LOAD from Excel file.
    
    Args:
        filepath: Path to DAILY_PRODUCTION_LOAD.xlsx.
    
    Returns:
        DailyProductionLoad with all jobs parsed.
    
    Raises:
        FileLoadError: If file cannot be read.
        ValidationError: If required columns are missing or data is invalid.
    """
    filepath = Path(filepath)
    
    try:
        df = pd.read_excel(filepath)
    except FileNotFoundError as e:
        raise FileLoadError(str(filepath), e)
    except Exception as e:
        raise FileLoadError(str(filepath), e)
    
    # Validate required columns
    required_columns = {
        "REQ_BY", "JOB", "DESCRIPTION", "PATTERN", "OPENING_SIZE",
        "WIRE_DIAMETER", "MOLDS", "MOLD_TYPE", "PROD_QTY", 
        "EQUIVALENT", "ORANGE_ELIGIBLE"
    }
    
    available_columns = set(df.columns)
    missing_columns = required_columns - available_columns
    if missing_columns:
        raise ValidationError(
            field="columns",
            value=list(available_columns),
            reason=f"Missing required columns: {', '.join(sorted(missing_columns))}"
        )
    
    # Parse each row into a Job
    jobs = []
    for idx, row in df.iterrows():
        row_num = idx + 2  # Excel rows are 1-indexed, plus header
        job = _parse_job_row(row, row_num)
        jobs.append(job)
    
    return DailyProductionLoad(
        jobs=jobs,
        load_timestamp=datetime.now(),
        source_file=str(filepath)
    )


def _parse_job_row(row: pd.Series, row_number: int) -> Job:
    """Parse a single row into a Job object.
    
    Args:
        row: Pandas Series containing row data.
        row_number: Row number for error messages.
    
    Returns:
        Parsed Job object.
    
    Raises:
        ValidationError: If any field is invalid.
    """
    # Parse REQ_BY date
    req_by = _parse_date(row["REQ_BY"], "REQ_BY", row_number)
    
    # Parse and validate JOB ID
    job_id = str(row["JOB"]).strip()
    if not job_id or job_id.lower() == "nan":
        raise ValidationError(
            field="JOB",
            value=row["JOB"],
            reason="Job ID cannot be empty",
            row=row_number
        )
    
    # Parse DESCRIPTION (can be empty but should exist)
    description = str(row["DESCRIPTION"]) if pd.notna(row["DESCRIPTION"]) else ""
    
    # Parse and validate PATTERN
    pattern = str(row["PATTERN"]).strip().upper()
    if pattern not in VALID_PATTERNS:
        raise ValidationError(
            field="PATTERN",
            value=row["PATTERN"],
            reason=f"Must be one of: {', '.join(sorted(VALID_PATTERNS))}",
            row=row_number
        )
    
    # Parse OPENING_SIZE
    opening_size = _parse_float(row["OPENING_SIZE"], "OPENING_SIZE", row_number)
    if opening_size <= 0:
        raise ValidationError(
            field="OPENING_SIZE",
            value=opening_size,
            reason="Must be a positive number",
            row=row_number
        )
    
    # Parse WIRE_DIAMETER
    wire_diameter = _parse_float(row["WIRE_DIAMETER"], "WIRE_DIAMETER", row_number)
    if wire_diameter <= 0:
        raise ValidationError(
            field="WIRE_DIAMETER",
            value=wire_diameter,
            reason="Must be a positive number",
            row=row_number
        )
    
    # Parse MOLDS
    molds = _parse_int(row["MOLDS"], "MOLDS", row_number)
    if molds <= 0:
        raise ValidationError(
            field="MOLDS",
            value=molds,
            reason="Must be a positive integer",
            row=row_number
        )
    
    # Parse and validate MOLD_TYPE
    mold_type = str(row["MOLD_TYPE"]).strip().upper()
    if mold_type not in VALID_MOLD_TYPES:
        raise ValidationError(
            field="MOLD_TYPE",
            value=row["MOLD_TYPE"],
            reason=f"Must be one of: {', '.join(sorted(VALID_MOLD_TYPES))}",
            row=row_number
        )
    
    # Parse PROD_QTY
    prod_qty = _parse_int(row["PROD_QTY"], "PROD_QTY", row_number)
    if prod_qty <= 0:
        raise ValidationError(
            field="PROD_QTY",
            value=prod_qty,
            reason="Must be a positive integer",
            row=row_number
        )
    
    # Parse EQUIVALENT
    equivalent = _parse_float(row["EQUIVALENT"], "EQUIVALENT", row_number)
    if equivalent <= 0:
        raise ValidationError(
            field="EQUIVALENT",
            value=equivalent,
            reason="Must be a positive number",
            row=row_number
        )
    
    # Parse ORANGE_ELIGIBLE
    orange_eligible = _parse_bool(row["ORANGE_ELIGIBLE"], "ORANGE_ELIGIBLE", row_number)
    
    # Note: ON_TABLE_TODAY, JOB_QUANTITY_REMAINING, and EXPEDITE are NOT in the Excel file.
    # They are operator inputs set via the UI after the file is uploaded.
    # Those fields remain at their default values (None/False) until set by the UI.
    
    return Job(
        req_by=req_by,
        job_id=job_id,
        description=description,
        pattern=pattern,
        opening_size=opening_size,
        wire_diameter=wire_diameter,
        molds=molds,
        mold_type=mold_type,
        prod_qty=prod_qty,
        equivalent=equivalent,
        orange_eligible=orange_eligible,
        row_number=row_number
        # on_table_today, job_quantity_remaining, expedite use defaults (None/False)
        # These are set via UI after file upload
    )


def _parse_date(value, field_name: str, row_number: int) -> date:
    """Parse a value into a date.
    
    Args:
        value: Value to parse.
        field_name: Field name for error messages.
        row_number: Row number for error messages.
    
    Returns:
        Parsed date.
    
    Raises:
        ValidationError: If value cannot be parsed as a date.
    """
    if pd.isna(value):
        raise ValidationError(
            field=field_name,
            value=value,
            reason="Date cannot be empty",
            row=row_number
        )
    
    if isinstance(value, pd.Timestamp):
        return value.date()
    elif isinstance(value, datetime):
        return value.date()
    elif isinstance(value, date):
        return value
    else:
        try:
            parsed = pd.to_datetime(value)
            return parsed.date()
        except Exception:
            raise ValidationError(
                field=field_name,
                value=value,
                reason="Cannot parse as date",
                row=row_number
            )


def _parse_float(value, field_name: str, row_number: int) -> float:
    """Parse a value into a float.
    
    Args:
        value: Value to parse.
        field_name: Field name for error messages.
        row_number: Row number for error messages.
    
    Returns:
        Parsed float.
    
    Raises:
        ValidationError: If value cannot be parsed as a float.
    """
    if pd.isna(value):
        raise ValidationError(
            field=field_name,
            value=value,
            reason="Value cannot be empty",
            row=row_number
        )
    
    try:
        return float(value)
    except (ValueError, TypeError):
        raise ValidationError(
            field=field_name,
            value=value,
            reason="Must be a number",
            row=row_number
        )


def _parse_int(value, field_name: str, row_number: int) -> int:
    """Parse a value into an integer.
    
    Args:
        value: Value to parse.
        field_name: Field name for error messages.
        row_number: Row number for error messages.
    
    Returns:
        Parsed integer.
    
    Raises:
        ValidationError: If value cannot be parsed as an integer.
    """
    if pd.isna(value):
        raise ValidationError(
            field=field_name,
            value=value,
            reason="Value cannot be empty",
            row=row_number
        )
    
    try:
        return int(float(value))
    except (ValueError, TypeError):
        raise ValidationError(
            field=field_name,
            value=value,
            reason="Must be an integer",
            row=row_number
        )


def _parse_bool(value, field_name: str, row_number: int) -> bool:
    """Parse a value into a boolean.
    
    Args:
        value: Value to parse.
        field_name: Field name for error messages.
        row_number: Row number for error messages.
    
    Returns:
        Parsed boolean.
    
    Raises:
        ValidationError: If value cannot be parsed as a boolean.
    """
    if pd.isna(value):
        return False
    
    if isinstance(value, bool):
        return value
    
    if isinstance(value, (int, float)):
        return bool(value)
    
    str_val = str(value).strip().upper()
    if str_val in ("TRUE", "YES", "1", "Y"):
        return True
    elif str_val in ("FALSE", "NO", "0", "N", ""):
        return False
    else:
        raise ValidationError(
            field=field_name,
            value=value,
            reason="Must be TRUE/FALSE, YES/NO, or 1/0",
            row=row_number
        )
