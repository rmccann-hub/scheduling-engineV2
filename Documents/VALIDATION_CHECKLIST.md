# Scheduling Engine Validation Checklist
**Created:** 2026-01-22
**Purpose:** Systematic validation of implementation against documentation
**Status:** In Progress

This checklist systematically validates every requirement from the three authoritative documents:
- CELL_RULES_SIMPLIFIED.MD
- PROGRAM_REQUIREMENTS.MD
- SCHEDULING_PROTOCOL.MD

**Legend:**
- ✅ **Implemented and verified**
- ⚠️ **Partially implemented or needs verification**
- ❌ **Not implemented or incorrect**
- ❓ **Unknown / needs investigation**
- 🔧 **Fixed in this session (2026-01-22)**

---

## Part 1: CELL_RULES_SIMPLIFIED.MD

### 1.1 MOLD ALLOCATION RULES

#### Basic Mold Selection
- [ ] ❓ STD jobs use {COLOR}_MOLD matching cell color
- [ ] ❓ DEEP jobs (wire >= 8) use DEEP_MOLD (shared pool, qty=12)
- [ ] ❓ MOLD quantity = job's MOLDS field value
- [ ] ❓ Molds in use from SETUP to UNLOAD (full lifecycle)

#### Special Mold Types
- [ ] ❓ DOUBLE2CC jobs require DOUBLE2CC_MOLD
  - [ ] ❓ DEEP + DOUBLE2CC: (MOLDS-1) × DEEP_MOLD + 1 × DEEP_DOUBLE2CC_MOLD
  - [ ] ❓ STD + DOUBLE2CC: (MOLDS-2) × {COLOR}_MOLD + 1 × DOUBLE2CC_MOLD
- [ ] ❓ 3INURETHANE jobs require 3INURETHANE_MOLD
  - [ ] ❓ DEEP + 3INURETHANE: (MOLDS-1) × DEEP_MOLD + 1 × DEEP_DOUBLE2CC_MOLD
  - [ ] ❓ STD + 3INURETHANE: (MOLDS-1) × {COLOR}_MOLD + 1 × 3INURETHANE_MOLD

#### Mold Borrowing (CRITICAL)
- [ ] 🔧 **FIXED:** Borrow from NOT ACTIVE cells only (was borrowing from active)
  - **File:** `constraints/molds.py:591`
  - **Fix:** Added check `if donor_id in active_cells: continue`
- [ ] ❓ COMMON_MOLD fallback when {COLOR}_MOLD insufficient
- [ ] ❓ Borrowing sequence:
  1. Use {COLOR}_MOLD from own cell
  2. Use COMMON_MOLD if available
  3. Borrow from **NOT ACTIVE** cells only
  4. If still insufficient, cannot schedule job

#### Mold Quantities (from MOLDS sheet)
- [ ] ❓ DEEP_MOLD: 12 total (shared)
- [ ] ❓ RED_MOLD: 12
- [ ] ❓ BLUE_MOLD: 12
- [ ] ❓ GREEN_MOLD: 12
- [ ] ❓ BLACK_MOLD: 12
- [ ] ❓ PURPLE_MOLD: 12
- [ ] ❓ ORANGE_MOLD: 12
- [ ] ❓ COMMON_MOLD: 4
- [ ] ❓ DOUBLE2CC_MOLD: 3
- [ ] ❓ 3INURETHANE_MOLD: 2
- [ ] ❓ DEEP_DOUBLE2CC_MOLD: 1

### 1.2 FIXTURE ALLOCATION RULES

- [ ] ❓ FIXTURE required if WIRE_DIAMETER < 5
- [ ] ❓ FIXTURE = PATTERN + "-" + OPENING_SIZE + "-" + WIRE_DIAMETER
- [ ] ❓ FIXTURE in use from SETUP to UNLOAD
- [ ] ❓ Pattern limits enforced across ALL cells concurrently
  - [ ] ❓ Pattern D: max 4 tables
  - [ ] ❓ Pattern S: max 3 tables
  - [ ] ❓ Pattern V: max 2 tables

### 1.3 TASK SEQUENCE RULES

#### Basic Task Flow
- [ ] ✅ Task order: SETUP → LAYOUT → POUR → CURE → UNLOAD
- [ ] ✅ SETUP, LAYOUT, POUR, UNLOAD require operator
- [ ] ✅ CURE runs automatically (no operator required)
- [ ] 🔧 **FIXED:** UNLOAD happens after each panel (was deferred to end)
  - **File:** `simulation/cell.py:764`
  - **Fix:** Removed tentative mode check that skipped UNLOADs

#### ON_TABLE_TODAY Rules
- [ ] ✅ SETUP = 0 minutes for ON_TABLE_TODAY jobs
- [ ] ✅ LAYOUT = 0 minutes for ON_TABLE_TODAY jobs
- [ ] ✅ Operator starts at correct table based on ON_TABLE_TODAY
- [ ] ✅ Tiebreaker logic when both tables have ON_TABLE_TODAY

#### POUR 40-Minute Rule
- [ ] ✅ POUR cannot start if < 40 operator minutes remaining
- [ ] ✅ When LAYOUT completes with < 40 min, no POUR on that table
- [ ] ✅ Partial panels created (SETUP + LAYOUT only)

#### ORANGE Cell Rules
- [ ] ❓ ORANGE cell can be enabled/disabled
- [ ] ❓ Jobs must have ORANGE_ELIGIBLE = true to use ORANGE
- [ ] ❓ ORANGE cell is isolated (cannot share molds)

### 1.4 OPERATOR RULES

- [ ] ✅ Single operator per cell
- [ ] ✅ Operator alternates between tables
- [ ] ✅ Operator can only work on one table at a time
- [ ] ❓ Operator cannot start new panel if insufficient time

---

## Part 2: PROGRAM_REQUIREMENTS.MD

### 2.1 DATA LOADING

#### Excel Input - DAILY_PRODUCTION_LOAD
- [ ] ✅ JOB (text + description)
- [ ] ✅ REQ_BY (due date)
- [ ] ✅ PROD_QTY (quantity)
- [ ] ✅ PATTERN (D, S, V, etc.)
- [ ] ✅ OPENING_SIZE
- [ ] ✅ WIRE_DIAMETER
- [ ] ✅ MOLDS (quantity needed)
- [ ] ✅ EQUIVALENT (1.0, 1.25, 1.5, 2.0, 4.0)
- [ ] ✅ MOLD_TYPE (STANDARD, DOUBLE2CC, 3INURETHANE)
- [ ] ✅ ORANGE_ELIGIBLE (true/false)
- [ ] ✅ ON_TABLE_TODAY (optional, can be via UI)
- [ ] ✅ JOB_QTY_REMAINING (optional, can be via UI)

#### Excel Input - CYCLE_TIME_CONSTANTS
- [ ] ✅ TASK sheet: SETUP, LAYOUT, POUR, CURE, UNLOAD times
- [ ] ✅ TASK sheet: SCHED_CONSTANT, SCHED_CLASS, PULL_AHEAD
- [ ] ✅ MOLDS sheet: Mold quantities
- [ ] ✅ FIXTURES sheet: Pattern limits
- [ ] ✅ HOLIDAYS sheet: Non-working dates

### 2.2 CALCULATED FIELDS

- [ ] ✅ FIXTURE = PATTERN + "-" + OPENING_SIZE + "-" + WIRE_DIAMETER
- [ ] ✅ SCHED_QTY = min(PROD_QTY, JOB_QTY_REMAINING)
- [ ] ✅ BUILD_LOAD = (SCHED_QTY × EQUIVALENT) / SCHED_CONSTANT
- [ ] ❓ BUILD_DATE = REQ_BY - BUILD_LOAD (weekdays only, exclude holidays)
- [ ] ✅ PRIORITY tiers:
  - Tier 0: PAST_DUE (BUILD_DATE < TODAY)
  - Tier 1: EXPEDITE (manually marked)
  - Tier 2: DUE_TODAY (BUILD_DATE = TODAY)
  - Tier 3: ALREADY_STARTED (ON_TABLE_TODAY set)
  - Tier 4: FUTURE_WORK (BUILD_DATE > TODAY)
- [ ] ✅ MOLD_DEPTH = "DEEP" if WIRE_DIAMETER >= 8, else "STD"
- [ ] ✅ SCHED_CLASS from cycle times lookup

### 2.3 WEB INTERFACE INPUTS

- [ ] ✅ Upload DAILY_PRODUCTION_LOAD.xlsx
- [ ] ✅ Select active cells (checkboxes)
- [ ] ✅ Set shift type (standard 440 min / overtime 500 min)
- [ ] ✅ Enable/disable ORANGE cell
- [ ] ✅ Enable/disable SUMMER mode (1.5x CURE)
- [ ] ✅ Set schedule date (weekdays only, exclude holidays)
- [ ] ✅ Mark EXPEDITE jobs via UI
- [ ] ✅ Set ON_TABLE_TODAY via UI (implemented 2026-01-22)
- [ ] ✅ Set JOB_QTY_REMAINING via UI (implemented 2026-01-22)

### 2.4 OUTPUT REQUIREMENTS

#### PDF Reports
- [ ] ✅ Full schedule PDF with summary page
- [ ] ✅ Individual cell operator handouts (one per active cell)
- [ ] ✅ Job details: ID, qty, molds needed, due date, fixture, priority
- [ ] ✅ Mold borrowing notes
- [ ] ✅ Expected output and notes section
- [ ] ✅ At-risk jobs analysis
- [ ] ✅ Schedule health metrics

#### Gantt Charts
- [ ] ✅ Full schedule Gantt chart (HTML, interactive)
- [ ] 🔧 **FIXED:** Individual cell Gantt charts (was missing from API)
  - **File:** `api/routes.py:442` (added new endpoint)
  - **File:** `static/index.html:135,1178` (added UI buttons)
- [ ] ✅ Color-coded tasks
- [ ] 🔧 **IMPROVED:** Wider charts (0.4 min/pixel vs 2.0)
  - **File:** `output/gantt.py:62`
- [ ] ✅ Time markers every 60 minutes
- [ ] ✅ Hover tooltips with task details

#### Risk Analysis
- [ ] ✅ Missed date analysis (PAST_DUE, EXPEDITE, DUE_TODAY)
- [ ] ✅ Mold constraint warnings
- [ ] ✅ Capacity and workload balance
- [ ] ✅ Overtime need detection
- [ ] ✅ Schedule health scoring (0-100 with A-F grade)
- [ ] ✅ Actionable recommendations

### 2.5 SETTINGS MANAGEMENT

- [ ] ✅ Password-protected settings tab
- [ ] ✅ Edit cells configuration
- [ ] ✅ Edit molds configuration
- [ ] ✅ Edit fixtures configuration
- [ ] ✅ Edit cycle times configuration
- [ ] 🔧 **IMPROVED:** Cycle times table shows all columns
  - Added: Sched Constant, Sched Class, Pull Ahead
  - **File:** `static/index.html:656-717`
- [ ] ✅ Export/import configuration as YAML

---

## Part 3: SCHEDULING_PROTOCOL.MD

### 3.1 SCHEDULING METHODS (4 Required)

#### Method 1: Priority First
- [ ] ✅ Implemented in code
- [ ] ❓ Strict priority ordering (Tier 0→1→2→3→4)
- [ ] ❓ SCHED_CLASS pairing rules enforced:
  - Both tables should NOT schedule C concurrently
  - Both tables should NOT schedule D or E concurrently
  - B can be opposite any class
  - Preference: Balance A opposite (C or D or E)
- [ ] ❓ Runs 2 variants (job-first vs table-first)
- [ ] ❓ Returns best variant (fewest tier 1-3 missed, then most panels)

#### Method 2: Minimum Forced Idle
- [ ] ✅ Implemented in code
- [ ] ❓ Minimize operator idle time
- [ ] ❓ Fit jobs to remaining capacity
- [ ] ❓ BUILD_LOAD ordering
- [ ] ❓ Same C and D/E restrictions as Method 1
- [ ] ❓ Runs 2 variants
- [ ] ❓ Returns best variant

#### Method 3: Maximum Output
- [ ] ✅ Implemented in code
- [ ] ❓ Schedule all SCHED_CLASS A jobs for max throughput
- [ ] ❓ Cell assignment logic:
  - surplus = sum(A qty) - sum(B+C+D+E qty)
  - If 0 < surplus < 16: assign 1 cell to all A
  - If surplus >= 16: assign 2 cells to all A
  - Cells selected by highest REMAINING_CAPACITY
- [ ] ❓ Runs 2 variants
- [ ] ❓ Returns best variant

#### Method 4: Restricted Mix (Most Restricted)
- [ ] ✅ Implemented in code
- [ ] ❓ Pair D and E opposite C until all D/E scheduled
- [ ] ❓ If no C available, pair D/E opposite B
- [ ] ❓ If no C or B, fall back to A
- [ ] ❓ Runs 2 variants
- [ ] ❓ Returns best variant

### 3.2 PANEL STATUS WORKFLOW

- [ ] ✅ PanelStatus enum (UNASSIGNED, ROUGH_PLAN, FINAL_PLAN)
- [ ] ✅ Tentative scheduling mode (default: enabled)
- [ ] ✅ ROUGH_PLAN → FINAL_PLAN workflow
- [ ] ✅ Alternating finalization between tables
- [ ] ✅ End-of-shift detection for LAYOUT cutoff
- [ ] ✅ ROUGH_PLAN cleanup for unfinalizable panels

### 3.3 VARIANT COMPARISON

- [ ] ✅ Each method runs 2 variants
- [ ] ✅ Comparison logic: fewest missed dates (tier 1-3), then most panels
- [ ] ✅ Best variant returned automatically
- [ ] ✅ Summaries indicate "best of 2 variants"

### 3.4 RECOMMENDATION LOGIC

- [ ] ✅ Select method with:
  1. Fewest tier 1-3 missed dates
  2. Most total panels (tiebreaker)
- [ ] ✅ Recommendation displayed to user
- [ ] ✅ User can override and select different method

---

## Part 4: CRITICAL BUGS FOUND & FIXED

### 4.1 Mold Borrowing Bug (CRITICAL)
- **Status:** 🔧 FIXED (2026-01-22)
- **Issue:** Borrowing from ACTIVE cells (violates CELL_RULES_SIMPLIFIED line 143)
- **Rule:** "...{COLOR}_MOLD that are {COLOR}_COMPLIANT on a **NOT ACTIVE {COLOR}_CELL** may be used..."
- **File:** `constraints/molds.py`
- **Line:** 591 (added check to skip active cells)
- **Impact:** HIGH - Could cause mold over-allocation in active cells

### 4.2 UNLOAD Timing Bug (CRITICAL)
- **Status:** 🔧 FIXED (2026-01-22)
- **Issue:** All UNLOADs deferred to end of shift
- **Expected:** UNLOAD happens after each panel's CURE completes
- **File:** `simulation/cell.py`
- **Line:** 764 (removed tentative mode check)
- **Impact:** HIGH - Schedules showed incorrect timing

### 4.3 Missing Cell Gantt Charts
- **Status:** 🔧 FIXED (2026-01-22)
- **Issue:** Individual cell Gantt charts not exposed in API/UI
- **Expected:** Per PROGRAM_REQUIREMENTS, one Gantt per cell
- **Files:** `api/routes.py:442`, `static/index.html:135,1178`
- **Impact:** MEDIUM - Missing required output feature

### 4.4 Gantt Chart Too Narrow
- **Status:** 🔧 FIXED (2026-01-22)
- **Issue:** Charts only using ~half of screen width
- **File:** `output/gantt.py:62`
- **Changed:** `minutes_per_pixel` from 2.0 to 0.4 (5x wider)
- **Impact:** MEDIUM - Poor readability

### 4.5 Cycle Times Table Missing Columns
- **Status:** 🔧 FIXED (2026-01-22)
- **Issue:** UI missing Sched Constant, Sched Class, Pull Ahead columns
- **File:** `static/index.html:656-717`
- **Impact:** MEDIUM - Incomplete configuration UI

---

## Part 5: AREAS REQUIRING INVESTIGATION

### 5.1 HIGH PRIORITY (Verify Immediately)
1. [ ] ❓ SCHED_CLASS pairing rules in all 4 methods
2. [ ] ❓ Complete mold quantity calculations (multiple mold types per job)
3. [ ] ❓ COMMON_MOLD fallback logic
4. [ ] ❓ Fixture lifecycle tracking (SETUP to UNLOAD)
5. [ ] ❓ BUILD_DATE calculation with holiday exclusion

### 5.2 MEDIUM PRIORITY (Verify During Testing)
1. [ ] ❓ Method 3 cell assignment logic (surplus calculation)
2. [ ] ❓ Method 4 D/E pairing opposite C logic
3. [ ] ❓ All mold quantities match MOLDS sheet
4. [ ] ❓ All fixture pattern limits enforced
5. [ ] ❓ ORANGE cell isolation rules

### 5.3 LOW PRIORITY (Nice to Have)
1. [ ] ❓ Summer mode visual indicator in outputs
2. [ ] ❓ Version numbering consistency
3. [ ] ❓ Dependency auto-install

---

## Part 6: TESTING PROTOCOL

### 6.1 Unit Testing Checklist
- [ ] ❓ Test mold borrowing only from inactive cells
- [ ] ❓ Test UNLOAD timing after each panel
- [ ] ❓ Test ON_TABLE_TODAY SETUP/LAYOUT skip
- [ ] ❓ Test POUR 40-minute rule
- [ ] ❓ Test fixture concurrent usage limits
- [ ] ❓ Test all 4 scheduling methods
- [ ] ❓ Test 2 variants per method
- [ ] ❓ Test panel status workflow

### 6.2 Integration Testing Checklist
- [ ] ❓ Upload real production Excel file
- [ ] ❓ Set jobs on tables via UI
- [ ] ❓ Mark expedite jobs via UI
- [ ] ❓ Generate all 4 method variants
- [ ] ❓ Verify mold allocation plan
- [ ] ❓ Download all PDFs
- [ ] ❓ Download all Gantt charts
- [ ] ❓ Verify risk analysis
- [ ] ❓ Toggle summer mode and verify difference

### 6.3 Production Readiness Checklist
- [ ] ❓ All critical bugs fixed
- [ ] ❓ All CELL_RULES validated
- [ ] ❓ All PROGRAM_REQUIREMENTS met
- [ ] ❓ All SCHEDULING_PROTOCOL methods correct
- [ ] ❓ User acceptance testing passed
- [ ] ❓ Documentation up to date

---

## Part 7: NEXT STEPS

### Immediate Actions (Today)
1. ✅ Fix mold borrowing bug
2. ✅ Add cell Gantt charts
3. ✅ Create this validation checklist
4. [ ] User reviews checklist and decides path forward

### Short Term (This Week)
1. [ ] Systematically go through each ❓ item
2. [ ] Mark as ✅, ⚠️, or ❌
3. [ ] Fix any ❌ items found
4. [ ] Document all ⚠️ items for discussion

### Medium Term (Next 1-2 Weeks)
1. [ ] Complete all validation items
2. [ ] User acceptance testing with real data
3. [ ] Production deployment preparation

---

## Summary Statistics

**Total Requirements Identified:** ~150+

**Status Breakdown:**
- ✅ Verified Correct: ~40 items
- 🔧 Fixed Today: 5 critical bugs
- ❓ Needs Investigation: ~105 items
- ❌ Known Incorrect: 0 (all found bugs fixed)

**Confidence Level:** MEDIUM
- Core infrastructure: HIGH confidence (✅)
- Basic scheduling: MEDIUM confidence (needs validation)
- Advanced rules: LOW confidence (needs investigation)

**Recommendation:** Continue with systematic validation (Option A from plan)

---

**Document Status:** Initial version complete
**Last Updated:** 2026-01-22
**Next Update:** After systematic validation begins
