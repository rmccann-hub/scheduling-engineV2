DOCUMENT GUIDE:
-Collectively these documents will provide the LLM with guidance for creating the scheduling tool.
-These documents are: CELL_RULES_SIMPLIFIED, this document PROGRAM_REQUIREMENTS, CYCLE_TIME_CONSTANTS, DAILY_PRODUCTION_LOAD, and SCHEDULING_PROTOCOL.
-These documents, for the purposes of building and iterating the program, will live in a folder called Documents within the https://github.com/rmccann-hub/scheduling-engineV2 repository. This will not only give the program and rules in one source location, but allow for the documentation to be updated if needed by the LLM and pushed back to GitHub.
-This is a fresh build of the scheduling engine. Previous iterations should be disregarded.
-Before making any changes to the program, read through all of the documentation. Look for inconsistencies, conflicts, gaps, etc. and let the user know, preferably by asking questions and then updating the documentation as needed. Then push the updates back to GitHub.
-Once documentation is complete and understood, but before making any changes to the program, execute the Claude skill-orchestrator skill (and by doing so, any relevant skill branches).
-If any new documentation is created, such as a detailed plan, create this document in the same Documents folder.
-Once the skills are active you are good to start making program modifications. The goal is to be as modular as possible so that when iterating, fixing errors, or adding functionality, the fewest amount of tokens are used/files updated.
-The approach to updating the program should be taken in steps. Make a change, update, have the user test the program and confirm working or not, then move on to the next step. Push updates to GitHub after every successful step.

PROGRAM_REQUIREMENTS

GENERAL OVERVIEW:

This is a fresh build of the scheduling engine using OR-Tools constraint programming solver. We want to get this to a polished state that will be as straightforward as possible for the end users (non-technical) to use. We are trying to leverage the ability of software to have all variables in mind simultaneously, which a human cannot do, and to iterate as much as necessary to get the best results. This is not to say we want a program which will take 30 minutes to run. In the testing stage if we need to try different methods which take some time in order to narrow down to what works for the final version, this is fine.

All program user interfaces and outputs should follow the my-theme skill for formatting, font, colors, etc.

On execution the program should check that all dependencies are installed, and if not automatically install if possible, if not possible direct users to what they need and where to find it.

If there are version numbers present in the files, all version numbers should match. If needed start with a fresh version on the first build of this new project, start at 1.0.0.

The purpose of the program is to schedule six production work cells to meet required dates and maximize panel production from those work cells.

Variable data is included in the spreadsheet entitled CYCLE_TIME_CONSTANTS.  This data is meant to be built into the software, but has certain variables that can be modified inside the program behind a password protected layer.  More detail will be provided on the individual sheets in this document.

The document CELL_RULES_SIMPLIFIED contains all of the hard coded rules that determine the possibilities of scheduling.  Work cells and tables are defined, and interaction of elements are defined here.  These rules are not intended to be updated internally to the program, and if conflicts must be resolved, the rules will be edited and new program code generated.

The document SCHEDULING_PROTOCOL will document multiple methods of scheduling the work cells, with each method having two variants.  The program will not show both variants, but will choose the variant with the fewest missed dates.  If neither variant misses any dates, it will show the variant with the largest number of produced panels.  The purpose of the multiple methods is to allow the supervisor to select the preferred schedule.

The spreadsheet DAILY_PRODUCTION_LOAD will be loaded into the program each day.  This is a list of JOBs to be scheduled.  The list will likely include more JOBs than can be scheduled in a production day, and that is intended.  The program will select the appropriate jobs to meet BUILD_DATE first, and maximize the number of panels produced second.

The program will allow input of data by the operator prior to executing the scheduling process.  Specifics will be detailed below, but the summary is:
Update the DAILY_PRODUCTION_LOAD sheet to show JOBs already set up on work cells, and quantity remaining on those jobs.
Update the DAILY_PRODUCTION_LOAD sheet to show JOBs that require expediting to supercede calculated SCHEDULED_BUILD_DATE.
Indicate which of the six work cells are staffed and ACTIVE.
Indicate whether SHIFT is "standard" or "overtime".
Enable or disable the ORANGE CELL.
Enable or disable the SUMMER status.
Show a default calendar date of the current date, but allow it to be overridden to test alternate schedules.  The date will be referred to as TODAY.
This date input should only allow WEEKDAYS and must also exclude any dates listed in sheet HOLIDAYS from CYCLE_TIME_CONSTANTS

Once this data is populated, the operator will EXECUTE the scheduling process described above.  There are multiple calculated fields that will be created for each JOB on the DAILY_PRODUCTION_LOAD, and these calculated fields will be used in determining scheduling sequence and capacities on each cell.  This will result in creation of detailed schedules and summaries showing the number of panels expected, and the number of jobs due or past due that could not be scheduled. 

Based on these summaries, the operator will select one schedule to perform the detailed schedule and generate the required outputs.  These outputs are:
All outputs, except the Gantt chart, are to be in PDF format, standard size, formatted for easy and quick readability.
Detailed work cell report for each ACTIVE work cell.  This report will include:
Planned JOBs for both TABLES in the CELL, listing quantity required.  The JOB will be identified by the JOB Text String and the Description
Any required use of MOLDs that don't match the CELL {COLOR}.
Expected total output.
A blank line under each table for the operators to record what JOB they end on and quantity remaining.
A supervisor summary report that lists all six cells, states ACTIVE or NOT ACTIVE.
Each cell should list expected completion amounts.
Each cell should list any required MOLDs that don't match CELL {COLOR}.
A list of jobs that should have been scheduled and could not be.
Gantt charts for each cell as well as for the entire schedule.
These will primarily be used during testing to make sure the scheduling rules are followed.
These need to be detailed and possibly in a format that allows for a easier time to dig into details. Especially over an 8 hour period on a normally sized page the chart gets too small and compressed to see all the detail. Maybe this needs to be in a HTML or other format. I will leave this up to you.
A testing output Excel file which includes the input daily load columns plus the calculated columns that are used internally for scheduling.

Detailed explanation of DAILY_PRODUCTION_LOAD
Information loaded in an Excel spreadsheet format uploaded daily:
ROW 1 contains header information
All subsequent ROWs indicate an individual JOB.

COLUMN A:  REQ_BY:  Date format field that shows product ship date.  This will be used to calculate the SCHEDULED_BUILD

COLUMN B:  JOB:  text string.  Unique identifier.  Each job is something that must be evaluated for scheduling through the program

COLUMN C:  DESCRIPTION:  text string.  Will be printed on individual work cell report but not used for any calculation

COLUMN D:  PATTERN:  single character list:  "D", "V", or "S".  Used in creation of FIXTURE and to determine how many instances of that FIXTURE can be used concurrently, based on information from CYCLE_TIME_CONSTANTS sheet FIXTURES.

COLUMN E:  OPENING_SIZE:  decimal number used in creation of FIXTURE.

COLUMN F:  WIRE_DIAMETER:  decimal number.  Used in the creation of FIXTURE.  Used in look up for TASK cycle time in minutes.  Used in look up for SCHEDULING_CONSTANT.  Used in determination of MOLD_DEPTH.  Use ranges for lookups (<=4, >4 and <8, >=8).

COLUMN G:  MOLDS:  integer number of required MOLDs.  Available molds are listed in CYCLE_TIME_CONSTANTS, and rules for MOLD assignment are in CELL_RULES_SIMPLIFIED.

COLUMN H:  MOLD_TYPE:  text field from list: "STANDARD", "DOUBLE2CC", "3INURETHANE".  Used in assignment of MOLDs when scheduling JOB on {COLOR}_TABLE

COLUMN I:   PROD_QTY:  integer number of total number of panels required on the JOB.  Does not account for already built panels.

COLUMN J:  EQUIVALENT:  number used to equate difficulty of assembly of a panel.  Used in conjunction with WIRE_DIAMETER to determine TASK minutes and SCHEDULING_CONSTANT from CYCLE_TIME_CONSTANTS sheet values.  Also used in scheduling algorithms in conjunction with PRIORITY to finite assign JOBs to {COLOR}_TABLE

COLUMN K:  ORANGE_ELIGIBLE:  true/false variable.  If true, allows JOB to be scheduled on ORANGE CELL.  

Information to be added to each JOB row in the program by the operator:
ON_TABLE_TODAY:  If the JOB is already SETUP on a {COLOR} TABLE, the program operator will indicate which table it is on from a drop down list.  List options are:  RED_1, RED_2, BLUE_1, BLUE_2, GREEN_1, GREEN_2, BLACK_1, BLACK_2, PURPLE_1, PURPLE_2, ORANGE_1, ORANGE_2. These should take the form of a dropdown list to ensure data validation, and ORANGE tables should only be allowed if ORANGE CELL is enabled by the user and ORANGE_ELIGIBLE is true.  If a job is entered on an ORANGE table but ORANGE_ELIGIBLE is false, accept it with a warning.

If ON_TABLE_TODAY is populated, a cell JOB_QUANTITY_REMAINING must be populated with an integer that cannot be 0 and cannot be greater than the value of PROD_QTY.

EXPEDITE:  if there are requirements to expedite an order regardless of priority date, a cell for the job must be set to EXPEDITE yes.

Information to be calculated for each JOB:  
These are values that do not need to be published, but will be required calculations for each JOB in DAILY_PRODUCTION_LOAD.  The values calculated will be used in the different scheduling algorithms

SCHED_QTY:  integer.  If ON_TABLE_TODAY is blank, this equals PROD_QTY.  If ON_TABLE_TODAY is populated, this is JOB_QUANTITY_REMAINING.

BUILD_LOAD:  two place number, calculated from SCHED_QTY times EQUIVALENT divided by SCHED_CONSTANT.  This is a representative of the anticipated number of CELL shifts required to complete the job.  SCHED_CONSTANT is based on WIRE_DIAMETER and EQUIVALENT from the sheet CYCLE_TIME_CONSTANTS

BUILD_DATE:  calendar date.  Weekdays only.  Calculated by subtracting (ROUNDUP(BUILD_LOAD + PULL_AHEAD)) days from REQ_BY date of JOB.  Only count WEEKDAYS in the calculation.  Must also exclude any dates listed in sheet HOLIDAYS from CYCLE_TIME_CONSTANTS

PRIORITY:  number assignment to set order sequence for scheduling algorithms.  Calculated as follows:
0:	Past due.  (BUILD_DATE is earlier than the TODAY) OR (BUILD_DATE equals TODAY and EXPEDITE = TRUE)
1:	On schedule:  BUILD_DATE equals TODAY.
2:     	Expedite:  BUILD_DATE after TODAY and EXPEDITE = true
3:	Ahead of Schedule:   BUILD_DATE after TODAY

FIXTURE:  identifier for the FIXTURE made of concatenating PATTERN + "-" + OPENING_SIZE + "-" + WIRE_DIAMETER.  Used in scheduling algorithms to determine how many {COLOR}_TABLES can be used concurrently and if SETUP tasks can be eliminated between JOBs.

MOLD_DEPTH:  value from list: "DEEP" or "STD".  If WIRE_DIAMETER is 8 or larger, this value is "DEEP".  If WIRE_DIAMETER is less than 8, this value is "STD".  MOLD_DEPTH is used in MOLD selection when determining if a JOB can be scheduled.

SCHED_CLASS:  Alphabet character from CYCLE_TIME_CONSTANTS based on WIRE_DIAMETER and EQUIVALENT.  Used to sort and group JOBS in the scheduling methods defined in SCHEDULING_PROTOCOL.


EDITABLE VARIABLE DATA:

Variable information to be built into the program, with ability to edit hidden behind a password protected approval.  Could be labelled as settings or configure.

All data is originally contained in the file CYCLE_TIME_CONSTANTS.  This file will only be used at time of program creation, and restructure to the data will require redefinition outside of the program, and recreation.

CYCLE_TIME_CONSTANTS contains multiple sheets, and each sheet should be its own table.  They can all be on a single page, or can be different pages in the program.

Sheet TASK:
Data range is A1:J16.  Values in B2:J16 should be editable.  Columns A & B are used to look up values in columns C through J.  Columns C through G represent minutes required on a {COLOR}_TABLE to complete the TASK listed in ROW 1.  Column H is a constant used to calculate BUILD_LOAD and therefore BUILD_DATE.  Column I is a look up for SCHED_CLASS, which is used for sorting and scheduling as detailed in SCHEDULING_PROTOCOL.  Column J is a look up for PULL_AHEAD, which is a factor used to modify BUILD_DATE.

Sheet  MOLDS:
Data range is A1:J12.  Values in D2:D12 need to be editable.  Column D is quantity of specific MOLD_NAME available to be on all {COLOR}_TABLE concurrently.  Columns E through J show true false whether MOLD is eligible to be used on different {COLOR} Table.

Sheet FIXTURES:
Data range is A1:C4.  Values in C2:C4 need to be editable.  Column C shows how many {COLOR} TABLEs can be SETUP concurrently with a FIXTURE based on the PATTERN element of the FIXTURE.

Sheet HOLIDAYS:
Data range is A1:B9.  Values in B2:B9 need to be editable.  Values are date format.  When determining BUILD_DATE, any value listed in this table is not counted.


MOLD AVAILABILITY RULES:

When a {COLOR}_CELL is ACTIVE, its {COLOR}_MOLDs are reserved for that cell and cannot be used elsewhere.
When a {COLOR}_CELL is NOT ACTIVE, its {COLOR}_MOLDs can be used on any cell where they are marked as compliant in the MOLDS sheet.
COMMON_MOLDs can be used on any compliant cell regardless of ACTIVE status, but cannot be used concurrently on multiple jobs.


FUTURE STATE:
These are things which we do not need in the current version of the program, but I am stating so that if there are prerequisites, setup, or foundation needed that these can be included now to be ready for implementation later.
-For initial testing, running this locally is perfect. But eventually I want to be able to run this on a windows 11 or windows server 2022 and have users load up the webpage on their computer.
-Eventually I want to replace the DAILY_PRODUCTION_LOAD excel spreadsheet upload with a direct API connection to Epicor/Kinetic. It will still get the exact same data in the same format.
