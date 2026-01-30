# Method Evaluation and Comparison.
# Version: 1.0.0
# Evaluates and compares results from all scheduling methods.

from dataclasses import dataclass, field
from typing import Literal

from .constants import CellColor
from .calculated_fields import (
    SCHED_CLASS_A, SCHED_CLASS_B, SCHED_CLASS_C, SCHED_CLASS_D, SCHED_CLASS_E,
    PRIORITY_PAST_DUE, PRIORITY_TODAY, PRIORITY_EXPEDITE, PRIORITY_FUTURE
)
from .multi_cell_scheduler import MultiCellScheduleResult
from .method_variants import SchedulingMethod, SchedulingVariant


@dataclass
class PriorityMetrics:
    """Metrics for jobs by priority level.
    
    Attributes:
        scheduled: Number of jobs scheduled.
        not_scheduled: Number of jobs not scheduled.
        panels_scheduled: Total panels scheduled.
    """
    scheduled: int = 0
    not_scheduled: int = 0
    panels_scheduled: int = 0


@dataclass
class ClassMetrics:
    """Metrics for panels by SCHED_CLASS.
    
    Attributes:
        class_a: Panels of class A.
        class_b: Panels of class B.
        class_c: Panels of class C.
        class_d: Panels of class D.
        class_e: Panels of class E.
    """
    class_a: int = 0
    class_b: int = 0
    class_c: int = 0
    class_d: int = 0
    class_e: int = 0
    
    @property
    def total(self) -> int:
        return self.class_a + self.class_b + self.class_c + self.class_d + self.class_e


@dataclass
class EfficiencyMetrics:
    """Efficiency metrics for a schedule.
    
    Attributes:
        forced_table_idle: Total forced table idle minutes.
        forced_operator_idle: Total forced operator idle minutes.
        utilization_pct: Operator utilization percentage.
    """
    forced_table_idle: int = 0
    forced_operator_idle: int = 0
    utilization_pct: float = 0.0


@dataclass
class MethodEvaluation:
    """Complete evaluation of a scheduling method result.
    
    Attributes:
        method: Scheduling method used.
        variant: Variant used (job-first or table-first).
        status: Schedule status.
        priority_metrics: Dict of priority level to metrics.
        class_metrics: Metrics by SCHED_CLASS.
        cell_panels: Dict of cell color to panels produced.
        efficiency: Efficiency metrics.
        total_panels: Total panels scheduled.
        total_jobs_scheduled: Total jobs scheduled.
        total_jobs_unscheduled: Total jobs not scheduled.
    """
    method: SchedulingMethod
    variant: SchedulingVariant
    status: str
    priority_metrics: dict[int, PriorityMetrics] = field(default_factory=dict)
    class_metrics: ClassMetrics = field(default_factory=ClassMetrics)
    cell_panels: dict[CellColor, int] = field(default_factory=dict)
    efficiency: EfficiencyMetrics = field(default_factory=EfficiencyMetrics)
    total_panels: int = 0
    total_jobs_scheduled: int = 0
    total_jobs_unscheduled: int = 0
    
    @property
    def method_name(self) -> str:
        names = {
            SchedulingMethod.PRIORITY_FIRST: "Priority First",
            SchedulingMethod.MINIMUM_FORCED_IDLE: "Minimum Forced Idle",
            SchedulingMethod.MAXIMUM_OUTPUT: "Maximum Output",
            SchedulingMethod.MOST_RESTRICTED_MIX: "Most Restricted Mix"
        }
        return names.get(self.method, str(self.method))
    
    @property
    def variant_name(self) -> str:
        return "Job First" if self.variant == SchedulingVariant.JOB_FIRST else "Table First"
    
    @property
    def full_name(self) -> str:
        return f"{self.method_name} ({self.variant_name})"


def evaluate_result(
    result: MultiCellScheduleResult,
    method: SchedulingMethod,
    variant: SchedulingVariant
) -> MethodEvaluation:
    """Evaluate a scheduling result.
    
    Args:
        result: MultiCellScheduleResult to evaluate.
        method: Scheduling method used.
        variant: Variant used.
    
    Returns:
        MethodEvaluation with all metrics.
    """
    evaluation = MethodEvaluation(
        method=method,
        variant=variant,
        status=result.status,
        total_panels=result.total_panels
    )
    
    # Initialize priority metrics
    for priority in [PRIORITY_PAST_DUE, PRIORITY_TODAY, PRIORITY_EXPEDITE, PRIORITY_FUTURE]:
        evaluation.priority_metrics[priority] = PriorityMetrics()
    
    # Process scheduled jobs
    for assignment in result.job_assignments:
        calc = assignment.calc
        panels = assignment.panels_to_schedule
        
        # Priority metrics
        pm = evaluation.priority_metrics.get(calc.priority)
        if pm:
            pm.scheduled += 1
            pm.panels_scheduled += panels
        
        # Class metrics
        if calc.sched_class == SCHED_CLASS_A:
            evaluation.class_metrics.class_a += panels
        elif calc.sched_class == SCHED_CLASS_B:
            evaluation.class_metrics.class_b += panels
        elif calc.sched_class == SCHED_CLASS_C:
            evaluation.class_metrics.class_c += panels
        elif calc.sched_class == SCHED_CLASS_D:
            evaluation.class_metrics.class_d += panels
        elif calc.sched_class == SCHED_CLASS_E:
            evaluation.class_metrics.class_e += panels
    
    evaluation.total_jobs_scheduled = len(result.job_assignments)
    
    # Process unscheduled jobs
    for item in result.unscheduled_jobs:
        # Handle both (job, reason) and (job, calc, reason) formats
        job = item[0]
        evaluation.total_jobs_unscheduled += 1
    
    # Cell panels
    for cell_color, cell_result in result.cell_results.items():
        evaluation.cell_panels[cell_color] = cell_result.total_panels
    
    # Efficiency metrics
    total_table_idle = 0
    total_operator_idle = 0
    total_shift_minutes = 0
    total_operator_minutes = 0
    
    for cell_color, cell_result in result.cell_results.items():
        if cell_result.is_feasible:
            # forced_table_idle is a dict of table_id to idle minutes
            for table_id, idle in cell_result.forced_table_idle.items():
                total_table_idle += idle
            total_operator_idle += cell_result.forced_operator_idle
            total_shift_minutes += result.shift_minutes
            total_operator_minutes += cell_result.total_operator_time
    
    evaluation.efficiency.forced_table_idle = total_table_idle
    evaluation.efficiency.forced_operator_idle = total_operator_idle
    
    if total_shift_minutes > 0:
        # Utilization = operator working time / (shift * num_active_cells)
        evaluation.efficiency.utilization_pct = (
            total_operator_minutes / total_shift_minutes * 100
        )
    
    return evaluation


def compare_methods(
    evaluations: list[MethodEvaluation]
) -> dict[str, MethodEvaluation]:
    """Compare methods and identify best performers.
    
    Args:
        evaluations: List of MethodEvaluation to compare.
    
    Returns:
        Dict with keys for each "best" category and the winning evaluation.
    """
    if not evaluations:
        return {}
    
    comparisons = {}
    
    # Best by total panels
    comparisons["most_panels"] = max(evaluations, key=lambda e: e.total_panels)
    
    # Best by priority 0 jobs scheduled
    comparisons["best_priority_0"] = max(
        evaluations,
        key=lambda e: e.priority_metrics.get(PRIORITY_PAST_DUE, PriorityMetrics()).scheduled
    )
    
    # Best by efficiency (lowest idle)
    comparisons["most_efficient"] = min(
        evaluations,
        key=lambda e: e.efficiency.forced_table_idle + e.efficiency.forced_operator_idle
    )
    
    # Best by jobs scheduled
    comparisons["most_jobs"] = max(evaluations, key=lambda e: e.total_jobs_scheduled)
    
    return comparisons


def generate_evaluation_report(
    evaluations: list[MethodEvaluation],
    include_comparison: bool = True
) -> str:
    """Generate a text report comparing all method evaluations.
    
    Args:
        evaluations: List of evaluations to report.
        include_comparison: Whether to include comparison summary.
    
    Returns:
        Multi-line report string.
    """
    lines = []
    lines.append("=" * 80)
    lines.append("SCHEDULING METHOD EVALUATION REPORT")
    lines.append("=" * 80)
    lines.append("")
    
    # Summary table
    lines.append("SUMMARY:")
    lines.append("-" * 80)
    header = f"{'Method':<35} {'Status':<12} {'Panels':<8} {'Jobs':<6} {'Unsched':<8}"
    lines.append(header)
    lines.append("-" * 80)
    
    for eval in evaluations:
        row = (
            f"{eval.full_name:<35} "
            f"{eval.status:<12} "
            f"{eval.total_panels:<8} "
            f"{eval.total_jobs_scheduled:<6} "
            f"{eval.total_jobs_unscheduled:<8}"
        )
        lines.append(row)
    
    lines.append("")
    
    # Priority breakdown
    lines.append("SCHEDULE EFFECTIVENESS BY PRIORITY:")
    lines.append("-" * 80)
    
    priority_names = {
        PRIORITY_PAST_DUE: "Priority 0 (Past Due)",
        PRIORITY_TODAY: "Priority 1 (Today)",
        PRIORITY_EXPEDITE: "Priority 2 (Expedite)",
        PRIORITY_FUTURE: "Priority 3 (Future)"
    }
    
    for eval in evaluations:
        lines.append(f"\n{eval.full_name}:")
        for priority, name in priority_names.items():
            pm = eval.priority_metrics.get(priority, PriorityMetrics())
            lines.append(
                f"  {name}: {pm.scheduled} scheduled, "
                f"{pm.not_scheduled} not scheduled, {pm.panels_scheduled} panels"
            )
    
    lines.append("")
    
    # Panels by class
    lines.append("PANELS BY SCHED_CLASS:")
    lines.append("-" * 80)
    header = f"{'Method':<35} {'A':<6} {'B':<6} {'C':<6} {'D':<6} {'E':<6} {'Total':<8}"
    lines.append(header)
    lines.append("-" * 80)
    
    for eval in evaluations:
        cm = eval.class_metrics
        row = (
            f"{eval.full_name:<35} "
            f"{cm.class_a:<6} "
            f"{cm.class_b:<6} "
            f"{cm.class_c:<6} "
            f"{cm.class_d:<6} "
            f"{cm.class_e:<6} "
            f"{cm.total:<8}"
        )
        lines.append(row)
    
    lines.append("")
    
    # Panels by cell
    lines.append("PANELS BY CELL:")
    lines.append("-" * 80)
    
    # Get all cells
    all_cells = set()
    for eval in evaluations:
        all_cells.update(eval.cell_panels.keys())
    all_cells = sorted(all_cells)
    
    header = f"{'Method':<35} " + " ".join(f"{c:<8}" for c in all_cells)
    lines.append(header)
    lines.append("-" * 80)
    
    for eval in evaluations:
        cells = " ".join(f"{eval.cell_panels.get(c, 0):<8}" for c in all_cells)
        lines.append(f"{eval.full_name:<35} {cells}")
    
    lines.append("")
    
    # Efficiency
    lines.append("SCHEDULE EFFICIENCY:")
    lines.append("-" * 80)
    header = f"{'Method':<35} {'Table Idle':<12} {'Op Idle':<12} {'Util %':<10}"
    lines.append(header)
    lines.append("-" * 80)
    
    for eval in evaluations:
        eff = eval.efficiency
        row = (
            f"{eval.full_name:<35} "
            f"{eff.forced_table_idle:<12} "
            f"{eff.forced_operator_idle:<12} "
            f"{eff.utilization_pct:.1f}%"
        )
        lines.append(row)
    
    # Comparison
    if include_comparison and evaluations:
        lines.append("")
        lines.append("=" * 80)
        lines.append("COMPARISON SUMMARY:")
        lines.append("=" * 80)
        
        comparisons = compare_methods(evaluations)
        
        for category, winner in comparisons.items():
            category_name = category.replace("_", " ").title()
            lines.append(f"  {category_name}: {winner.full_name}")
    
    return "\n".join(lines)


def rank_methods(
    evaluations: list[MethodEvaluation],
    weights: dict[str, float] | None = None
) -> list[tuple[MethodEvaluation, float]]:
    """Rank methods by weighted score.
    
    Default weights prioritize:
    - Total panels (40%)
    - Priority 0 jobs (30%)
    - Efficiency (20%)
    - Jobs scheduled (10%)
    
    Args:
        evaluations: Evaluations to rank.
        weights: Optional custom weights.
    
    Returns:
        List of (evaluation, score) sorted by score descending.
    """
    if not evaluations:
        return []
    
    default_weights = {
        "panels": 0.4,
        "priority_0": 0.3,
        "efficiency": 0.2,
        "jobs": 0.1
    }
    weights = weights or default_weights
    
    # Normalize metrics
    max_panels = max(e.total_panels for e in evaluations) or 1
    max_p0 = max(
        e.priority_metrics.get(PRIORITY_PAST_DUE, PriorityMetrics()).scheduled
        for e in evaluations
    ) or 1
    max_idle = max(
        e.efficiency.forced_table_idle + e.efficiency.forced_operator_idle
        for e in evaluations
    ) or 1
    max_jobs = max(e.total_jobs_scheduled for e in evaluations) or 1
    
    scores = []
    for eval in evaluations:
        score = 0.0
        
        # Panels (higher is better)
        score += weights.get("panels", 0) * (eval.total_panels / max_panels)
        
        # Priority 0 (higher is better)
        p0 = eval.priority_metrics.get(PRIORITY_PAST_DUE, PriorityMetrics()).scheduled
        score += weights.get("priority_0", 0) * (p0 / max_p0)
        
        # Efficiency (lower idle is better, so invert)
        idle = eval.efficiency.forced_table_idle + eval.efficiency.forced_operator_idle
        score += weights.get("efficiency", 0) * (1 - idle / max_idle)
        
        # Jobs (higher is better)
        score += weights.get("jobs", 0) * (eval.total_jobs_scheduled / max_jobs)
        
        scores.append((eval, score))
    
    scores.sort(key=lambda x: -x[1])
    return scores
