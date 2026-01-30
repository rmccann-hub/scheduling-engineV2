"""
Cell Scheduling Engine - FastAPI Web Backend
"""

import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Depends, Header
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import __version__
from src.constants import (
    load_constants_from_yaml,
    save_constants_to_yaml,
    CycleTimeConstants,
    TaskTiming,
    MoldInfo,
    FixtureLimit,
    Holiday,
    CELL_COLORS,
)
from src.data_loader import load_daily_production, Job, DailyProductionLoad
from src.validator import OperatorInputs
from src.calculated_fields import calculate_fields_for_job
from src.method_variants import (
    SchedulingMethod, SchedulingVariant,
    run_method, run_all_methods,
)
from src.method_evaluation import evaluate_result, rank_methods
from src.output_generator import (
    generate_schedule_report,
    generate_html_gantt,
    export_to_json,
)

# Initialize FastAPI app
app = FastAPI(
    title="Cell Scheduling Engine",
    description="Thermoforming Production Scheduler with OR-Tools CP-SAT Solver",
    version=__version__
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global data holders
constants: CycleTimeConstants = None
production_load = None
user_job_settings = {}

# Store all schedule results for downloads and method switching
all_schedule_results = {}  # {(method, variant): result}
last_schedule_result = None
last_schedule_method = None
last_schedule_variant = None
best_method_key = None  # (method, variant) tuple for best result


def get_base_path():
    return Path(__file__).parent.parent


def get_config_path():
    return get_base_path() / "config" / "constants.yaml"


class ScheduleRequest(BaseModel):
    schedule_date: str
    active_cells: list[str]
    shift_type: str = "standard"
    summer_mode: bool = False
    method: str = "all"
    variant: str = "both"


class JobSetting(BaseModel):
    job_id: str
    on_table_today: Optional[str] = None  # e.g., "RED_1", "BLUE_2", etc.
    cell_color: Optional[str] = None
    table_num: Optional[int] = None
    starts_with_pour: bool = False
    expedite: bool = False
    qty_remaining: Optional[int] = None


class SingleJobSetting(BaseModel):
    job_id: str
    expedite: bool = False
    on_table_today: Optional[str] = None  # e.g., "RED_1"
    qty_remaining: Optional[int] = None


# Settings models
class GeneralSettings(BaseModel):
    admin_password: str
    standard_shift: int
    overtime_shift: int
    summer_cure_multiplier: float
    pour_cutoff_minutes: int
    max_layout_pour_gap: int


class TaskTimingUpdate(BaseModel):
    wire_diameter: str
    equivalent: str
    setup: int
    layout: int
    pour_per_mold: float
    cure: int
    unload: int
    sched_constant: int
    sched_class: str
    pull_ahead: float


class MoldUpdate(BaseModel):
    name: str
    depth: str
    wire_diameter: str
    quantity: int
    cells: dict[str, bool]


class FixtureUpdate(BaseModel):
    pattern: str
    description: str
    quantity: int


class HolidayUpdate(BaseModel):
    label: str
    date: str


@app.on_event("startup")
async def load_data():
    """Load constants on startup."""
    global constants
    
    config_path = get_config_path()
    
    try:
        constants = load_constants_from_yaml(str(config_path))
        print(f"Loaded {len(constants.task_timings)} task timings from YAML")
        print(f"Loaded {len(constants.molds)} molds")
        print(f"Loaded {len(constants.fixtures)} fixtures")
        print(f"Loaded {len(constants.holidays)} holidays")
    except Exception as e:
        print(f"ERROR loading constants: {e}")
        raise
    
    print("Ready - waiting for user to upload daily production load")


def verify_password(password: str) -> bool:
    """Verify admin password."""
    return password == constants.admin_password


@app.get("/")
async def root():
    """Serve the main HTML page."""
    html_path = Path(__file__).parent / "static" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(), status_code=200)
    return HTMLResponse(content="<h1>Cell Scheduling Engine</h1>")


@app.get("/api/config")
async def get_config():
    """Get available configuration options."""
    return {
        "version": __version__,
        "cells": list(CELL_COLORS),
        "methods": [
            {"id": "1", "name": "Priority First"},
            {"id": "2", "name": "Minimum Forced Idle"},
            {"id": "3", "name": "Maximum Output"},
            {"id": "4", "name": "Most Restricted Mix"},
            {"id": "all", "name": "Run All Methods"},
        ],
        "variants": [
            {"id": "job", "name": "Job First"},
            {"id": "table", "name": "Table First"},
            {"id": "both", "name": "Both Variants"},
        ],
        "shift_types": [
            {"id": "standard", "name": f"Standard ({constants.shifts.get('standard', 440)} min)"},
            {"id": "overtime", "name": f"Overtime ({constants.shifts.get('overtime', 500)} min)"},
        ],
        "has_production_load": production_load is not None,
        "jobs_count": len(production_load.jobs) if production_load else 0,
    }


# ============ SETTINGS ENDPOINTS ============

@app.post("/api/settings/verify")
async def verify_settings_password(password: str = Form(...)):
    """Verify password for settings access."""
    if verify_password(password):
        return {"success": True}
    raise HTTPException(status_code=401, detail="Invalid password")


@app.get("/api/settings/general")
async def get_general_settings(password: str = Header(None, alias="X-Admin-Password")):
    """Get general settings."""
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    return {
        "admin_password": constants.admin_password,
        "standard_shift": constants.shifts.get('standard', 440),
        "overtime_shift": constants.shifts.get('overtime', 500),
        "summer_cure_multiplier": constants.summer_cure_multiplier,
        "pour_cutoff_minutes": constants.pour_cutoff_minutes,
        "max_layout_pour_gap": constants.max_layout_pour_gap,
    }


@app.post("/api/settings/general")
async def update_general_settings(
    settings: GeneralSettings,
    password: str = Header(None, alias="X-Admin-Password")
):
    """Update general settings."""
    global constants
    
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    # Update constants
    new_constants = CycleTimeConstants(
        task_timings=constants.task_timings,
        molds=constants.molds,
        fixtures=constants.fixtures,
        holidays=constants.holidays,
        holiday_list=constants.holiday_list,
        shifts={'standard': settings.standard_shift, 'overtime': settings.overtime_shift},
        summer_cure_multiplier=settings.summer_cure_multiplier,
        pour_cutoff_minutes=settings.pour_cutoff_minutes,
        max_layout_pour_gap=settings.max_layout_pour_gap,
        admin_password=settings.admin_password,
    )
    
    # Save to YAML
    save_constants_to_yaml(new_constants, get_config_path())
    constants = new_constants
    
    return {"success": True, "message": "General settings updated"}


@app.get("/api/settings/tasks")
async def get_task_timings(password: str = Header(None, alias="X-Admin-Password")):
    """Get all task timings."""
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    return {
        "tasks": [
            {
                "wire_diameter": t.wire_diameter,
                "equivalent": t.equivalent,
                "setup": t.setup,
                "layout": t.layout,
                "pour_per_mold": t.pour,
                "cure": t.cure,
                "unload": t.unload,
                "sched_constant": t.sched_constant,
                "sched_class": t.sched_class,
                "pull_ahead": t.pull_ahead,
            }
            for t in constants.task_timings
        ]
    }


@app.post("/api/settings/tasks")
async def update_task_timings(
    tasks: list[TaskTimingUpdate],
    password: str = Header(None, alias="X-Admin-Password")
):
    """Update all task timings."""
    global constants
    
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    new_timings = [
        TaskTiming(
            wire_diameter=t.wire_diameter,
            equivalent=t.equivalent,
            setup=t.setup,
            layout=t.layout,
            pour=t.pour_per_mold,
            cure=t.cure,
            unload=t.unload,
            sched_constant=t.sched_constant,
            sched_class=t.sched_class,
            pull_ahead=t.pull_ahead,
        )
        for t in tasks
    ]
    
    new_constants = CycleTimeConstants(
        task_timings=new_timings,
        molds=constants.molds,
        fixtures=constants.fixtures,
        holidays=constants.holidays,
        holiday_list=constants.holiday_list,
        shifts=constants.shifts,
        summer_cure_multiplier=constants.summer_cure_multiplier,
        pour_cutoff_minutes=constants.pour_cutoff_minutes,
        max_layout_pour_gap=constants.max_layout_pour_gap,
        admin_password=constants.admin_password,
    )
    
    save_constants_to_yaml(new_constants, get_config_path())
    constants = new_constants
    
    return {"success": True, "message": f"Updated {len(tasks)} task timings"}


@app.get("/api/settings/molds")
async def get_molds(password: str = Header(None, alias="X-Admin-Password")):
    """Get all molds."""
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    return {
        "molds": [
            {
                "name": m.mold_name,
                "depth": m.mold_depth,
                "wire_diameter": m.wire_diameter_range,
                "quantity": m.quantity,
                "cells": {cell: cell in m.compliant_cells for cell in CELL_COLORS},
            }
            for m in constants.molds.values()
        ]
    }


@app.post("/api/settings/molds")
async def update_molds(
    molds: list[MoldUpdate],
    password: str = Header(None, alias="X-Admin-Password")
):
    """Update all molds."""
    global constants
    
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    new_molds = {}
    for m in molds:
        mold_info = MoldInfo(
            mold_name=m.name,
            mold_depth=m.depth,
            wire_diameter_range=m.wire_diameter,
            quantity=m.quantity,
            compliant_cells=frozenset(c for c, v in m.cells.items() if v),
        )
        new_molds[m.name] = mold_info
    
    new_constants = CycleTimeConstants(
        task_timings=constants.task_timings,
        molds=new_molds,
        fixtures=constants.fixtures,
        holidays=constants.holidays,
        holiday_list=constants.holiday_list,
        shifts=constants.shifts,
        summer_cure_multiplier=constants.summer_cure_multiplier,
        pour_cutoff_minutes=constants.pour_cutoff_minutes,
        max_layout_pour_gap=constants.max_layout_pour_gap,
        admin_password=constants.admin_password,
    )
    
    save_constants_to_yaml(new_constants, get_config_path())
    constants = new_constants
    
    return {"success": True, "message": f"Updated {len(molds)} molds"}


@app.get("/api/settings/fixtures")
async def get_fixtures(password: str = Header(None, alias="X-Admin-Password")):
    """Get all fixtures."""
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    return {
        "fixtures": [
            {
                "pattern": f.pattern,
                "description": f.description,
                "quantity": f.max_concurrent,
            }
            for f in constants.fixtures.values()
        ]
    }


@app.post("/api/settings/fixtures")
async def update_fixtures(
    fixtures: list[FixtureUpdate],
    password: str = Header(None, alias="X-Admin-Password")
):
    """Update all fixtures."""
    global constants
    
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    new_fixtures = {}
    for f in fixtures:
        fixture_info = FixtureLimit(
            pattern=f.pattern,
            description=f.description,
            max_concurrent=f.quantity,
        )
        new_fixtures[f.pattern] = fixture_info
    
    new_constants = CycleTimeConstants(
        task_timings=constants.task_timings,
        molds=constants.molds,
        fixtures=new_fixtures,
        holidays=constants.holidays,
        holiday_list=constants.holiday_list,
        shifts=constants.shifts,
        summer_cure_multiplier=constants.summer_cure_multiplier,
        pour_cutoff_minutes=constants.pour_cutoff_minutes,
        max_layout_pour_gap=constants.max_layout_pour_gap,
        admin_password=constants.admin_password,
    )
    
    save_constants_to_yaml(new_constants, get_config_path())
    constants = new_constants
    
    return {"success": True, "message": f"Updated {len(fixtures)} fixtures"}


@app.get("/api/settings/holidays")
async def get_holidays(password: str = Header(None, alias="X-Admin-Password")):
    """Get all holidays."""
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    return {
        "holidays": [
            {
                "label": h.label,
                "date": h.date.isoformat(),
            }
            for h in constants.holiday_list
        ]
    }


@app.post("/api/settings/holidays")
async def update_holidays(
    holidays: list[HolidayUpdate],
    password: str = Header(None, alias="X-Admin-Password")
):
    """Update all holidays."""
    global constants
    
    if not password or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid password")
    
    new_holiday_list = [
        Holiday(
            label=h.label,
            date=datetime.strptime(h.date, "%Y-%m-%d").date(),
        )
        for h in holidays
    ]
    new_holidays = set(h.date for h in new_holiday_list)
    
    new_constants = CycleTimeConstants(
        task_timings=constants.task_timings,
        molds=constants.molds,
        fixtures=constants.fixtures,
        holidays=new_holidays,
        holiday_list=new_holiday_list,
        shifts=constants.shifts,
        summer_cure_multiplier=constants.summer_cure_multiplier,
        pour_cutoff_minutes=constants.pour_cutoff_minutes,
        max_layout_pour_gap=constants.max_layout_pour_gap,
        admin_password=constants.admin_password,
    )
    
    save_constants_to_yaml(new_constants, get_config_path())
    constants = new_constants
    
    return {"success": True, "message": f"Updated {len(holidays)} holidays"}


# ============ PRODUCTION LOAD ENDPOINTS ============

@app.post("/api/upload")
async def upload_production_load(file: UploadFile = File(...)):
    """Upload daily production load Excel file."""
    global production_load, user_job_settings
    
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="File must be Excel (.xlsx or .xls)")
    
    base_path = get_base_path()
    upload_path = base_path / "Documents" / "DAILY_PRODUCTION_LOAD.xlsx"
    
    try:
        with open(upload_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        production_load = load_daily_production(str(upload_path))
        user_job_settings = {}
        
        return {
            "success": True,
            "message": f"Uploaded {file.filename} with {len(production_load.jobs)} jobs",
            "jobs_count": len(production_load.jobs)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process file: {str(e)}")


@app.get("/api/jobs")
async def get_jobs():
    """Get list of jobs."""
    if not production_load:
        return {"jobs": [], "message": "No production load uploaded"}
    
    jobs = []
    schedule_date = date.today()
    
    for job in production_load.jobs:
        try:
            calc = calculate_fields_for_job(job, constants, schedule_date)
            priority = calc.priority
            sched_class = calc.sched_class
            sched_qty = calc.sched_qty
            build_date = str(calc.build_date)
        except:
            priority = 3
            sched_class = "B"
            sched_qty = job.prod_qty
            build_date = str(job.req_by)
        
        settings = user_job_settings.get(job.job_id, {})
        
        on_table_cell = None
        on_table_table = None
        if job.on_table_today:
            parts = job.on_table_today.rsplit("_", 1)
            if len(parts) == 2:
                on_table_cell = parts[0]
                on_table_table = int(parts[1])
        
        jobs.append({
            "job_id": job.job_id,
            "description": job.description[:60] + "..." if len(job.description) > 60 else job.description,
            "pattern": str(job.pattern),
            "molds": job.molds,
            "mold_type": str(job.mold_type),
            "prod_qty": job.prod_qty,
            "sched_qty": sched_qty,
            "req_by": str(job.req_by),
            "priority": priority,
            "sched_class": sched_class,
            "build_date": build_date,
            "orange_eligible": job.orange_eligible,
            "on_table_today": settings.get("on_table_today", job.on_table_today is not None),
            "on_table_cell": settings.get("cell_color", on_table_cell),
            "on_table_table": settings.get("table_num", on_table_table),
            "starts_with_pour": settings.get("starts_with_pour", False),
        })
    
    return {"jobs": jobs}


@app.post("/api/jobs/settings")
async def update_job_settings(settings: list[JobSetting]):
    """Update job settings (batch)."""
    global user_job_settings
    
    for setting in settings:
        if setting.on_table_today or setting.expedite:
            # Parse on_table_today format (e.g., "RED_1" -> cell_color="RED", table_num=1)
            cell_color = None
            table_num = None
            if setting.on_table_today and "_" in setting.on_table_today:
                parts = setting.on_table_today.rsplit("_", 1)
                cell_color = parts[0]
                table_num = int(parts[1])
            
            user_job_settings[setting.job_id] = {
                "on_table_today": bool(setting.on_table_today),
                "cell_color": cell_color,
                "table_num": table_num,
                "starts_with_pour": setting.starts_with_pour,
                "expedite": setting.expedite,
                "qty_remaining": setting.qty_remaining,
            }
        else:
            user_job_settings.pop(setting.job_id, None)
    
    return {"success": True}


@app.post("/api/job-settings")
async def update_single_job_setting(setting: SingleJobSetting):
    """Update settings for a single job."""
    global user_job_settings
    
    if setting.on_table_today or setting.expedite:
        # Parse on_table_today format (e.g., "RED_1" -> cell_color="RED", table_num=1)
        cell_color = None
        table_num = None
        if setting.on_table_today and "_" in setting.on_table_today:
            parts = setting.on_table_today.rsplit("_", 1)
            cell_color = parts[0]
            table_num = int(parts[1])
        
        user_job_settings[setting.job_id] = {
            "on_table_today": bool(setting.on_table_today),
            "cell_color": cell_color,
            "table_num": table_num,
            "starts_with_pour": bool(setting.on_table_today),  # If on table, starts with pour
            "expedite": setting.expedite,
            "qty_remaining": setting.qty_remaining,
        }
    else:
        user_job_settings.pop(setting.job_id, None)
    
    return {"success": True}


# ============ SCHEDULING ENDPOINTS ============

@app.post("/api/schedule")
async def run_schedule(request: ScheduleRequest):
    """Run the scheduling algorithm."""
    global last_schedule_result, last_schedule_method, last_schedule_variant, production_load
    global all_schedule_results, best_method_key
    
    if not constants:
        raise HTTPException(status_code=500, detail="Constants not loaded")
    
    if not production_load:
        raise HTTPException(status_code=400, detail="No production load uploaded")
    
    try:
        schedule_date = datetime.strptime(request.schedule_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    
    active_cells = set()
    for cell in request.active_cells:
        cell = cell.upper()
        if cell in CELL_COLORS:
            active_cells.add(cell)
    
    if not active_cells:
        raise HTTPException(status_code=400, detail="No valid cells selected")
    
    # Apply user job settings
    modified_jobs = []
    for job in production_load.jobs:
        settings = user_job_settings.get(job.job_id, {})
        
        # Handle ON_TABLE_TODAY
        on_table_today = job.on_table_today
        if settings.get("on_table_today"):
            cell = settings.get("cell_color")
            table = settings.get("table_num")
            if cell and table:
                on_table_today = f"{cell}_{table}"
        elif settings.get("on_table_today") == False:
            on_table_today = None
        
        # Handle EXPEDITE
        expedite = job.expedite
        if settings.get("expedite"):
            expedite = True
        
        # Handle JOB_QUANTITY_REMAINING
        job_quantity_remaining = job.job_quantity_remaining
        if settings.get("qty_remaining") is not None:
            job_quantity_remaining = settings.get("qty_remaining")
        
        modified_job = Job(
            job_id=job.job_id,
            description=job.description,
            req_by=job.req_by,
            prod_qty=job.prod_qty,
            pattern=job.pattern,
            opening_size=job.opening_size,
            wire_diameter=job.wire_diameter,
            molds=job.molds,
            mold_type=job.mold_type,
            equivalent=job.equivalent,
            orange_eligible=job.orange_eligible,
            on_table_today=on_table_today,
            job_quantity_remaining=job_quantity_remaining,
            expedite=expedite,
            row_number=job.row_number,
        )
        modified_jobs.append(modified_job)
    
    modified_load = DailyProductionLoad(jobs=modified_jobs)
    
    inputs = OperatorInputs(
        active_cells=active_cells,
        shift_type=request.shift_type,
        summer_mode=request.summer_mode,
        schedule_date=schedule_date
    )
    
    # Always run all methods and variants
    methods = list(SchedulingMethod)
    variants = list(SchedulingVariant)
    
    # Run scheduling - store ALL results
    all_schedule_results.clear()
    evaluations = []
    
    for method in methods:
        for variant in variants:
            try:
                result = run_method(method, variant, modified_load, constants, inputs)
                key = f"{method.name}_{variant.name}"
                all_schedule_results[key] = {
                    "result": result,
                    "method": method,
                    "variant": variant,
                    "eval": evaluate_result(result, method, variant)
                }
                evaluations.append((method, variant, all_schedule_results[key]["eval"], result))
            except Exception as e:
                print(f"Error: {method.name} {variant.name}: {e}")
    
    if not evaluations:
        return {"success": False, "message": "All methods failed"}
    
    best = max(evaluations, key=lambda x: x[2].total_panels)
    best_method, best_variant, best_eval, best_result = best
    
    best_method_key = f"{best_method.name}_{best_variant.name}"
    last_schedule_result = best_result
    last_schedule_method = best_method
    last_schedule_variant = best_variant
    
    # Build response with current best
    response_data = build_schedule_response(best_result, best_method, best_variant, best_eval, evaluations)
    
    return response_data


def build_schedule_response(result, method, variant, eval_result, all_evaluations):
    """Build the schedule response data."""
    cell_breakdown = {}
    for cell_color, cr in result.cell_results.items():
        cell_breakdown[cell_color] = {
            "panels": cr.total_panels,
            "status": cr.status,
            "table1_panels": len(cr.table1_panels),
            "table2_panels": len(cr.table2_panels),
        }
    
    job_assignments = []
    for a in result.job_assignments:
        job_assignments.append({
            "job_id": a.job.job_id,
            "cell": a.cell_color,
            "table": a.table_num,
            "panels": a.panels_to_schedule,
            "priority": a.calc.priority,
            "sched_class": a.calc.sched_class,
            "is_on_table_today": a.is_on_table_today,
        })
    
    unscheduled_jobs = []
    for item in result.unscheduled_jobs:
        job = item[0]
        calc = item[1] if len(item) > 2 else None
        reason = item[-1]
        
        unsched_entry = {
            "job_id": job.job_id,
            "reason": reason,
            "req_by": str(job.req_by) if job.req_by else None,
        }
        
        if calc:
            unsched_entry["build_date"] = str(calc.build_date) if calc.build_date else None
            unsched_entry["priority"] = calc.priority
            unsched_entry["sched_class"] = calc.sched_class
            unsched_entry["is_late"] = calc.priority <= 1  # Priority 0 or 1 = late
        
        unscheduled_jobs.append(unsched_entry)
    
    gantt_data = build_gantt_data(result)
    
    ranked = rank_methods([e[2] for e in all_evaluations])
    method_rankings = [
        {"name": eval.full_name, "score": round(score, 3), "panels": eval.total_panels, "status": eval.status}
        for eval, score in ranked
    ]
    
    comparison_data = [
        {
            "method": m.name,
            "variant": v.name,
            "key": f"{m.name}_{v.name}",
            "panels": e.total_panels,
            "jobs_scheduled": e.total_jobs_scheduled,
            "table_idle": e.efficiency.forced_table_idle,
            "operator_idle": e.efficiency.forced_operator_idle,
            "status": e.status,
        }
        for m, v, e, r in all_evaluations
    ]
    
    # Build method buttons data
    method_buttons = []
    for m, v, e, r in all_evaluations:
        key = f"{m.name}_{v.name}"
        method_buttons.append({
            "key": key,
            "method": m.name,
            "variant": v.name,
            "label": f"{m.name.replace('_', ' ')} ({v.name.replace('_', ' ')})",
            "panels": e.total_panels,
            "is_best": key == f"{method.name}_{variant.name}",
            "status": e.status,
        })
    
    return {
        "success": True,
        "message": f"Best: {method.name} ({variant.name})",
        "best_method": method.name,
        "best_variant": variant.name,
        "current_method": method.name,
        "current_variant": variant.name,
        "total_panels": result.total_panels,
        "jobs_scheduled": len(result.job_assignments),
        "jobs_unscheduled": len(result.unscheduled_jobs),
        "cell_breakdown": cell_breakdown,
        "job_assignments": job_assignments,
        "unscheduled_jobs": unscheduled_jobs,
        "gantt_data": gantt_data,
        "method_rankings": method_rankings,
        "comparison_data": comparison_data,
        "method_buttons": method_buttons,
    }


def build_gantt_data(result):
    """Build Gantt chart data."""
    gantt = {"shift_minutes": result.shift_minutes, "cells": {}}
    
    task_colors = {
        "SETUP": "#FF6B6B",
        "LAYOUT": "#4ECDC4",
        "POUR": "#45B7D1",
        "CURE": "#96CEB4",
        "UNLOAD": "#FFEAA7"
    }
    
    for cell_color, cr in result.cell_results.items():
        cell_data = {"tables": {}, "total_panels": cr.total_panels}
        
        for table_name, panels in [("1", cr.table1_panels), ("2", cr.table2_panels)]:
            table_id = f"{cell_color}_{table_name}"
            tasks = []
            
            for panel in panels:
                for task_name, task in panel.tasks.items():
                    if task.duration > 0:
                        tasks.append({
                            "task": task_name,
                            "start": task.start_time,
                            "end": task.end_time,
                            "duration": task.duration,
                            "color": task_colors.get(task_name, "#999"),
                            "job_id": panel.job_id,
                            "panel": panel.panel_index,
                        })
            
            cell_data["tables"][table_id] = sorted(tasks, key=lambda x: x["start"])
        
        gantt["cells"][cell_color] = cell_data
    
    return gantt


@app.get("/api/method/{method_key}")
async def get_method_result(method_key: str):
    """Get schedule result for a specific method/variant combination."""
    global last_schedule_result, last_schedule_method, last_schedule_variant
    
    if method_key not in all_schedule_results:
        raise HTTPException(status_code=404, detail=f"No results for {method_key}")
    
    stored = all_schedule_results[method_key]
    result = stored["result"]
    method = stored["method"]
    variant = stored["variant"]
    eval_result = stored["eval"]
    
    # Update current selection
    last_schedule_result = result
    last_schedule_method = method
    last_schedule_variant = variant
    
    # Build all evaluations for comparison data
    all_evaluations = [
        (s["method"], s["variant"], s["eval"], s["result"])
        for s in all_schedule_results.values()
    ]
    
    return build_schedule_response(result, method, variant, eval_result, all_evaluations)


# ============ DOWNLOAD ENDPOINTS ============

@app.get("/api/download/html")
async def download_html():
    if not last_schedule_result:
        raise HTTPException(status_code=400, detail="No schedule to download")
    
    import tempfile
    html = generate_html_gantt(last_schedule_result, f"Schedule - {last_schedule_result.schedule_date}")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        return FileResponse(f.name, media_type='text/html', filename=f'schedule_{last_schedule_result.schedule_date}_gantt.html')


@app.get("/api/download/report")
async def download_report():
    """Download summary report as PDF."""
    if not last_schedule_result:
        raise HTTPException(status_code=400, detail="No schedule to download")
    
    import tempfile
    from src.output_generator import generate_summary_pdf
    
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        output_path = f.name
    
    try:
        method_name = last_schedule_method.name if last_schedule_method else "UNKNOWN"
        variant_name = last_schedule_variant.name if last_schedule_variant else "UNKNOWN"
        generate_summary_pdf(last_schedule_result, method_name, variant_name, output_path)
        return FileResponse(
            output_path, 
            media_type='application/pdf', 
            filename=f'schedule_{last_schedule_result.schedule_date}_report.pdf'
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")


@app.get("/api/download/cell/{cell_color}/pdf")
async def download_cell_pdf(cell_color: str):
    """Download PDF report for a specific cell."""
    if not last_schedule_result:
        raise HTTPException(status_code=400, detail="No schedule to download")
    
    cell_color = cell_color.upper()
    if cell_color not in last_schedule_result.cell_results:
        raise HTTPException(status_code=404, detail=f"Cell {cell_color} not in schedule")
    
    import tempfile
    from src.output_generator import generate_cell_pdf
    
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        output_path = f.name
    
    try:
        generate_cell_pdf(last_schedule_result, cell_color, output_path)
        return FileResponse(
            output_path, 
            media_type='application/pdf', 
            filename=f'{cell_color}_schedule_{last_schedule_result.schedule_date}.pdf'
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")


@app.get("/api/download/cell/{cell_color}/html")
async def download_cell_html(cell_color: str):
    """Download HTML report for a specific cell."""
    if not last_schedule_result:
        raise HTTPException(status_code=400, detail="No schedule to download")
    
    cell_color = cell_color.upper()
    if cell_color not in last_schedule_result.cell_results:
        raise HTTPException(status_code=404, detail=f"Cell {cell_color} not in schedule")
    
    import tempfile
    from src.output_generator import generate_cell_html_report
    
    html = generate_cell_html_report(last_schedule_result, cell_color)
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        return FileResponse(
            f.name, 
            media_type='text/html', 
            filename=f'{cell_color}_schedule_{last_schedule_result.schedule_date}.html'
        )


@app.get("/api/scheduled-cells")
async def get_scheduled_cells():
    """Get list of cells that were scheduled."""
    if not last_schedule_result:
        return {"cells": []}
    
    cells = []
    for cell_color, cr in last_schedule_result.cell_results.items():
        cells.append({
            "color": cell_color,
            "total_panels": cr.total_panels,
            "table1_panels": len(cr.table1_panels),
            "table2_panels": len(cr.table2_panels),
        })
    
    return {"cells": cells}


@app.get("/api/download/debug-excel")
async def download_debug_excel():
    """Download debugging Excel file with all job data and schedule assignments."""
    global last_schedule_result, last_schedule_method, last_schedule_variant, production_load
    
    if not last_schedule_result:
        raise HTTPException(status_code=400, detail="No schedule to download")
    
    if not production_load:
        raise HTTPException(status_code=400, detail="No production load")
    
    import tempfile
    from src.output_generator import generate_debug_excel
    from src.calculated_fields import calculate_fields_for_job
    
    # Calculate fields for all jobs
    job_calcs = {}
    for job in production_load.jobs:
        try:
            calc = calculate_fields_for_job(job, constants, last_schedule_result.schedule_date)
            job_calcs[job.job_id] = calc
        except:
            pass
    
    # Generate Excel
    try:
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
            output_path = f.name
        
        method_name = last_schedule_method.name if last_schedule_method else "UNKNOWN"
        variant_name = last_schedule_variant.name if last_schedule_variant else "UNKNOWN"
        
        generate_debug_excel(
            result=last_schedule_result,
            job_calcs=job_calcs,
            output_path=output_path,
            method_name=method_name,
            variant_name=variant_name
        )
        
        filename = f"schedule_debug_{last_schedule_result.schedule_date}.xlsx"
        return FileResponse(output_path, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', filename=filename)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Excel generation failed: {str(e)}")


# Mount static files
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
