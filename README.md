# Cell Scheduling Engine

Thermoforming production scheduler using Google OR-Tools CP-SAT constraint programming solver.

## Features

- **Web-based Interface** - Modern UI for uploading production loads and configuring schedules
- **Multiple Scheduling Methods** - 4 methods × 3 variants = 12 different scheduling strategies
- **Interactive Gantt Charts** - Visual timeline with task tooltips
- **Downloadable Outputs** - HTML Gantt charts, PDF summary reports, Debug Excel, and per-cell PDF reports
- **ON_TABLE_TODAY Support** - Pre-position jobs already on tables
- **Multi-Cell Scheduling** - Coordinate 6 cells (RED, BLUE, GREEN, BLACK, PURPLE, ORANGE)
- **Fixture Optimization** - FIXTURE_FIRST variant minimizes SETUP time by grouping same-fixture jobs

## Quick Start

### Windows

1. Extract the zip file
2. Double-click `run_web.bat`
3. Open your browser to **http://localhost:8000**

### Linux/Mac

```bash
pip install -r requirements.txt
python -m uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Then open **http://localhost:8000**

## Usage

1. **Upload Production Load** - Click or drag your `DAILY_PRODUCTION_LOAD.xlsx` file
2. **Configure Jobs** - Set ON_TABLE_TODAY for jobs already on tables
3. **Set Options** - Choose date, active cells, shift type, summer mode
4. **Run Scheduler** - Click "Run Scheduler" to generate the schedule
5. **Download** - Export results as HTML, PDF, JSON, or text report

## Scheduling Methods

| Method | Description |
|--------|-------------|
| **Priority First** | Schedule by priority level (Past Due → Today → Expedite → Future) |
| **Minimum Forced Idle** | Minimize table and operator idle time |
| **Maximum Output** | Maximize total panels produced |
| **Most Restricted Mix** | Pair D/E classes opposite C for efficiency |

Each method can run in three variants:
- **Job First** - Select the best job, then find the best table for it
- **Table First** - Select the next table, then find the best job for it
- **Fixture First** - Group jobs by fixture to minimize SETUP time (saves 10 min per reused fixture)

All 12 combinations run automatically and the best result is selected.

## Project Structure

```
scheduling-engineV2/
├── run_web.bat              # Start web server (Windows)
├── requirements.txt         # Python dependencies
│
├── web/                     # Web interface
│   ├── app.py               # FastAPI backend
│   └── static/
│       └── index.html       # Frontend UI
│
├── Documents/               # Data files
│   ├── CYCLE_TIME_CONSTANTS.xlsx
│   └── DAILY_PRODUCTION_LOAD.xlsx
│
└── src/                     # Core scheduling engine
    ├── constants.py         # Load CYCLE_TIME_CONSTANTS
    ├── data_loader.py       # Load DAILY_PRODUCTION_LOAD
    ├── calculated_fields.py # SCHED_QTY, BUILD_DATE, PRIORITY
    ├── constraints.py       # OR-Tools constraint builders
    ├── scheduler.py         # Single-cell scheduler
    ├── multi_cell_scheduler.py  # Multi-cell coordination
    ├── method_variants.py   # 4 methods × 3 variants = 12 combinations
    ├── method_evaluation.py # Method comparison
    ├── validator.py         # Input validation and operator settings
    ├── resources.py         # Mold/fixture pool management
    └── output_generator.py  # Reports and exports
```

## Requirements

- Python 3.9+
- ortools (Google OR-Tools)
- openpyxl (Excel support)
- fastapi (Web framework)
- uvicorn (Web server)

## Input Files

### CYCLE_TIME_CONSTANTS.xlsx

Task timings by pattern, mold type, and operation type.

### DAILY_PRODUCTION_LOAD.xlsx

Jobs to schedule with columns:
- JOB_ID, DESCRIPTION, REQ_BY, PROD_QTY
- PATTERN, MOLDS, MOLD_TYPE
- ORANGE_ELIGIBLE, ON_TABLE_TODAY, etc.

## License

MIT License
