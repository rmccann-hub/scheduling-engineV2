# Resource management for molds and fixtures.
# Version: 1.0.0
# Tracks mold availability, fixture limits, and resource allocation.

from dataclasses import dataclass, field
from typing import Literal

from .constants import CycleTimeConstants, CellColor, CELL_COLORS, MoldInfo
from .data_loader import Job
from .calculated_fields import CalculatedFields


@dataclass
class MoldRequirement:
    """Mold requirement for a job.
    
    Attributes:
        job_id: Job identifier.
        mold_depth: DEEP or STD.
        mold_type: STANDARD, DOUBLE2CC, or 3INURETHANE.
        molds_needed: Number of molds required.
        primary_mold: Primary mold type to use.
        specialty_mold: Specialty mold if needed (DOUBLE2CC/3INURETHANE).
        primary_count: Number of primary molds needed.
        specialty_count: Number of specialty molds needed.
    """
    job_id: str
    mold_depth: Literal["DEEP", "STD"]
    mold_type: Literal["STANDARD", "DOUBLE2CC", "3INURETHANE"]
    molds_needed: int
    primary_mold: str = ""
    specialty_mold: str | None = None
    primary_count: int = 0
    specialty_count: int = 0


@dataclass
class MoldAllocation:
    """Allocation of molds to a job on a specific cell.
    
    Attributes:
        job_id: Job identifier.
        cell_color: Cell where job is allocated.
        mold_assignments: Dict mapping mold name to count allocated.
        is_valid: Whether allocation is valid (all molds available).
        error_message: Error message if allocation failed.
    """
    job_id: str
    cell_color: CellColor
    mold_assignments: dict[str, int] = field(default_factory=dict)
    is_valid: bool = True
    error_message: str = ""


@dataclass
class ResourcePool:
    """Pool of available resources for scheduling.
    
    Tracks molds and fixtures across all cells, handling reservations
    for active cells and ON_TABLE_TODAY jobs.
    
    Attributes:
        mold_inventory: Dict of mold name to total quantity.
        mold_available: Dict of mold name to currently available quantity.
        mold_reserved: Dict of mold name to reserved quantity (active cells).
        fixture_limits: Dict of pattern to max concurrent tables.
        fixture_in_use: Dict of fixture_id to count of tables using it.
        active_cells: Set of active cell colors.
    """
    mold_inventory: dict[str, int] = field(default_factory=dict)
    mold_available: dict[str, int] = field(default_factory=dict)
    mold_reserved: dict[str, int] = field(default_factory=dict)
    fixture_limits: dict[str, int] = field(default_factory=dict)
    fixture_in_use: dict[str, int] = field(default_factory=dict)
    active_cells: set[CellColor] = field(default_factory=set)
    
    def get_available_molds(self, mold_name: str) -> int:
        """Get currently available quantity of a mold type."""
        return self.mold_available.get(mold_name, 0)
    
    def reserve_molds(self, mold_name: str, count: int) -> bool:
        """Reserve molds from the available pool.
        
        Args:
            mold_name: Mold type to reserve.
            count: Number to reserve.
        
        Returns:
            True if reservation successful, False if insufficient.
        """
        available = self.mold_available.get(mold_name, 0)
        if count > available:
            return False
        self.mold_available[mold_name] = available - count
        return True
    
    def release_molds(self, mold_name: str, count: int) -> None:
        """Release molds back to the available pool."""
        current = self.mold_available.get(mold_name, 0)
        max_qty = self.mold_inventory.get(mold_name, 0)
        self.mold_available[mold_name] = min(current + count, max_qty)
    
    def check_fixture_limit(self, pattern: str) -> bool:
        """Check if another table can use this fixture pattern.
        
        Args:
            pattern: Fixture pattern (D, S, or V).
        
        Returns:
            True if within limit, False if at capacity.
        """
        limit = self.fixture_limits.get(pattern, 999)
        in_use = self.fixture_in_use.get(pattern, 0)
        return in_use < limit
    
    def reserve_fixture(self, fixture_id: str) -> bool:
        """Reserve a fixture slot.
        
        Args:
            fixture_id: Full fixture ID (e.g., "D-0.0938-1.4").
        
        Returns:
            True if reservation successful.
        """
        pattern = fixture_id.split("-")[0]
        if not self.check_fixture_limit(pattern):
            return False
        self.fixture_in_use[pattern] = self.fixture_in_use.get(pattern, 0) + 1
        return True
    
    def release_fixture(self, fixture_id: str) -> None:
        """Release a fixture slot."""
        pattern = fixture_id.split("-")[0]
        current = self.fixture_in_use.get(pattern, 0)
        if current > 0:
            self.fixture_in_use[pattern] = current - 1


def create_resource_pool(
    constants: CycleTimeConstants,
    active_cells: set[CellColor]
) -> ResourcePool:
    """Create a resource pool from constants and active cells.
    
    Initializes mold inventory and reserves molds for active cells.
    
    Args:
        constants: CycleTimeConstants with mold and fixture info.
        active_cells: Set of active cell colors.
    
    Returns:
        Initialized ResourcePool.
    """
    pool = ResourcePool(active_cells=active_cells)
    
    # Initialize mold inventory
    for mold_name, mold_info in constants.molds.items():
        pool.mold_inventory[mold_name] = mold_info.quantity
        pool.mold_available[mold_name] = mold_info.quantity
    
    # Initialize fixture limits
    for pattern, fixture_info in constants.fixtures.items():
        pool.fixture_limits[pattern] = fixture_info.max_concurrent
    
    # Reserve color-specific molds for active cells
    # Per CELL_RULES: Active cells have their color molds reserved
    for cell_color in active_cells:
        if cell_color == "ORANGE":
            continue  # ORANGE uses ORANGE_MOLD, handled separately
        
        color_mold = f"{cell_color}_MOLD"
        if color_mold in pool.mold_inventory:
            qty = pool.mold_inventory[color_mold]
            pool.mold_reserved[color_mold] = qty
            # Don't deduct from available - reserved molds ARE available for that cell
    
    return pool


def calculate_mold_requirement(
    job: Job,
    calc: CalculatedFields,
    cell_color: CellColor
) -> MoldRequirement:
    """Calculate mold requirements for a job on a specific cell.
    
    Per CELL_RULES_SIMPLIFIED mold assignment rules:
    - DEEP + STANDARD: MOLDS × DEEP_MOLD
    - DEEP + DOUBLE2CC/3INURETHANE: (MOLDS-1) × DEEP_MOLD + 1 × DEEP_DOUBLE2CC_MOLD
    - STD + STANDARD: MOLDS × {COLOR}_MOLD
    - STD + 3INURETHANE: (MOLDS-1) × {COLOR}_MOLD + 1 × 3INURETHANE_MOLD
    - STD + DOUBLE2CC: (MOLDS-2) × {COLOR}_MOLD + 1 × DOUBLE2CC_MOLD
    
    Args:
        job: Job to calculate requirements for.
        calc: Calculated fields with mold_depth.
        cell_color: Target cell for the job.
    
    Returns:
        MoldRequirement with mold assignments.
    """
    req = MoldRequirement(
        job_id=job.job_id,
        mold_depth=calc.mold_depth,
        mold_type=job.mold_type,
        molds_needed=job.molds
    )
    
    if calc.mold_depth == "DEEP":
        # DEEP molds
        req.primary_mold = "DEEP_MOLD"
        
        if job.mold_type == "STANDARD":
            req.primary_count = job.molds
        else:
            # DOUBLE2CC or 3INURETHANE - use DEEP_DOUBLE2CC_MOLD for specialty
            req.primary_count = job.molds - 1
            req.specialty_mold = "DEEP_DOUBLE2CC_MOLD"
            req.specialty_count = 1
    else:
        # STD molds - use color-specific or ORANGE_MOLD
        if cell_color == "ORANGE":
            req.primary_mold = "ORANGE_MOLD"
        else:
            req.primary_mold = f"{cell_color}_MOLD"
        
        if job.mold_type == "STANDARD":
            req.primary_count = job.molds
        elif job.mold_type == "3INURETHANE":
            req.primary_count = job.molds - 1
            req.specialty_mold = "3INURETHANE_MOLD"
            req.specialty_count = 1
        else:  # DOUBLE2CC
            req.primary_count = job.molds - 2
            req.specialty_mold = "DOUBLE2CC_MOLD"
            req.specialty_count = 1
    
    return req


def allocate_molds_for_job(
    job: Job,
    calc: CalculatedFields,
    cell_color: CellColor,
    pool: ResourcePool,
    constants: CycleTimeConstants
) -> MoldAllocation:
    """Attempt to allocate molds for a job on a specific cell.
    
    Follows the mold availability priority from CELL_RULES:
    1. Use {COLOR}_MOLD matching cell (if ACTIVE, these are reserved)
    2. Use COMMON_MOLD
    3. Use {COLOR}_MOLD from NOT ACTIVE cells (if compliant)
    4. If none available → allocation fails
    
    Args:
        job: Job to allocate molds for.
        calc: Calculated fields for the job.
        cell_color: Target cell.
        pool: Resource pool with available molds.
        constants: CycleTimeConstants for mold compliance info.
    
    Returns:
        MoldAllocation with assignments or error.
    """
    allocation = MoldAllocation(job_id=job.job_id, cell_color=cell_color)
    
    # Calculate requirements
    req = calculate_mold_requirement(job, calc, cell_color)
    
    # Check if cell is compliant for required mold depth
    if not _is_cell_compliant(cell_color, req.mold_depth, constants):
        allocation.is_valid = False
        allocation.error_message = (
            f"Cell {cell_color} is not compliant for {req.mold_depth} molds"
        )
        return allocation
    
    # Allocate primary molds
    primary_needed = req.primary_count
    primary_allocated = 0
    
    # Handle DEEP molds differently - they are shared, not reserved
    if req.mold_depth == "DEEP":
        # DEEP molds are shared across all compliant cells
        available = pool.get_available_molds(req.primary_mold)
        take = min(primary_needed, available)
        if take > 0:
            allocation.mold_assignments[req.primary_mold] = take
            primary_allocated += take
            primary_needed -= take
    else:
        # STD molds - Priority 1: Use cell's color mold (if active and reserved)
        if req.primary_mold in pool.mold_reserved and cell_color in pool.active_cells:
            available = pool.get_available_molds(req.primary_mold)
            take = min(primary_needed, available)
            if take > 0:
                allocation.mold_assignments[req.primary_mold] = take
                primary_allocated += take
                primary_needed -= take
        
        # Priority 2: Use COMMON_MOLD
        if primary_needed > 0:
            available = pool.get_available_molds("COMMON_MOLD")
            take = min(primary_needed, available)
            if take > 0:
                allocation.mold_assignments["COMMON_MOLD"] = (
                    allocation.mold_assignments.get("COMMON_MOLD", 0) + take
                )
                primary_allocated += take
                primary_needed -= take
        
        # Priority 3: Use color molds from inactive cells (if compliant)
        if primary_needed > 0:
            for other_color in CELL_COLORS:
                if other_color == cell_color or other_color == "ORANGE":
                    continue
                if other_color in pool.active_cells:
                    continue  # Active cells have reserved molds
                
                other_mold = f"{other_color}_MOLD"
                mold_info = constants.molds.get(other_mold)
                if mold_info and cell_color in mold_info.compliant_cells:
                    available = pool.get_available_molds(other_mold)
                    take = min(primary_needed, available)
                    if take > 0:
                        allocation.mold_assignments[other_mold] = (
                            allocation.mold_assignments.get(other_mold, 0) + take
                        )
                        primary_allocated += take
                        primary_needed -= take
                
                if primary_needed == 0:
                    break
    
    # Check if primary allocation complete
    if primary_needed > 0:
        allocation.is_valid = False
        allocation.error_message = (
            f"Insufficient {req.primary_mold}: need {req.primary_count}, "
            f"allocated {primary_allocated}"
        )
        return allocation
    
    # Allocate specialty molds if needed
    if req.specialty_mold and req.specialty_count > 0:
        available = pool.get_available_molds(req.specialty_mold)
        if available < req.specialty_count:
            allocation.is_valid = False
            allocation.error_message = (
                f"Insufficient {req.specialty_mold}: need {req.specialty_count}, "
                f"available {available}"
            )
            return allocation
        
        allocation.mold_assignments[req.specialty_mold] = req.specialty_count
    
    return allocation


def _is_cell_compliant(
    cell_color: CellColor,
    mold_depth: str,
    constants: CycleTimeConstants
) -> bool:
    """Check if a cell is compliant for a mold depth.
    
    Args:
        cell_color: Cell to check.
        mold_depth: DEEP or STD.
        constants: CycleTimeConstants with mold compliance info.
    
    Returns:
        True if cell can use the required mold depth.
    """
    if mold_depth == "DEEP":
        mold_info = constants.molds.get("DEEP_MOLD")
        if mold_info:
            return cell_color in mold_info.compliant_cells
        return False
    else:
        # STD - check color mold or ORANGE_MOLD
        if cell_color == "ORANGE":
            mold_info = constants.molds.get("ORANGE_MOLD")
        else:
            mold_info = constants.molds.get(f"{cell_color}_MOLD")
        
        if mold_info:
            return cell_color in mold_info.compliant_cells
        return False


def get_compliant_cells_for_job(
    job: Job,
    calc: CalculatedFields,
    constants: CycleTimeConstants,
    active_cells: set[CellColor],
    operator_inputs: 'OperatorInputs | None' = None
) -> list[CellColor]:
    """Get list of cells that can run a job.
    
    Considers:
    - Mold depth compliance
    - ORANGE_ELIGIBLE flag
    - ORANGE mold type restrictions
    - Active cell status
    
    Args:
        job: Job to check.
        calc: Calculated fields for the job.
        constants: CycleTimeConstants with compliance info.
        active_cells: Set of active cells.
        operator_inputs: Optional OperatorInputs with ORANGE mold settings.
    
    Returns:
        List of compliant cell colors (intersection with active cells).
    """
    compliant = []
    
    for cell_color in active_cells:
        # Check ORANGE restriction
        if cell_color == "ORANGE":
            if not job.orange_eligible:
                continue
            # Check mold type restrictions for ORANGE
            if operator_inputs and not operator_inputs.is_job_allowed_on_orange(job.mold_type):
                continue
        
        # Check mold compliance
        if not _is_cell_compliant(cell_color, calc.mold_depth, constants):
            continue
        
        compliant.append(cell_color)
    
    return compliant


@dataclass
class CellCapacity:
    """Capacity information for a single cell.
    
    Attributes:
        cell_color: Cell identifier.
        is_active: Whether cell is active.
        table1_available: Whether table 1 is available.
        table2_available: Whether table 2 is available.
        table1_job: Job currently on table 1 (ON_TABLE_TODAY).
        table2_job: Job currently on table 2 (ON_TABLE_TODAY).
        estimated_panels_per_shift: Estimated panels this cell can produce.
    """
    cell_color: CellColor
    is_active: bool = False
    table1_available: bool = True
    table2_available: bool = True
    table1_job: Job | None = None
    table2_job: Job | None = None
    estimated_panels_per_shift: int = 0


def calculate_cell_capacities(
    active_cells: set[CellColor],
    jobs_on_tables: dict[str, Job],
    constants: CycleTimeConstants,
    shift_minutes: int
) -> dict[CellColor, CellCapacity]:
    """Calculate capacity for each active cell.
    
    Args:
        active_cells: Set of active cell colors.
        jobs_on_tables: Dict mapping table_id to ON_TABLE_TODAY job.
        constants: CycleTimeConstants for timing estimates.
        shift_minutes: Available shift minutes.
    
    Returns:
        Dict of cell color to CellCapacity.
    """
    capacities = {}
    
    for cell_color in CELL_COLORS:
        cap = CellCapacity(
            cell_color=cell_color,
            is_active=(cell_color in active_cells)
        )
        
        # Check for ON_TABLE_TODAY jobs
        table1_id = f"{cell_color}_1"
        table2_id = f"{cell_color}_2"
        
        if table1_id in jobs_on_tables:
            cap.table1_job = jobs_on_tables[table1_id]
            cap.table1_available = False
        
        if table2_id in jobs_on_tables:
            cap.table2_job = jobs_on_tables[table2_id]
            cap.table2_available = False
        
        # Estimate panels per shift (rough calculation)
        # Assumes average panel takes ~50-60 minutes with interleaving
        if cap.is_active:
            cap.estimated_panels_per_shift = shift_minutes // 55
        
        capacities[cell_color] = cap
    
    return capacities
