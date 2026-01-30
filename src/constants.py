# Load and structure constants from YAML config file.
# Version: 1.0.0
# Provides lookup functions for task times, molds, fixtures, and holidays.

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional
import yaml

from .errors import ConfigurationError, FileLoadError


# Type aliases for clarity
CellColor = Literal["RED", "BLUE", "GREEN", "BLACK", "PURPLE", "ORANGE"]
MoldDepth = Literal["DEEP", "STD"]
Pattern = Literal["D", "S", "V"]
SchedClass = Literal["A", "B", "C", "D", "E"]

# All valid cell colors
CELL_COLORS: tuple[CellColor, ...] = ("RED", "BLUE", "GREEN", "BLACK", "PURPLE", "ORANGE")


@dataclass(frozen=True)
class TaskTiming:
    """Task timing values for a specific WIRE_DIAMETER/EQUIVALENT combination.
    
    Attributes:
        wire_diameter: Wire diameter condition (e.g., "<=4", ">4,<8", ">=8").
        equivalent: Difficulty factor condition.
        setup: SETUP task duration in minutes (operator required).
        layout: LAYOUT task duration in minutes (operator required).
        pour: POUR task base duration in minutes (multiply by MOLDS count).
        cure: CURE task duration in minutes (no operator required).
        unload: UNLOAD task duration in minutes (operator required).
        sched_constant: Scheduling constant for BUILD_LOAD calculation.
        sched_class: Scheduling class (A, B, C, D, or E).
        pull_ahead: Days to subtract from BUILD_DATE calculation.
    """
    wire_diameter: str
    equivalent: str
    setup: int
    layout: int
    pour: float
    cure: int
    unload: int
    sched_constant: int
    sched_class: SchedClass
    pull_ahead: float


@dataclass(frozen=True)
class MoldInfo:
    """Information about a mold type.
    
    Attributes:
        mold_name: Unique mold identifier.
        mold_depth: DEEP or STD.
        wire_diameter_range: Wire diameter range this mold applies to.
        quantity: Total quantity available.
        compliant_cells: Set of cell colors where this mold can be used.
    """
    mold_name: str
    mold_depth: MoldDepth
    wire_diameter_range: str
    quantity: int
    compliant_cells: frozenset[CellColor]


@dataclass(frozen=True)
class FixtureLimit:
    """Concurrent usage limit for a fixture pattern.
    
    Attributes:
        pattern: D, S, or V.
        description: Human-readable description.
        max_concurrent: Maximum tables that can use this pattern concurrently.
    """
    pattern: Pattern
    description: str
    max_concurrent: int


@dataclass(frozen=True)
class Holiday:
    """Company holiday/closure date.
    
    Attributes:
        label: Human-readable name.
        date: The date of the holiday.
    """
    label: str
    date: date


@dataclass
class CycleTimeConstants:
    """Container for all cycle time constants loaded from YAML.
    
    Attributes:
        task_timings: List of TaskTiming objects.
        molds: Dict mapping mold_name to MoldInfo.
        fixtures: Dict mapping pattern to FixtureLimit.
        holidays: Set of holiday dates.
        shifts: Dict of shift type to minutes.
        summer_cure_multiplier: Multiplier for CURE time in summer mode.
        pour_cutoff_minutes: Minimum minutes remaining to start POUR.
        max_layout_pour_gap: Maximum gap between LAYOUT end and POUR start.
        admin_password: Password for settings page.
    """
    task_timings: list[TaskTiming]
    molds: dict[str, MoldInfo]  # Keyed by mold_name
    fixtures: dict[str, FixtureLimit]  # Keyed by pattern
    holidays: set[date]
    holiday_list: list[Holiday]
    shifts: dict[str, int]
    summer_cure_multiplier: float
    pour_cutoff_minutes: int
    max_layout_pour_gap: int
    admin_password: str
    
    def get_task_timing(self, wire_diameter: float, equivalent: float) -> TaskTiming:
        """Get task timing for given wire diameter and equivalent.
        
        Args:
            wire_diameter: Wire diameter value.
            equivalent: Difficulty equivalent value.
            
        Returns:
            Matching TaskTiming object.
            
        Raises:
            ConfigurationError: If no matching timing found.
        """
        # Determine wire diameter category
        if wire_diameter <= 4:
            wd_category = "<=4"
        elif wire_diameter < 8:
            wd_category = ">4,<8"
        else:
            wd_category = ">=8"
        
        # Round equivalent UP to next tier for conservative scheduling
        # Tiers: 1.0, 1.25, 1.5, 1.75, >=2
        if equivalent <= 1.0:
            eq_target = 1.0
        elif equivalent <= 1.25:
            eq_target = 1.25
        elif equivalent <= 1.5:
            eq_target = 1.5
        elif equivalent <= 1.75:
            eq_target = 1.75
        else:
            eq_target = 2.0  # Will match ">=2"
        
        # Find matching timing
        for timing in self.task_timings:
            if timing.wire_diameter != wd_category:
                continue
            
            eq_str = str(timing.equivalent)
            if eq_target >= 2.0 and eq_str == ">=2":
                return timing
            elif eq_str != ">=2":
                try:
                    if abs(float(eq_str) - eq_target) < 0.01:
                        return timing
                except ValueError:
                    continue
        
        # Fallback to highest equivalent if no match
        for timing in self.task_timings:
            if timing.wire_diameter == wd_category and str(timing.equivalent) == ">=2":
                return timing
        
        raise ConfigurationError(f"No timing found for wire_diameter={wire_diameter}, equivalent={equivalent}")
    
    def get_mold_depth(self, wire_diameter: float) -> str:
        """Determine mold depth based on wire diameter.
        
        Args:
            wire_diameter: Wire diameter value from job.
        
        Returns:
            "DEEP" if wire_diameter >= 8, else "STD".
        """
        return "DEEP" if wire_diameter >= 8 else "STD"
    
    def get_mold(self, mold_name: str) -> MoldInfo:
        """Get mold info by name.
        
        Args:
            mold_name: Mold name to look up.
            
        Returns:
            Matching MoldInfo object.
            
        Raises:
            ConfigurationError: If mold not found.
        """
        if mold_name in self.molds:
            return self.molds[mold_name]
        raise ConfigurationError(f"Mold not found: {mold_name}")
    
    def get_fixture(self, pattern: str) -> FixtureLimit:
        """Get fixture limit by pattern.
        
        Args:
            pattern: Pattern (D, S, or V).
            
        Returns:
            Matching FixtureLimit object.
            
        Raises:
            ConfigurationError: If pattern not found.
        """
        if pattern in self.fixtures:
            return self.fixtures[pattern]
        raise ConfigurationError(f"Fixture pattern not found: {pattern}")
    
    def get_fixture_limit(self, pattern: str) -> int:
        """Get the maximum concurrent usage for a fixture pattern.
        
        Args:
            pattern: Pattern character (D, S, or V).
        
        Returns:
            Maximum number of tables that can use this pattern concurrently.
        
        Raises:
            ConfigurationError: If pattern not found.
        """
        if pattern not in self.fixtures:
            raise ConfigurationError(f"Unknown pattern '{pattern}'. Valid patterns: D, S, V")
        return self.fixtures[pattern].max_concurrent
    
    def get_molds_for_cell(self, cell_color: str, mold_depth: str) -> dict[str, int]:
        """Get available molds for a cell and depth.
        
        Args:
            cell_color: Cell color (RED, BLUE, etc.).
            mold_depth: DEEP or STD.
        
        Returns:
            Dictionary mapping mold_name to available quantity for compliant molds.
        """
        result = {}
        for mold_name, mold_info in self.molds.items():
            if mold_info.mold_depth == mold_depth:
                if cell_color in mold_info.compliant_cells:
                    result[mold_name] = mold_info.quantity
        return result
    
    def is_business_day(self, check_date: date) -> bool:
        """Check if a date is a valid business day.
        
        Args:
            check_date: Date to check.
        
        Returns:
            True if weekday (Mon-Fri) and not a holiday.
        """
        # Monday = 0, Friday = 4
        if check_date.weekday() > 4:
            return False
        if check_date in self.holidays:
            return False
        return True
    
    def is_holiday(self, check_date: date) -> bool:
        """Check if a date is a holiday.
        
        Args:
            check_date: Date to check.
            
        Returns:
            True if the date is a holiday.
        """
        return check_date in self.holidays
    
    def get_shift_minutes(self, shift_type: str) -> int:
        """Get shift duration in minutes.
        
        Args:
            shift_type: 'standard' or 'overtime'.
            
        Returns:
            Shift duration in minutes.
        """
        return self.shifts.get(shift_type, self.shifts.get('standard', 440))


def load_constants_from_yaml(yaml_path: str | Path) -> CycleTimeConstants:
    """Load cycle time constants from YAML file.
    
    Args:
        yaml_path: Path to the YAML config file.
        
    Returns:
        CycleTimeConstants object with all loaded data.
        
    Raises:
        FileLoadError: If file cannot be read.
        ConfigurationError: If file format is invalid.
    """
    yaml_path = Path(yaml_path)
    
    if not yaml_path.exists():
        raise FileLoadError(f"Config file not found: {yaml_path}")
    
    try:
        with open(yaml_path, 'r') as f:
            data = yaml.safe_load(f)
    except Exception as e:
        raise FileLoadError(f"Failed to read config file: {e}")
    
    # Parse task timings
    task_timings = []
    for t in data.get('task_timings', []):
        task_timings.append(TaskTiming(
            wire_diameter=str(t['wire_diameter']),
            equivalent=str(t['equivalent']),
            setup=int(t['setup']),
            layout=int(t['layout']),
            pour=float(t['pour_per_mold']),
            cure=int(t['cure']),
            unload=int(t['unload']),
            sched_constant=int(t['sched_constant']),
            sched_class=t['sched_class'],
            pull_ahead=float(t['pull_ahead']),
        ))
    
    # Parse molds - create dict keyed by mold_name
    molds = {}
    for m in data.get('molds', []):
        compliant = frozenset(
            cell for cell, is_compliant in m.get('cells', {}).items()
            if is_compliant
        )
        mold_info = MoldInfo(
            mold_name=m['name'],
            mold_depth=m['depth'],
            wire_diameter_range=m['wire_diameter'],
            quantity=int(m['quantity']),
            compliant_cells=compliant,
        )
        molds[m['name']] = mold_info
    
    # Parse fixtures - create dict keyed by pattern
    fixtures = {}
    for f in data.get('fixtures', []):
        fixture_info = FixtureLimit(
            pattern=f['pattern'],
            description=f['description'],
            max_concurrent=int(f['quantity']),
        )
        fixtures[f['pattern']] = fixture_info
    
    # Parse holidays
    holiday_list = []
    holidays = set()
    for h in data.get('holidays', []):
        date_str = h['date']
        if isinstance(date_str, str):
            holiday_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        elif isinstance(date_str, date):
            holiday_date = date_str
        else:
            holiday_date = date_str.date() if hasattr(date_str, 'date') else date_str
        
        holiday_list.append(Holiday(label=h['label'], date=holiday_date))
        holidays.add(holiday_date)
    
    # Get other settings
    shifts = data.get('shifts', {'standard': 440, 'overtime': 500})
    
    return CycleTimeConstants(
        task_timings=task_timings,
        molds=molds,
        fixtures=fixtures,
        holidays=holidays,
        holiday_list=holiday_list,
        shifts=shifts,
        summer_cure_multiplier=data.get('summer_cure_multiplier', 1.5),
        pour_cutoff_minutes=data.get('pour_cutoff_minutes', 40),
        max_layout_pour_gap=data.get('max_layout_pour_gap', 60),
        admin_password=data.get('admin_password', 'admin'),
    )


def save_constants_to_yaml(constants: CycleTimeConstants, yaml_path: str | Path) -> None:
    """Save cycle time constants to YAML file.
    
    Args:
        constants: CycleTimeConstants object to save.
        yaml_path: Path to save the YAML config file.
    """
    data = {
        'admin_password': constants.admin_password,
        'shifts': constants.shifts,
        'summer_cure_multiplier': constants.summer_cure_multiplier,
        'pour_cutoff_minutes': constants.pour_cutoff_minutes,
        'max_layout_pour_gap': constants.max_layout_pour_gap,
        'task_timings': [],
        'molds': [],
        'fixtures': [],
        'holidays': [],
    }
    
    # Task timings
    for t in constants.task_timings:
        data['task_timings'].append({
            'wire_diameter': t.wire_diameter,
            'equivalent': t.equivalent if t.equivalent == ">=2" else float(t.equivalent),
            'setup': t.setup,
            'layout': t.layout,
            'pour_per_mold': t.pour,
            'cure': t.cure,
            'unload': t.unload,
            'sched_constant': t.sched_constant,
            'sched_class': t.sched_class,
            'pull_ahead': t.pull_ahead,
        })
    
    # Molds - iterate dict values
    for m in constants.molds.values():
        data['molds'].append({
            'name': m.mold_name,
            'depth': m.mold_depth,
            'wire_diameter': m.wire_diameter_range,
            'quantity': m.quantity,
            'cells': {cell: cell in m.compliant_cells for cell in CELL_COLORS},
        })
    
    # Fixtures - iterate dict values
    for f in constants.fixtures.values():
        data['fixtures'].append({
            'pattern': f.pattern,
            'description': f.description,
            'quantity': f.max_concurrent,
        })
    
    # Holidays
    for h in constants.holiday_list:
        data['holidays'].append({
            'label': h.label,
            'date': h.date.isoformat(),
        })
    
    yaml_path = Path(yaml_path)
    with open(yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


# Backward compatibility - load from YAML by default, fallback to Excel
def load_cycle_time_constants(path: str | Path) -> CycleTimeConstants:
    """Load cycle time constants from file.
    
    Automatically detects YAML or Excel format.
    
    Args:
        path: Path to config file (YAML or Excel).
        
    Returns:
        CycleTimeConstants object.
    """
    path = Path(path)
    
    # Check for YAML first
    if path.suffix in ('.yaml', '.yml'):
        return load_constants_from_yaml(path)
    
    # Check for YAML in same directory
    yaml_path = path.parent / 'constants.yaml'
    if yaml_path.exists():
        return load_constants_from_yaml(yaml_path)
    
    # Fallback to Excel loading (legacy)
    return _load_from_excel(path)


def _load_from_excel(excel_path: Path) -> CycleTimeConstants:
    """Legacy Excel loader for backward compatibility."""
    import pandas as pd
    
    if not excel_path.exists():
        raise FileLoadError(f"File not found: {excel_path}")
    
    try:
        # Load all sheets
        task_df = pd.read_excel(excel_path, sheet_name='TASK')
        mold_df = pd.read_excel(excel_path, sheet_name='MOLDS')
        fixture_df = pd.read_excel(excel_path, sheet_name='FIXTURES')
        holiday_df = pd.read_excel(excel_path, sheet_name='HOLIDAYS')
    except Exception as e:
        raise FileLoadError(f"Failed to read Excel file: {e}")
    
    # Parse task timings
    task_timings = []
    for _, row in task_df.iterrows():
        task_timings.append(TaskTiming(
            wire_diameter=str(row['WIRE_DIAMETER']),
            equivalent=str(row['EQUIVALENT']),
            setup=int(row['SETUP']),
            layout=int(row['LAYOUT']),
            pour=float(row['POUR']),
            cure=int(row['CURE']),
            unload=int(row['UNLOAD']),
            sched_constant=int(row['SCHED_CONSTANT']),
            sched_class=row['SCHED_CLASS'],
            pull_ahead=float(row['PULL_AHEAD']),
        ))
    
    # Parse molds - create dict keyed by mold_name
    molds = {}
    for _, row in mold_df.iterrows():
        compliant = frozenset(
            cell for cell in CELL_COLORS
            if row.get(f'{cell}_COMPLIANT', False)
        )
        mold_info = MoldInfo(
            mold_name=row['MOLD_NAME'],
            mold_depth=row['MOLD_DEPTH'],
            wire_diameter_range=row['WIRE_DIAMETER'],
            quantity=int(row['MOLD_QTY']),
            compliant_cells=compliant,
        )
        molds[row['MOLD_NAME']] = mold_info
    
    # Parse fixtures - create dict keyed by pattern
    fixtures = {}
    for _, row in fixture_df.iterrows():
        fixture_info = FixtureLimit(
            pattern=row['PATTERN'],
            description=row['DESCRIPTION'],
            max_concurrent=int(row['FIXTURE_QTY']),
        )
        fixtures[row['PATTERN']] = fixture_info
    
    # Parse holidays
    holiday_list = []
    holidays = set()
    for _, row in holiday_df.iterrows():
        h_date = row['Date']
        if isinstance(h_date, str):
            h_date = datetime.strptime(h_date, "%Y-%m-%d").date()
        elif hasattr(h_date, 'date'):
            h_date = h_date.date()
        holiday_list.append(Holiday(label=row['Label'], date=h_date))
        holidays.add(h_date)
    
    return CycleTimeConstants(
        task_timings=task_timings,
        molds=molds,
        fixtures=fixtures,
        holidays=holidays,
        holiday_list=holiday_list,
        shifts={'standard': 440, 'overtime': 500},
        summer_cure_multiplier=1.5,
        pour_cutoff_minutes=40,
        max_layout_pour_gap=60,
        admin_password='admin',
    )
