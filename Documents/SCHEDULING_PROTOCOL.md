SCHEDULING_PROTOCOL

Purpose of the SCHEDULING_PROTOCOL is to define how the rules defined in CELL_RULES_SIMPLIFIED, CYCLE_TIME_CONSTANTS, and PROGRAM_REQUIREMENTS are applied to generate multiple possible schedules, for the program operator to select the final schedule for the day.

RESOURCE TRACKING AND DEFINITIONS:

Every {COLOR} CELL must track and produce a TASK Gantt Chart for three resources:
{COLOR}_1:  the first table in the cell
{COLOR}_2:  the second table in the cell
{COLOR}_OPERATOR:  the OPERATOR performing tasks in the CELL.
Example:  RED CELL has to track RED_1, RED_2, and RED_OPERATOR.
In this document, {COLOR} and {COLOR}_CELL both refer to the CELL, so RED and RED CELL mean the same thing.
SHIFT determines how many minutes of availability each resource has:
Standard shift has 440 minutes.
Overtime shift has 500 minutes.
A {COLOR} must be ACTIVE for it to have a {COLOR}_OPERATOR
{COLOR}_TABLES may have assigned JOBs without being ACTIVE.
These JOBs cannot have TASKs performed without their {COLOR}_OPERATOR.
JOBS assigned to a NOT ACTIVE {COLOR} may have to be scheduled on an ACTIVE {COLOR}, so they will still require review.
TABLEs produce PANELs, and JOBs are assigned as PANELs to a TABLE.
The term PANEL refers to the production opportunity on a TABLE.
Completion time on a PANEL is unknown until a JOB is assigned to it.
JOBs are assigned to these PANEL slots to determine TASK times based on the JOBs variable data.
A JOB requires one consecutive PANEL slot on the table for every SCHED_QTY on the JOB.
Example, if a JOB has has a SCHED_QTY of 4, it will need four consecutive slots on the same table. (RED_1_1, RED_1_2, RED_1_3, RED_1_4).
If a JOB is scheduled to be run on more than one TABLE on the same day, the SCHED_QTY will be allocated to each table in the most evenly.  If they cannot be divided equally, the TABLE that is available at the earliest PANEL slot will receive the larger allocation.
The {CELL}_OPERATOR is the constrained resource, and can only perform work on one {COLOR}_TABLE at a time.
The CELL_RULES_SIMPLIFIED document details FORCED_TABLE_IDLE and FORCED_OPERATOR_IDLE.
These values are determined by the interaction of TASKs between the two CELL TABLES, so they cannot be determined until JOBS have been assigned to PANEL slots on both TABLES.

PANEL STATUS WORKFLOW:

In the course of scheduling, PANEL assignments on {COLOR}_TABLES have a STATUS attribute to indicate if they have been planned or are available.
Valid Status attributes are UNASSIGNED, ROUGH_PLAN, and FINAL_PLAN.
All PANELS on all TABLES start UNASSIGNED.
ALL PANELS on all ACTIVE TABLES must end with either UNASSIGNED or FINAL_PLAN status.
ROUGH_PLAN is a transitory status used for the scheduling process, and the schedule variants cannot be completed with a PANEL and JOB in the ROUGH_PLAN status.
ROUGH_PLAN status must be assigned contiguously starting with PANEL_1 on a {COLOR}_TABLE.
ROUGH_PLAN status will be converted to FINAL_PLAN status contiguously starting with PANEL 1.
A {COLOR}_TABLE has been fully scheduled when PANEL_1 through PANEL_N has the FINAL_PLAN status and PANEL_N+1 has been set to UNASSIGNED.
UNASSIGNED PANELs are PANELs that do not have a JOB assigned.
All TABLES begin with all PANELs UNASSIGNED
If a {COLOR}_TABLE has a JOB called out in ON_TABLE_TODAY, a number of its PANEL attributes are assigned to ROUGH_PLAN.
The process will set ROUGH_PLAN panels that cannot be completed to UNASSIGNED to conclude each ACTIVE {COLOR} CELLs production day.
ROUGH_PLAN is based on JOBS assigned to PANELS on a TABLE without knowing, or before calculating, the corresponding JOBS assigned to PANELS on the other TABLE
ROUGH_PLAN uses the calculated sum of SETUP (if required), LAYOUT, POUR, CURE, and UNLOAD for each PANEL with an assigned JOB, without regard to OPERATOR availability.
FORCED_TABLE_IDLE cannot be calculated without knowing what is on the other {COLOR}_TABLE.
The OPERATOR is assumed available in the ROUGH_PLAN, and is assigned to one TABLE only.
The ROUGH_PLAN time for PANEL_1 on any TABLE identified in ON_TABLE_TODAY is calculated differently from subsequent panels.  The rules defined in CELL_RULES_SIMPLIFIED detail where to start TASKS based on whether one or both TABLES have ON_TABLE_TODAY information.
FINAL_PLAN is based on JOBs assigned to PANELs on BOTH TABLEs, so the OPERATOR can be scheduled to exact time.
FORCED_TABLE_IDLE and FORCED_OPERATOR_IDLE are now known based on the JOBs assigned to PANELs on both TABLEs.
FINAL_PLAN will reflect where the OPERATOR is on each TABLE, and in which TASK.
FINAL_PLAN can only be set as PANEL slots are assigned on both TABLEs, and will replace ROUGH_PLAN for the assigned TABLE.
If a JOB with 6 SCHED_QTY has been assigned to the first 6 PANELs on TABLE RED_1, RED_1 will have a ROUGH_PLAN that consumes a calculated amount of the available SHIFT minutes.
When a JOB is assigned to RED_2, a FINAL_PLAN can begin to be calculated for both RED_1 and RED_2, but only as far as PANEL quantities match.
If the RED_2 JOB has 6 SCHED_QTY, FINAL_PLAN can be calculated for both RED_1_1 through RED_1_6 and RED_2_1 through RED_2_6
If the RED_2 JOB has 3 SCHED_QTY, FINAL_PLAN can be calculated for RED_1_1 through RED_1_3 and RED_2_1 through RED_2_3, but RED_1_4 through RED_1_6 still only have a ROUGH_PLAN
 If the RED_2 JOB has 8 SCHED_QTY, FINAL_PLAN can be calculated for RED_1_1 through RED_1_6 and RED_2_1 through RED_2_6, but RED_2_7 through RED_2_8 still only have a ROUGH_PLAN
The time attached to a FINAL_PLAN step will never be shorter than the ROUGH_PLAN step.  Just as with ROUGH_PLAN, for PANEL_1 for ON_TABLE_TODAY, the time associated with PANEL_1 of an already started JOb may be less than the FINAL_PLAN time of subsequent PANELs of the same JOB.
The scheduling process will ensure that all {COLOR} CELLs have a FINAL_PLAN established for all ACTIVE {COLOR}_TABLEs.
FINAL_PLAN is a conversion process, and it changes a ROUGH_PLAN PANEL to a FINAL_PLAN.
The CELL_RULES_SIMPLIFIED document details how the last scheduled PANEL on each {COLOR}_TABLE is handled.  This last PANEL will be converted to FINAL_PLAN
Any subsequent PANELS that have been ROUGH_PLAN scheduled cannot be completed, and those PANEL statuses will be changed to UNASSIGNED.
All ACTIVE {COLOR}_TABLE PANELs are expected to move from UNASSIGNED to ROUGH_PLAN to FINAL_PLAN status through the scheduling process.

CALCULATE EARLIEST AVAILABILITY AND CAPACITY:

WHEN_AVAILABLE is a metric to determine when a {COLOR}_TABLE is going to be open in a shift to schedule the first UNASSIGNED PANEL with a new JOB and SETUP TASK.
It is measured in time elapsed in minutes from the start of the shift. 
If all PANELs on a TABLE are UNASSIGNED, WHEN_AVAILABLE is 0.
When PANELs are changed to ROUGH_PLAN or FINAL_PLAN, WHEN_AVAILABLE is the sum of all accrued time for ROUGH_PLAN and FINAL_PLAN assignments.  FINAL_PLAN assignments will include the impact of any FORCED_TABLE_IDLE.  
WHEN_AVAILABLE represents the first minute on each {CELL}_TABLE that an UNASSIGNED PANEL is available to accept a SETUP TASK on a new JOB.
REMAINING_CAPACITY is the number of minutes remaining available for possible scheduling.
It is calculated per {COLOR}_TABLE, and is the number of minutes in the SHIFT, based on standard or overtime, minus WHEN_AVAILABLE.
It is only used in some scheduling variants to test fit possible JOBs before committing to ROUGH_PLAN status.

TABLE ASSIGNMENT BALANCE:

In scheduling, some methods are going to look for first available TABLE based on WHEN_AVAILABLE, and some methods are going to look for first then next CELL in sequence regardless of WHEN_AVAILABLE.  To balance out weekly difficulty in some of the scheduling methods, a sequence order based on weekday will be hard coded into the scheduler.

If the day being scheduled is a Monday, and the method calls for scheduling cells in sequence, use the following sequence:  Blue, Green, Red, Black, Purple, Orange.

If the day being scheduled is a Tuesday, and the method calls for scheduling cells in sequence, use the following sequence:  Green, Red, Black, Purple, Blue, Orange.

If the day being scheduled is a Wednesday, and the method calls for scheduling cells in sequence, use the following sequence:  Red, Black, Purple, Blue, Green, Orange.

If the day being scheduled is a Thursday, and the method calls for scheduling cells in sequence, use the following sequence:  Black, Purple, Blue, Green, Red, Orange.

If the day being scheduled is a Friday, and the method calls for scheduling cells in sequence, use the following sequence:  Purple, Blue, Green, Red, Black, Orange.

 
SCHEDULING PROCESS CONSISTENT FOR ALL SCHEDULE VARIANTS:

Prior to modeling any scheduling, the data to evaluate the DAILY_PRODUCTION_LOAD and Program inputs must be set.
All calculated fields for every job must be calculated.
All ON_TABLE_TODAY panels must be assigned PANELs on the defined {COLOR}_TABLE.
The number of PANELs assigned must match the SCHED_QTY field.
The STATUS on these PANELs will be changed to ROUGH_PLAN.
If both TABLES in a CELL have ON_TABLE_TODAY JOBS, convert as many as possible to FINAL_PLAN status.
Appropriate MOLDs must be assigned to all assigned PANELs.  If {COLOR}_MOLD quantity is exceeded, assign COMMON_MOLDs
Appropriate FIXTUREs must be assigned.
If there are insufficient MOLDs or FIXTUREs to cover all ON_TABLE_TODAY, assume that the JOB assignments are valid but enforce quantity availability rules when next scheduling a SETUP TASK.
JOBs with a priority of 2 or less that are ON_TABLE_TODAY on a {COLOR}_TABLE that is NOT ACTIVE must be scheduled to an ACTIVE {COLOR}_TABLE.
They will be scheduled based on the rules defined for the scheduling variant, but they must be identified as a required job to schedule, and they must receive the first available assignment for a job with a matching SCHED_CLASS.

PROCESS TO CONFIRM A PROSPECTIVE SETUP:

Each scheduling scheme will involve selecting a JOB based on the scheme's ruleset to ROUGH_PLAN in an available {COLOR}_TABLE PANEL.  JOBs that violate the ruleset cannot be assigned to that {COLOR}_TABLE PANEL.

The critical rules are:
The {COLOR}_CELL must be ACTIVE.
If scheduling ORANGE, the JOB must be ORANGE_ELIGIBLE=true
A FIXTURE must be available.
CELL_RULES_SIMPLIFIED has the rule for determining how many of each FIXTURE exist.
The quantity is for how many concurrent sets can be in use.  A specific V fixture with a FIXTURE_QTY=2 could be used on 4 different {COLOR}_TABLES provided no more than 2 are used concurrently.
FIXTUREs are in use from SETUP of the first PANEL on the JOB through UNLOAD of the last PANEL on the JOB.
JOBs assigned as PANEL_1 through ON_TABLE_TODAY have FIXTUREs assigned, even though the SETUP TASK does not need to be verified.
All required MOLDs must be available.
CELL_RULES_SIMPLIFIED has the rule for determining how many of each type of MOLD are required for the JOB.
Any MOLD in use on another {COLOR}_TABLE is not available for use in this JOB.
COMMON_MOLD can be used on multiple {COLOR}_CELLs throughout the schedule, but not concurrently.
MOLDs are in use from SETUP of the first PANEL on the JOB through UNLOAD of the last PANEL on the JOB.
JOBs assigned as PANEL_1 through ON_TABLE_TODAY have MOLDs assigned, even though the SETUP TASK does not need to be verified.

CONVERTING ROUGH_PLAN TO FINAL_PLAN:

The process for planning any scheme is to select a JOB based on the scheme's ruleset, and ROUGH_PLAN it on the specified {COLOR}_TABLE, and then immediately check the other {COLOR}_TABLE for any ROUGH_PLAN panels.
If ROUGH_PLAN tables are available on both TABLES, convert PANELs to FINAL_PLAN for as many as can be done.
PANELs need to be converted to FINAL_PLAN one PANEL at a time alternating between tables.
This is done to encounter the last PANEL of the day, when the end of shift rules are encountered.  The last PANEL that can complete LAYOUT will be the last FINAL_PLAN PANEL on that TABLE.  Any remaining ROUGH_PLAN PANELs will be converted to UNASSIGNED.
The other TABLE will have its next ROUGH_PLAN PANEL evaluated to determine if LAYOUT TASK can complete prior to end of shift. 
If it can complete LAYOUT, it is set as FINAL_PLAN and subsequent ROUGH_PLAN are changed to UNASSIGNED.
If it cannot complete LAYOUT, is is set as UNASSIGNED and not counted as a scheduled PANEL for the TABLE that shift.
It is expected that each TABLE will have a different number of ROUGH_PLAN PANELs assigned through the day, but FINAL_PLAN panels should end up the same or within one at the end of the shift.
The TABLE with the fewer ROUGH_PLAN PANELs partially through the shift should be able to be fully converted to FINAL_PLAN PANELs before a next JOB is chosen for UNASSIGNED PANEL spots..
A {COLOR}_TABLE may reach a point where no available JOBs can be scheduled.
This may be caused by lack of FIXTURE, but is more commonly caused by lack of MOLDs.
In the event that the scheduling method ends with ROUGH_PLAN PANELs on one TABLE and UNASSIGNED PANELs on the other TABLE, the ROUGH_PLAN PANELs are converted to FINAL_PLAN, and all time on the other TABLE is considered FORCED_TABLE_IDLE time. 

SCHEDULING_METHODS

GENERAL GUIDELINES FOR ALL METHODS:
These are not rules, they are recommendations for any of the tested methods based on internal experience.
ORANGE has the most available {COLOR}_MOLDS
If ORANGE is ACTIVE, directing ORANGE_ELIGIBLE= true JOBS with the highest MOLDs requirement will free up the most other capacity on all other {COLOR}_CELLS
Pairing JOBs with the same FIXTURE eliminates a SETUP TASK.  
If the scheduling method variant is select a JOB first and then look for a {COLOR}_TABLE, selecting a TABLE with the same FIXTURE is preferred as long as it does not violate a critical rule.
If the scheduling method variant is select a {COLOR}_TABLE first and then look for a JOB, selecting a JOB with the same FIXTURE is preferred as long as it does not violate a critical rule.
MOLDs can become a constraint, and a part of this testing is to determine whether more COMMON_MOLDs and {COLOR}_MOLDs are required.
Pairing the JOBs on {COLOR}_TABLEs early in the shift that use the least amount of MOLDs generally saves COMON_MOLDs for assignment later in the shift.
When MOLDs become unavailable, {COLOR}_TABLEs will have no JOBS that can be SETUP validly.  When one TABLE stops producing PANELs generally the CELL will produce fewer total PANELs and the entire day will produce less PANELs.
Schedules that keep all TABLES producing PANELs for the entire shift are generally more productive than schedules that shut down TABLEs through the day.
If a PRIORITY 0 JOB has a BUILD_LOAD greater than 1, it must be scheduled on more than one {COLOR}_TABLE
The critical rules and general rules will still apply for how each table is selected.


EVALUATION OF METHODS:

For each method and its variants, produce a report identifying:
Schedule effectiveness:
quantity of Priority 0 jobs scheduled, quantity not able to be scheduled
quantity of Priority 1 jobs scheduled, quantity not able to be scheduled
quantity of Priority 2 jobs scheduled, quantity not able to be scheduled
quantity of Priority 3 jobs scheduled, quantity not able to be scheduled
Number of Panels produced:
Total Quantity produced
Quantity produced by cell
Quantitiy of each SCHED_CLASS produced
Schedule Efficiency:
Sum of FORCED_TABLE_IDLE across all {COLOR}_CELLS
Sum of FORCED_OPERATOR_IDLE across all {COLOR}_CELLS


DEFINITIONS IN TEST METHOD:

Each method will have CRITICAL RULES that can't be violated.
If a selected ROUGH_PLAN assignment violates a CRITICAL RULE, it can't be violated.
Each method will have a GENERAL RULE that can be violated if no other option exists.
This is meant to set the general path of the scheme on a first pass preference.
If a TABLE cannot schedule any JOB and meet the GENERAL RULE, it is allowed to violate.
This means doing something on a TABLE is more important than idling the TABLE
Each method may have a PREFERENCE, which is a fall back decision breaker if multiple JOBs meet all other rules, or if the other rules can't be met.


METHOD VARIANT:
For each Method detailed below, it will be tested in two different means of JOB assignment, and the results of both VARIANTS reported.
The first VARIANT is selecting a JOB first, and then selecting a {COLOR}_TABLE.
The application will select a JOB based on the sort criteria set in the METHOD.
The TABLE selected will be based on:
Compliance with Critical Rules and General Rules
Ability to complete the SETUP TASK
Earliest WHEN_AVAILABLE time
The second VARIANT will select a {COLOR}_TABLE first and the find a compliant JOB.
The application will select a {COLOR}_TABLE based on the criteria in the METHOD.
If a criteria is not dictated, it will select TABLES based on the weekday order set out in Table Assignment balance in SCHEDULING_PROTOCOL.
The JOB selected will be based on:
Compliance with Critical Rules and General Rules
Ability to complete the SETUP TASK
Lowest PRIORITY will be selected.

METHOD 1:  Priority First
CRITICAL RULES:
All Priority 0 Jobs must be scheduled before any higher priority
Once all 0 are scheduled, priority 1 must be scheduled before any higher priority
GENERAL RULES:
Both TABLES in a {COLOR} should not be scheduled with SCHED_CLASS C concurrently
Both TABLES in a {COLOR} should not be scheduled with (D OR E) concurrently
SCHED_CLASS B can be scheduled opposite any SCHED_CLASS
PREFERENCES::
Balance assigning SCHED_CLASS A on tables opposing (C OR D OR E)


METHOD 2:  Minimum Forced Idle
CRITICAL RULES:
Both TABLES in a {COLOR} should not be scheduled with SCHED_CLASS C concurrently
Both TABLES in a {COLOR} should not be scheduled with (D OR E) concurrently
GENERAL RULES:
Assign PRIORITY 0 and 1 before assigning PRIORITY 2
Priority 2 jobs should be assigned by Highest BUILD_LOAD to earliest WHEN_AVAILABLE
PREFERENCES::
Treat BUILD_LOAD as a percentage of shift required to complete, and assign to {COLOR}_TABLES that have a REMAINING_CAPACITY sufficient to complete the JOB within the shift.  Select the JOB that fits and preserves the most REMAINING_CAPACITY
If no job fits in REMAINING_CAPACITY, schedule without regards to BUILD_LOAD

METHOD 3:  Maximum output
CRITICAL RULES:
Schedule as many cells as possible with all SCHED_CLASS A jobs on both {COLOR}_TABLES
To determine number of {COLOR}_CELLs to assign, subtract the SCHED_QTY sum of SCHED_CLASS (B+C+D+E) from the sum of SCHED_QTY of SCHED_CLASS A.  If this surplus is less 16, assign one CELL to all A.  If 16 or more, assign 2 cells to all A.
The cells to schedule will be based first on the sum of both TABLES REMAINING_CAPACITY, with the cells with the highest sum assigned first
GENERAL RULES:
On the tables not assigned to SCHED_CLASS A, pair SCHED_CLASS B opposite other classes.  Avoid B-B TABLE pairings.
In assigning all tables, attempt to schedule by lowest priority first.
PREFERENCES::
Keep all E to one table.


METHOD 4:  Most restricted mix
CRITICAL RULES:
Pair D and E opposite C in table assignments until all D and E are scheduled.
If no C are available opposite, D and E, then schedule B.
GENERAL RULES:
Schedule lower PRIORITY as tie breaker
Schedule higher BUILD_LOAD as a tie breaker
PREFERENCES::
none.
