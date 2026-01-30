CELL_RULES_SIMPLIFIED

These rules are absolute: an operator cannot be in two places. These are hard errors if violated.

The purpose of the software is to produce a daily schedule of PANEL production over multiple CELLs to meet due date requirements and maximize performance to scheduled date and maximize PANEL quantity produced.

The program will schedule a single production day.  All inputs and calculations will be refreshed on demand.

Production has 6 CELLs, identified by {COLOR}:  RED, BLUE, GREEN, BLACK, PURPLE, ORANGE.  In this document, {COLOR} refers to any CELL.  {NOT ORANGE} refers to any cell of the five cells that are not ORANGE.

Each CELL has two TABLEs, identified by {COLOR}_{TABLE#}: RED_1, RED_2, BLUE_1, BLUE_2, GREEN_1, GREEN_2, BLACK_1, BLACK_2, PURPLE_1, PURPLE_2, ORANGE_1, ORANGE_2.  In this document, {COLOR}_TABLE is used to refer to either TABLE 1 or TABLE 2 in a CELL.

Each CELL must be ACTIVE for it to be eligible for scheduling.  The variable {COLOR}_ACTIVE will be set to true or false in PROGRAM_INPUTS portion of the application each day:  RED_ACTIVE, BLUE_ACTIVE, GREEN_ACTIVE, BLACK_ACTIVE, PURPLE_ACTIVE, ORANGE_ACTIVE.

The ACTIVE value applies to both TABLES in a CELL.  If {COLOR}_ACTIVE is false, neither {COLOR}_TABLE_1 nor {COLOR}_TABLE_2 are scheduled.

Each TABLE produces PANELs, and PANELs are identified by JOB.  Available JOBs are loaded as a spreadsheet called DAILY_PRODUCTION_LOAD

Each TABLE may produce up to (N) PANELs per shift. This is variable based on the TASK times of the screens assigned on a TABLE, and also OPERATOR availability based on the JOBs assigned to both TABLES in the CELL.   For calculation purposes, these will be referred to as (CELL)_(TABLE)_(ORDINAL).  Examples are RED_1_1, RED_1_2, RED_1_3, representing the first, second, and third screens produced on a RED_TABLE_1

PANEL refers to a production slot on a table.  It produces nothing until a JOB is FIRM_PLAN assigned to it.  All PANELs on ACTIVE CELLS have one additional assigned attribute from a list:  UNASSIGNED, ROUGH_PLAN, FINAL_PLAN

JOB is formatted as (6 digit Number)"-"(2 digit Number)"-"(1 digit Number).  This should be treated as a combined text string.  For example, the value 095678-2-1 would represent a valid JOB identifier.

The ORANGE_CELL can only be scheduled with JOBs identified as ORANGE_ELIGIBLE true in the DAILY_PRODUCTION_LOAD sheet.

All {NOT ORANGE} CELLs can be scheduled with any JOB on the DAILY_PRODUCTION_LOAD file, regardless of ORANGE_ELIGIBLE value.

TABLEs in a CELL work on different JOBs.  If a JOB requires more than 1 TABLE based on scheduling calculation, it should be in more than 1 CELL.  The document SCHEDULING_PROTOCOL will detail exceptions to this.

Each JOB has a calculated SCHED_QTY.  The calculation for SCHED_QTY is defined in PROGRAM_REQUIREMENTS.

When a JOB is assigned to a table, it will stay on the table until the required SCHED_QTY is complete, and required PANELs are run consecutively.  For example, if JOB 0123456-1-1 is on TABLE RED_1 with a SCHED_QTY of 4, PANELs RED_1_1, RED_1_2, RED_1_3, and RED_1_4 will all be JOB 0123456-1-1, and PANEL RED_1_5 will be a new JOB selected by the application.

In a cell, the primary scheduled constraint is the OPERATOR, and if {COLOR}_ACTIVE=true, there is an OPERATOR for that CELL.  If the SHIFT is STANDARD, there are 440 minutes of OPERATOR available.  If the SHIFT is OVERTIME, there are 500 minutes of OPERATOR available.  Setting of SHIFT is detail in the PROGRAM_REQUIREMENTS document.

The TASKs SETUP, LAYOUT, POUR, and UNLOAD require OPERATOR minutes, the TASK CURE does not require OPERATOR minutes. 

Every PANEL must have its TASKS completed in the sequence: SETUP, LAYOUT, POUR, CURE, UNLOAD.  TASKs must be performed in order on a PANEL, and subsequent tasks cannot be started unless the prior task is completed.

SETUP, LAYOUT, POUR, and UNLOAD TASKs require time on both a {CELL}_TABLE and OPERATOR time.  CURE TASK requires time on a {CELL}_TABLE only, and no OPERATOR time.	 

The OPERATOR cannot perform work on both TABLEs in a CELL at the same time.  CURE is the only TASK that can occur on a TABLE without the OPERATOR.

The OPERATOR is the scheduled constraint on the TABLES in a CELL.  The OPERATOR completes TASKs up to CURE on TABLE_1, then moves to TABLE_2 and completes TASKs up to CURE, then moves back to TABLE_1.

When the OPERATOR returns to a {COLOR}_TABLE after the CURE TASK is complete, the UNLOAD TASK is completed on that PANEL.  The OPERATOR will then SETUP the next JOB if SCHED_QTY on the current JOB is met, or proceed to LAYOUT TASK on the next PANEL of the current JOB.

Because the OPERATOR is the primary scheduling constraint, there is a scheduling element defined as FORCED_TABLE_IDLE.  If the TASKs performed on TABLE_2 require more OPERATOR minutes than the CURE on TABLE_1, TABLE_1 will be inactive after CURE and will experience FORCED_TABLE_IDLE time while it waits for OPERATOR availability to perform the UNLOAD TASK on TABLE_1.  This is an expected part of the process.

Because the OPERATOR is the constraint, there is a scheduling element defined as FORCED_OPERATOR_IDLE.  If the TASKs performed on TABLE_2 require less OPERATOR minutes than the CURE on TABLE_1, TABLE_2 TASKs will complete and the OPERATOR must wait for CURE to complete on TABLE_1 before the UNLOAD TASK can be performed.  FORCED_OPERATOR_IDLE is waste, and the purpose of the scheduling process is to eliminate or minimize it.

Both FORCED_TABLE_IDLE and FORCED_OPERATOR_IDLE are calculated based on the PANELs immediately preceding and following the PANEL on the alternate TABLE in the CELL.  Using RED CELL as an example, PANEL RED_1_1 will experience FORCED_TABLE_IDLE based on PANEL RED_2_1, or it may cause FORCED_OPERATOR_IDLE.  Then PANEL RED_2_1 may experience either of these based on PANEL RED_1_2.

The reason that each TABLE produces (N) panels is that exact planning of TASKs and FORCED_OPERATOR_IDLE make the process difficult to predict until exact PANELs are selected on each CELL TABLE.  That selection process is detailed in the SCHEDULING_PROTOCOL document. 
 
Because of the alternating pattern between TABLES inside a CELL, the number of PANELs completed on each TABLE in a CELL will be equal or no more than 1 different.

Each JOB has a EQUIVALENT numeric value, a WIRE_DIAMETER numeric value, and a MOLDS numeric value.  These variables are used to determine required time in minutes for various TASKs:  SETUP, LAYOUT, POUR, CURE, and UNLOAD.  The values for a PANEL on that specific JOB based on in spreadsheet CYCLE_TIME_CONSTANTS.

Each JOB with a WIRE_DIAMETER less than 5 requires availability of a FIXTURE.  FIXTURE is a calculated field, and is identified by the combination of PATTERN "-" OPENING_SIZE "-" WIRE_DIAMETER from the DAILY_PRODUCTION_LOAD spreadsheet.  For example, a JOB 095678-2-1 might require FIXTURE D-0.2500-2.  Two JOBs use the same fixture if all three variables are an exact match.

If a JOB has a WIRE_DIAMETER of 5 or larger, it does not require a FIXTURE, and can be scheduled on any available {CELL}_TABLE.  These jobs are still constrained in the same way (limited concurrent usage), but they do not consume FIXTURES.
 
FIXTURE_QTY for a FIXTURE defines how many {CELL}_TABLES can be scheduled with that FIXTURE.  FIXTURE_QTY is based on the PATTERN field in the FIXTURE, and that quantity is defined in spreadsheet CYCLE_TIME_CONSTANTS, on the FIXTURES sheet.  If PATTERN=D has FIXTURE_QTY=4 and a JOB requires FIXTURE D-0.2500-2, it can only be scheduled if there are 3 or less {CELL}_TABLES already scheduled with FIXTURE D-0.2500-2.  If a {CELL}_TABLE is scheduled with FIXTURE D-0.2500-2.5, it does not matter.  FIXTURE_QTY applies to each specific FIXTURE, and is not the sum of all scheduled FIXTURES of that PATTERN.

The duration of the TASK SETUP is in OPERATOR minutes, but the TASK is not required on every PANEL.  On a specific TABLE, if the scheduled CELL_TABLE_PANEL_N uses the same FIXTURE as CELL_TABLE_PANEL_(N-1), the SETUP is 0 minutes.  Also, if the PANEL CELL_TABLE_1 has a JOB already assigned to it based on the value in ON_TABLE_TODAY in spreadsheet DAILY_PRODUCTION_LOAD, the SETUP is 0 minutes.

The duration of TASK LAYOUT is in OPERATOR minutes.  It is required on every PANEL

The duration of TASK POUR is calculated.  It is the result of (POUR from CYCLE_TIME_CONSTANTS) multiplied by (MOLDS from DAILY_PRODUCTION_LOAD).  This result is the number of OPERATOR minutes required.

The TASK POUR cannot be started if there are less than 40 OPERATOR minutes remaining in the SHIFT.  When a PANEL completes the LAYOUT TASK with less than 40 minutes remaining in the SHIFT, no further actions can be scheduled on that {COLOR}_TABLE.  The OPERATOR is available to UNLOAD the other TABLE in the CELL when its CURE TASK completes, and can SETUP and LAYOUT a PANEL on that TABLE, but will not be able to POUR.  If both {COLOR}_TABLES have LAYOUT TASKS complete with less than 40 minutes remaining in the SHIFT, no additional work will be scheduled in that {COLOR}_CELL.

The duration of the TASK CURE is in minutes.  It is a calculated value based on the result of (CURE from CYCLE_TIME_CONSTANTS) times (1.5 if SUMMER=true, 1 if SUMMER=false).  The value for SUMMER is in the PROGRAM_INPUTS portion of the application.  This task does not require OPERATOR minutes, but no other work can be completed on the CELL_TABLE for the duration of this CURE.

If the calculated CURE on one CELL_TABLE is longer than the sum of UNLOAD+SETUP (if required)+LAYOUT+POUR on the other CELL_TABLE, OPERATOR minutes cannot be used on that TABLE until the CURE completes.  When CURE completes, the UNLOAD TASK can be performed.  This was described above as FORCED_OPERATOR_IDLE.

If the calculated CURE on one CELL_TABLE is shorter than or equal to the sum of UNLOAD+SETUP (if required)+LAYOUT+POUR on the other CELL_TABLE, the UNLOAD TASK cannot be performed until the OPERATOR is available.  The OPERATOR can return to this table and perform the UNLOAD TASK when they complete the POUR TASK on the other CELL_TABLE.  This was described above as FORCED_TABLE_IDLE.

The duration of TASK UNLOAD is in OPERATOR minutes.  It is required on every PANEL.  At the conclusion of UNLOAD, the OPERATOR immediately begins a next PANEL on the same {COLOR}_TABLE.

SHIFTS are expected to end with a JOB on each {CELL}_TABLE, and the JOB will be in some stage of completion.  This means the first PANEL scheduled on every {COLOR}_TABLE will have to have its starting TASK determined.

If a {COLOR}_CELL has no JOBs identified on either CELL_TABLE in ON_TABLE_TODAY:
It is available to have any JOB scheduled to either TABLE.
No {COLOR}_MOLDS matching the {COLOR}_CELL are in use on either TABLE, so all are available for scheduling.
No FIXTUREs are assigned to either TABLE.
The first PANEL scheduled to either TABLE will require the full SETUP TASK from CYCLE_TIME_CONSTANTS and OPERATOR minutes.

If a {COLOR}_CELL has a JOB identified on only one {COLOR}_TABLE in ON_TABLE_TODAY:
The indicated JOB has its SETUP TASK set to 0 minutes on PANEL 1.
The indicated JOB has its LAYOUT TASK completed on PANEL 1 only.
The OPERATOR will begin the SHIFT with the POUR TASK on this JOB before going to work on the other CELL_TABLE.
The other CELL_TABLE is available to have any JOB scheduled per the SCHEDULING_PROTOCOL rules, and that JOB will begin with the SETUP TASK and required OPERATOR minutes.
{COLOR}_MOLDS will be assigned to the ON_TABLE_TODAY JOB, and will impact calculations of what JOB can be scheduled on the other CELL_TABLE.
A FIXTURE will be assigned to the JOB that is ON_TABLE_TODAY, and will potentially impact JOB scheduling on all other CELLs.

If a {COLOR}_CELL has a JOB identified on both {COLOR}_TABLEs in ON_TABLE_TODAY:
Both JOBs have their respective SETUP TASK set to 0 minutes on PANEL 1.
The JOB with the lowest EQUIVALENT value has its LAYOUT TASK completed on PANEL 1 only.  If both JOBs have the same EQUIVALENT, the JOB with the largest calculated CURE TASK will have its LAYOUT TASK completed.  If both EQUIVALENT and CURE have the same value, the JOB with the largest SCHED_QTY will have the LAYOUT TASK completed.
This will result in one JOB ready to POUR and one JOB ready to LAYOUT.  The OPERATOR will perform the POUR TASK on that JOB's TABLE before proceeding to LAYOUT on the other TABLE.
MOLDs need to be assigned to the JOB's on both TABLES.  If the quantity of {COLOR}_MOLD required exceeds the quantity of {COLOR}_MOLD available, COMMON_MOLDs will be assigned to the JOBs.
A FIXTURE will be assigned to each JOB that is ON_TABLE_TODAY, and will potentially impact JOB scheduling on all other CELLs.
This {COLOR}_CELL will have to complete the SCHED_QTY on one of its CELLs before a next JOB can be scheduled.

SHIFTS start with either CELL_TABLEs available to accept any JOB, or with a JOB in progress.  If a JOB is in progress, it will be entered into the spreadsheet DAILY_PRODUCTION_LOAD in the column ON_TABLE_TODAY.  The specific cell will list {COLOR}_1 or {COLOR}_2 to show the exact TABLE.  PANEL_1 on that TABLE will be that JOB.

JOBs require one FIXTURE for the entire elapsed time from SETUP on the first PANEL until UNLOAD on the last PANEL.  After UNLOAD of the last PANEL, the FIXTURE is available for use on any other CELL or TABLE.  

In addition to FIXTURES, JOBs require MOLDs to complete the SETUP.  The number of MOLDs required is listed in the DAILY_PRODUCTION_LOAD sheet, in the column MOLDS.  These required MOLDs have to be of the correct MOLD_TYPE as listed on the MOLDS sheet in CYCLE_TIME_CONSTANTS.  

The file CYCLE_TIME_CONSTANTS details MOLD_TYPE, MOLD_QTY for each MOLD_TYPE, and whether the mold can be used on a cell.  The column RED_COMPLIANT contains true false values showing if a mold can be used on CELL=RED.  There is a column for every CELL compliance.  When scheduling a JOB on a {CELL}_TABLE, WIRE_DIAMETER is considered first, to determine if DEEP_MOLDs are required.  

JOBs require MOLDs for the entire elapsed time from SETUP on the first PANEL until UNLOAD on the last PANEL.  After UNLOAD of the last PANEL, the MOLDs are available for use on any other JOB on the CELL or TABLE, or to be moved to a different {COLOR}_CELL if required.

When scheduling JOBs, if the JOB being scheduled uses the same FIXTURE as the previous job on the same CELL_TABLE, the SETUP TASK for the JOB being scheduled will take 0 minutes.  

If no FIXTURE_QTY is available for the FIXTURE required on a JOB, that JOB cannot be scheduled until a FIXTURE_QTY becomes available for it.

In addition to FIXTURES, JOBs require MOLDs to complete the SETUP.  

The number and type of MOLDs required is listed in the DAILY_PRODUCTION_LOAD sheet, in the columns MOLDS and MOLD_TYPE.  The software will calculate an additional field MOLD_DEPTH for every job.  

There are three possible MOLD_TYPE entries: "STANDARD", "DOUBLE2CC", and "3INURETHANE".

For each JOB, if WIRE_DIAMETER is equal to or greater than 8, MOLD_DEPTH value is "DEEP".  For and JOB with WIRE_DIAMETER less than 8, MOLD_DEPTH is "STD".

The file CYCLE_TIME_CONSTANTS has a sheet title MOLDS.  This details the quantity of MOLDS available of each MOLD_NAME, and indicates what {COLOR} CELL can use that mold.  The columns {COLOR}_COMPLIANT are true/false fields that must be true for a CELL_TABLE to be scheduled with a JOB requiring that MOLD_NAME.

A JOB cannot be scheduled on a CELL unless there are sufficient available MOLDS of the correct MOLD_NAME to equal or exceed the MOLDS value associated with the JOB.  These required MOLDs have to be of the correct MOLD_NAME(s) and MOLD_DEPTH as listed on the MOLDS sheet in CYCLE_TIME_CONSTANTS.

A JOB with MOLD_DEPTH = "DEEP" and MOLD_TYPE="STANDARD" requires a quantity of DEEP_MOLD equal to the JOB's MOLDS value in DAILY_PRODUCTION_LOAD.  

A JOB with MOLD_DEPTH = "DEEP" and MOLD_TYPE="3INURETHANE" OR "DOUBLE2CC" requires a quantity of DEEP_MOLD equal to the JOB's (MOLDS - 1) AND one piece of DEEP_DOUBLE2CC_MOLD.

A JOB with MOLD_DEPTH = "STD" and MOLD_TYPE="STANDARD" requires a quantity of {COLOR}_MOLD equal to the JOB's MOLDS value in DAILY_PRODUCTION_LOAD, with {COLOR} matching the CELL being scheduled.  

A JOB with MOLD_DEPTH = "STD" and MOLD_TYPE="3INURETHANE" requires a quantity of {COLOR}_MOLD equal to the JOB's (MOLDS - 1) AND one piece of 3INURETHANE_MOLD.  The {COLOR}_MOLD should match the CELL being scheduled.

A JOB with MOLD_DEPTH = "STD" and MOLD_TYPE="DOUBLE2CC" requires a quantity of {COLOR}_MOLD equal to the JOB's (MOLDS - 2) AND one piece of DOUBLE2CC_MOLD.  The {COLOR}_MOLD should match the CELL being scheduled.

If there are insufficient {COLOR}_MOLD to allow SETUP of the JOB, any COMMON_MOLD not currently in use on another JOB may be used in addition to the {COLOR}_MOLD.  In the event that there are not sufficient COMMON_MOLDs available, {COLOR}_MOLD that are {COLOR}_COMPLIANT on a NOT ACTIVE {COLOR}_CELL may be used provided they are not already assigned to a JOB that is SETUP on the NOT ACTIVE {COLOR}_CELL.  If this sequence does not provide adequate available MOLDs, the JOB cannot be scheduled.

CELLs can use MOLDs from other {COLOR}_COMPLIANT CELLs, and this complexity will be explained in SCHEDULING_PROTOCOL document.  Because scheduling is an interactive process, unlimited MOLD sharing on first CELLs scheduled may result in a lack of MOLDS to positively schedule all ACTIVE CELLs.  This process will be detailed in a separate document.
