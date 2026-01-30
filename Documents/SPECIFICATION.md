---
name: Cell Scheduling Engine Specification
description: Technical specification and implementation plan for thermoforming production cell scheduler using OR-Tools CP-SAT solver
version: 1.0.0
date: 2026-01-22
repository: https://github.com/rmccann-hub/scheduling-engineV2
---

# Cell Scheduling Engine Specification

## Overview

Schedule six thermoforming production cells (RED, BLUE, GREEN, BLACK, PURPLE, ORANGE) to meet required ship dates while maximizing panel output. Each cell has two tables sharing one operator who alternates between them, leveraging the CURE task (no operator required) to interleave work.

This is a fresh build using Google OR-Tools CP-SAT constraint programming solver. Target runtime: Python 3.12+.

---

## System Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                         INPUT LAYER                             │
│  data_loader.py → validator.py → calculated_fields.py           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        CORE ENGINE                              │
│  constraints.py → scheduler.py (OR-Tools) → solution_parser.py  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       OUTPUT LAYER                              │
│  report_generator.py → pdf_output.py → gantt_generator.py       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        UI LAYER                                 │
│  app.py (Flask/Streamlit) → operator inputs → method selection  │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure

```text
scheduling-engineV2/
├── Documents/           # Documentation
│   ├── PROGRAM_REQUIREMENTS.md
│   ├── CELL_RULES_SIMPLIFIED.md
│   ├── SCHEDULING_PROTOCOL.md
│   ├── CYCLE_TIME_CONSTANTS.xlsx
│   ├── DAILY_PRODUCTION_LOAD.xlsx
│   └── SPECIFICATION.md
├── src/
│   ├── __init__.py
│   ├── data_loader.py          # Excel loading
│   ├── validator.py            # Input validation
│   ├── calculated_fields.py    # SCHED_QTY, BUILD_DATE, PRIORITY, etc.
│   ├── constants.py            # TASK times, MOLDS, FIXTURES from Excel
│   ├── constraints.py          # OR-Tools constraint builders
│   ├── scheduler.py            # Main scheduling engine
│   ├── solution_parser.py      # Extract schedule from solver
│   ├── report_generator.py     # Format outputs
│   ├── pdf_output.py           # PDF generation
│   ├── gantt_generator.py      # HTML Gantt charts
│   ├── errors.py               # Custom exception classes
│   └── app.py                  # UI entry point
├── tests/
│   ├── test_calculated_fields.py
│   ├── test_constraints.py
│   ├── test_scheduler.py
│   └── test_data/
├── requirements.txt
├── README.md
└── config.py                   # Password-protected editable constants
```

---

## Coding Standards

All code must follow these standards (enforced by skill chain: code-standards → python-coding → error-handling):

| Standard | Requirement |
|----------|-------------|
| Python version | 3.12+ |
| Type hints | Required on all functions/methods |
| Docstrings | Google format on all public functions/classes |
| Error handling | Custom exceptions, fail-fast validation |
| Logging | Structured logging with context |
| Architecture | KISS, DRY, YAGNI, SoC/SRP |

---

## Error Handling Strategy

### Error Classification

| Type | Examples | Strategy |
|------|----------|----------|
| **Validation** | Invalid JOB format, missing required field, out-of-range value | Fail fast with specific field error |
| **Configuration** | Missing CYCLE_TIME_CONSTANTS, invalid MOLD data | Fail at startup with clear message |
| **Scheduling** | No feasible solution, timeout, infeasible constraints | Return partial result with explanation |
| **I/O** | File not found, permission denied, corrupt Excel | Catch specific, log context, user-friendly message |

### Custom Exception Hierarchy

```python
class SchedulingError(Exception):
    """Base exception for scheduling engine."""

class ValidationError(SchedulingError):
    """Invalid input data."""
    def __init__(self, field: str, value: Any, reason: str): ...

class ConfigurationError(SchedulingError):
    """Invalid or missing configuration."""

class InfeasibleScheduleError(SchedulingError):
    """No valid schedule exists for given constraints."""

class ResourceExhaustedError(SchedulingError):
    """Molds or fixtures unavailable."""
```

### User-Facing Messages

| Internal Error | User Message |
|----------------|--------------|
| `ValidationError(field="JOB", ...)` | "Invalid JOB format in row X. Expected format: 123456-01-1" |
| `ConfigurationError` | "Configuration error: [specific issue]. Check CYCLE_TIME_CONSTANTS.xlsx" |
| `InfeasibleScheduleError` | "Cannot create valid schedule. [X] Priority 0 jobs could not be scheduled due to [reason]" |
| `ResourceExhaustedError` | "Insufficient molds available. Need X, only Y available." |

### Logging Strategy

| Level | When to Use | Example |
|-------|-------------|---------|
| ERROR | Operation failed, needs attention | "Failed to load DAILY_PRODUCTION_LOAD.xlsx: {error}" |
| WARNING | Unexpected but handled | "ON_TABLE_TODAY job {job} has ORANGE_ELIGIBLE=false on ORANGE cell" |
| INFO | Significant state changes | "Loaded {n} jobs, {m} valid after validation" |
| DEBUG | Detailed troubleshooting | "Constraint HC4 added: fixture {fixture} limit {limit}" |

**Never log:** Passwords, API keys, file paths with usernames.

---

## Data Model

### Job (from DAILY_PRODUCTION_LOAD)

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| REQ_BY | date | Excel | Ship date |
| JOB | string | Excel | Unique ID (format: 123456-01-1) |
| DESCRIPTION | string | Excel | Display only |
| PATTERN | char | Excel | D, V, or S |
| OPENING_SIZE | decimal | Excel | Fixture component |
| WIRE_DIAMETER | decimal | Excel | Lookup key for TASK times |
| MOLDS | int | Excel | Count required |
| MOLD_TYPE | string | Excel | STANDARD, DOUBLE2CC, 3INURETHANE |
| PROD_QTY | int | Excel | Total panels needed |
| EQUIVALENT | decimal | Excel | Difficulty factor |
| ORANGE_ELIGIBLE | bool | Excel | Can run on ORANGE cell |
| ON_TABLE_TODAY | string | Operator | Which table job is on (nullable) |
| JOB_QUANTITY_REMAINING | int | Operator | Panels left if ON_TABLE_TODAY set |
| EXPEDITE | bool | Operator | Force higher priority |

### Calculated Fields (per Job)

| Field | Formula |
|-------|---------|
| SCHED_QTY | If ON_TABLE_TODAY blank → PROD_QTY; else → JOB_QUANTITY_REMAINING |
| BUILD_LOAD | SCHED_QTY × EQUIVALENT ÷ SCHED_CONSTANT |
| BUILD_DATE | REQ_BY − ROUNDUP(BUILD_LOAD + PULL_AHEAD) business days |
| PRIORITY | 0=past due or (today+expedite), 1=today, 2=future+expedite, 3=future |
| FIXTURE | PATTERN + "-" + OPENING_SIZE + "-" + WIRE_DIAMETER |
| MOLD_DEPTH | "DEEP" if WIRE_DIAMETER ≥ 8, else "STD" |
| SCHED_CLASS | Lookup from TASK sheet (A, B, C, D, E) |

### Resources

| Resource | Quantity | Notes |
|----------|----------|-------|
| CELLS | 6 | RED, BLUE, GREEN, BLACK, PURPLE, ORANGE |
| TABLES per CELL | 2 | {COLOR}_1, {COLOR}_2 |
| OPERATOR per CELL | 1 | 440 min (standard) or 500 min (overtime) |
| FIXTURES | Per PATTERN | D=4, S=3, V=2 concurrent |
| MOLDS | Per MOLDS sheet | Color-specific + COMMON |

---

## Constraint Definitions

### Hard Constraints (Must Satisfy)

| ID | Constraint | OR-Tools Implementation |
|----|------------|-------------------------|
| HC1 | Operator can only be at one table at a time | NoOverlap on operator intervals |
| HC2 | Task sequence: SETUP→LAYOUT→POUR→CURE→UNLOAD | Precedence constraints per panel |
| HC3 | Cannot start POUR with <40 min remaining | Conditional: if start_pour > (shift_end - 40), disable |
| HC4 | Fixture concurrent limit | Cumulative constraint on fixture usage |
| HC5 | Mold availability | Cumulative constraint on mold usage |
| HC6 | ORANGE only accepts ORANGE_ELIGIBLE jobs | Filter job pool for ORANGE cell |
| HC7 | Job runs consecutively until SCHED_QTY complete | Interval grouping |
| HC8 | Active cell molds reserved | Exclude from other cells' pools |

### Soft Constraints (Objective Function)

| ID | Constraint | Weight | Notes |
|----|------------|--------|-------|
| SC1 | Schedule all Priority 0 jobs | 10000 | Critical |
| SC2 | Schedule all Priority 1 jobs | 1000 | High |
| SC3 | Maximize panels produced | 10 | Per panel |
| SC4 | Minimize FORCED_OPERATOR_IDLE | -1 | Per minute |

### Method-Specific Constraints

See SCHEDULING_PROTOCOL.md for detailed rules per method. Each method modifies the constraint set:

| Method | Critical Rules Summary |
|--------|------------------------|
| 1: Priority First | Priority 0 before 1 before 2 before 3 |
| 2: Minimum Forced Idle | Avoid C-C and D/E-D/E pairings |
| 3: Maximum Output | Dedicate cells to SCHED_CLASS A |
| 4: Most Restricted Mix | Pair D/E opposite C |

---

## Task Timing

### Duration Formulas

| Task | Duration | Operator Required |
|------|----------|-------------------|
| SETUP | TASK sheet lookup (0 if same fixture as prior) | Yes |
| LAYOUT | TASK sheet lookup | Yes |
| POUR | TASK sheet lookup × MOLDS count | Yes |
| CURE | TASK sheet lookup × (1.5 if SUMMER else 1.0) | No |
| UNLOAD | TASK sheet lookup | Yes |

### TASK Sheet Lookup

Use WIRE_DIAMETER ranges and EQUIVALENT for lookup:

- WIRE_DIAMETER ≤ 4
- WIRE_DIAMETER > 4 and < 8
- WIRE_DIAMETER ≥ 8

---

## Mold Assignment Rules

### Mold Type Requirements

| MOLD_DEPTH | MOLD_TYPE | Requirement |
|------------|-----------|-------------|
| DEEP | STANDARD | MOLDS × DEEP_MOLD |
| DEEP | DOUBLE2CC or 3INURETHANE | (MOLDS-1) × DEEP_MOLD + 1 × DEEP_DOUBLE2CC_MOLD |
| STD | STANDARD | MOLDS × {COLOR}_MOLD |
| STD | 3INURETHANE | (MOLDS-1) × {COLOR}_MOLD + 1 × 3INURETHANE_MOLD |
| STD | DOUBLE2CC | (MOLDS-2) × {COLOR}_MOLD + 1 × DOUBLE2CC_MOLD |

### Mold Availability Priority

1. Use {COLOR}_MOLD matching cell (if cell is ACTIVE, these are reserved)
2. Use COMMON_MOLD
3. Use {COLOR}_MOLD from NOT ACTIVE cells (if compliant)
4. If none available → job cannot be scheduled

---

## Scheduling Workflow

### Phase 1: Data Load and Validation

1. Load DAILY_PRODUCTION_LOAD.xlsx
2. Validate all fields (types, ranges, required values)
3. Accept ON_TABLE_TODAY on ORANGE with ORANGE_ELIGIBLE=false → warn
4. Calculate all derived fields per job

### Phase 2: Initial State Setup

1. Assign ON_TABLE_TODAY jobs to their tables (ROUGH_PLAN)
2. Allocate molds and fixtures to ON_TABLE_TODAY jobs
3. Identify jobs on NOT ACTIVE cells that need rescheduling (Priority ≤ 2)

### Phase 3: Run Scheduling Methods

For each of the 4 methods, run both variants:

- Variant A: Select JOB first, then find TABLE
- Variant B: Select TABLE first, then find JOB

Select best variant per method (fewest missed dates, then most panels).

### Phase 4: Present Results

Show summary comparison of all methods:

- Priority 0/1/2/3 jobs scheduled vs. not scheduled
- Total panels produced
- Total FORCED_OPERATOR_IDLE
- Total FORCED_TABLE_IDLE

### Phase 5: Generate Outputs

After operator selects a method:

1. Work cell reports (PDF per ACTIVE cell)
2. Supervisor summary (PDF)
3. Gantt charts (HTML, interactive)
4. Testing Excel (input + calculated fields)

---

## Build Phases

### Phase 1: Data Layer

**Files:** data_loader.py, validator.py, calculated_fields.py, constants.py, errors.py

**Deliverable:** Load Excel, validate, compute all calculated fields, output testing Excel.

**Verification:**

- Load sample DAILY_PRODUCTION_LOAD.xlsx
- Assert calculated fields match hand-calculated values
- BUILD_DATE test: REQ_BY=2026-01-26, BUILD_LOAD=1.3, PULL_AHEAD=0.75 → BUILD_DATE=2026-01-22

### Phase 2: Single-Cell Scheduler

**Files:** constraints.py, scheduler.py (partial), solution_parser.py

**Deliverable:** Schedule one cell (two tables, one operator) with task interleaving.

**Verification:**

- Two jobs, one per table, verify CURE interleaving
- Confirm FORCED_TABLE_IDLE and FORCED_OPERATOR_IDLE calculated correctly
- Generate basic Gantt for visual inspection

### Phase 3: Multi-Cell with Resources

**Files:** scheduler.py (complete), constraints.py (extended)

**Deliverable:** Schedule all 6 cells with fixture and mold constraints.

**Verification:**

- Fixture constraint: V pattern jobs limited to 2 concurrent
- Mold constraint: Active cell molds reserved
- Job spanning multiple cells if BUILD_LOAD > 1

### Phase 4: Method Variants

**Files:** scheduler.py (method implementations)

**Deliverable:** All 4 methods with both variants.

**Verification:**

- Method 1: Priority 0 jobs scheduled first
- Method 2: No C-C pairings
- Method 3: SCHED_CLASS A cells dedicated
- Method 4: D/E paired opposite C

### Phase 5: Output Generation

**Files:** report_generator.py, pdf_output.py, gantt_generator.py

**Deliverable:** All output formats.

**Verification:**

- PDF formatting matches my-theme skill
- Gantt charts interactive and detailed
- Testing Excel contains all calculated fields

### Phase 6: UI Layer

**Files:** app.py, config.py

**Deliverable:** Operator input interface, method selection, password-protected config.

**Verification:**

- End-to-end test with sample data
- All operator inputs functional
- Config changes persist

---

## Test Cases

### TC1: Basic Single Job

**Given:** One job with SCHED_QTY=2, RED_CELL active, both tables empty
**When:** Scheduler runs
**Then:** Job assigned to RED_1, panels 1-2 scheduled. RED_2 remains empty. Total output: 2 panels.

### TC2: Two-Job Interleaving

**Given:** Job A (SCHED_QTY=3) and Job B (SCHED_QTY=3), RED_CELL active, both tables empty
**When:** Scheduler runs
**Then:** A assigned to RED_1, B assigned to RED_2. Operator alternates between tables during CURE. FORCED_TABLE_IDLE or FORCED_OPERATOR_IDLE calculated based on relative CURE times.

### TC3: Fixture Constraint

**Given:** 5 jobs all requiring FIXTURE V-0.25-2 (FIXTURE_QTY for V = 2), 3 cells active
**When:** Scheduler runs
**Then:** Maximum 2 tables use this fixture concurrently. Third job waits until fixture becomes available.

### TC4: Mold Exhaustion

**Given:** Jobs requiring 15 RED_MOLDs total, only 12 RED_MOLD + 4 COMMON_MOLD available
**When:** Scheduler runs
**Then:** First jobs use RED_MOLD, subsequent jobs use COMMON_MOLD as RED_MOLDs exhaust. Final jobs cannot be scheduled (insufficient molds). Warning generated.

### TC5: Priority Override

**Given:** One Priority 0 (past due) job and one Priority 3 job where Priority 3 has better fixture match
**When:** Scheduler runs
**Then:** Priority 0 job scheduled first regardless of fixture efficiency.

### TC6: ON_TABLE_TODAY Continuation

**Given:** Job already on RED_1 with JOB_QUANTITY_REMAINING=3
**When:** Scheduler runs
**Then:** SETUP=0 minutes for panel 1, shift starts with POUR task. SCHED_QTY=3.

### TC7: ORANGE Eligibility Filter

**Given:** ORANGE_ELIGIBLE=false job, ORANGE cell active
**When:** Scheduler attempts to assign job to ORANGE
**Then:** Job rejected for ORANGE cell. Assigned to other available cell instead.

### TC8: DEEP Mold ORANGE Restriction

**Given:** WIRE_DIAMETER=8 job (requires DEEP molds), ORANGE_ELIGIBLE=true, ORANGE cell active
**When:** Scheduler runs
**Then:** Job cannot run on ORANGE (DEEP molds not ORANGE compliant). Assigned to non-ORANGE cell.

---

## Dependencies

```text
ortools>=9.8
pandas>=2.0
openpyxl>=3.1
reportlab>=4.0
plotly>=5.18
flask>=3.0  # or streamlit>=1.30
```

---

## Configuration (Password Protected)

Editable constants from CYCLE_TIME_CONSTANTS.xlsx:

| Sheet | Editable Fields |
|-------|-----------------|
| TASK | B2:J16 (all timing values) |
| MOLDS | D2:D12 (quantities) |
| FIXTURES | C2:C4 (concurrent limits) |
| HOLIDAYS | B2:B9 (dates) |

---

## Future State

Not in current scope, but architecture should support:

- Web deployment (Windows 11 / Server 2022)
- Epicor/Kinetic API integration (replace Excel upload)

---

## Limitations

- Solver timeout may occur with very large job sets (>100 jobs)
- Cannot guarantee optimal solution within time limit (returns best found)
- Gantt chart rendering may be slow for full 6-cell schedules
- PDF generation requires system fonts to be available
