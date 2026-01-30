# Cell Scheduling Engine - Core Package
# Version: 1.0.0

"""
Cell scheduling engine for thermoforming production optimization.

Uses Google OR-Tools CP-SAT solver to schedule six production cells
(RED, BLUE, GREEN, BLACK, PURPLE, ORANGE) to meet ship dates and
maximize panel output.
"""

__version__ = "1.0.0"

from .errors import (
    SchedulingError,
    ValidationError,
    ConfigurationError,
    InfeasibleScheduleError,
    ResourceExhaustedError,
    FileLoadError,
    ConstraintViolationError,
    SolverTimeoutError,
)

from .constants import (
    CycleTimeConstants,
    TaskTiming,
    MoldInfo,
    FixtureLimit,
    load_cycle_time_constants,
    CELL_COLORS,
)

from .data_loader import (
    Job,
    DailyProductionLoad,
    load_daily_production,
)

from .calculated_fields import (
    CalculatedFields,
    calculate_fields_for_job,
    calculate_all_fields,
    get_jobs_with_calculations,
)

from .validator import (
    OperatorInputs,
    ValidationResult,
    validate_production_load,
)

from .scheduler import (
    CellScheduleResult,
    ScheduledPanel,
    ScheduledTask,
    JobAssignment,
    schedule_single_cell,
)

from .resources import (
    ResourcePool,
    MoldAllocation,
    create_resource_pool,
    allocate_molds_for_job,
    get_compliant_cells_for_job,
)

from .multi_cell_scheduler import (
    MultiCellScheduleResult,
    JobCellAssignment,
    schedule_all_cells,
    get_schedule_summary,
)

from .solution_parser import (
    GanttData,
    GanttTask,
    extract_gantt_data,
    generate_text_gantt,
    generate_schedule_summary,
    validate_schedule,
    export_schedule_to_dict,
)

from .method_variants import (
    SchedulingMethod,
    SchedulingVariant,
    run_method,
    run_all_methods,
    get_table_order,
)

from .method_evaluation import (
    MethodEvaluation,
    PriorityMetrics,
    ClassMetrics,
    EfficiencyMetrics,
    evaluate_result,
    compare_methods,
    generate_evaluation_report,
    rank_methods,
)

from .output_generator import (
    generate_schedule_report,
    generate_gantt_text,
    generate_html_gantt,
    export_to_json,
    generate_comparison_report,
    save_all_outputs,
)
