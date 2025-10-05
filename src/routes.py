import uuid
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, HTTPException
from typing import Dict, Any

from .schemas import TaskStatusResponse, GenerationResultResponse
from .services.generator import VideoGenerator

router = APIRouter()

TASKS = {}
generator = None


def set_generator(gen: VideoGenerator):
    global generator
    generator = gen


async def update_progress(task_id: str, completed: int, total: int):
    if task_id in TASKS:
        TASKS[task_id]["completed"] = completed
        TASKS[task_id]["total"] = total
        TASKS[task_id]["progress"] = round((completed / total * 100) if total > 0 else 0, 2)


async def run_generation(task_id: str, config: dict):
    try:
        TASKS[task_id]["status"] = "processing"

        async def progress_callback(completed, total):
            await update_progress(task_id, completed, total)

        results = await generator.generate_all(task_id, config, progress_callback)

        if "error" in results:
            TASKS[task_id]["status"] = "failed"
            TASKS[task_id]["error"] = results["error"]
        else:
            TASKS[task_id]["status"] = "completed"
            TASKS[task_id]["results"] = results["successful"]
            TASKS[task_id]["failed_count"] = len(results["failed"])

        TASKS[task_id]["completed_at"] = datetime.now().isoformat()
    except Exception as e:
        TASKS[task_id]["status"] = "failed"
        TASKS[task_id]["error"] = str(e)


@router.post("/generate")
async def generate_videos(request: Dict[Any, Any], background_tasks: BackgroundTasks):
    if "task_name" not in request:
        raise HTTPException(status_code=400, detail="task_name is required")

    task_id = str(uuid.uuid4())

    TASKS[task_id] = {
        "task_name": request["task_name"],
        "status": "queued",
        "progress": 0.0,
        "completed": 0,
        "total": 0,
        "results": [],
        "failed_count": 0,
        "created_at": datetime.now().isoformat(),
        "completed_at": None,
        "error": None
    }

    background_tasks.add_task(run_generation, task_id, request)

    return {
        "task_id": task_id,
        "status": "queued",
        "message": "Generation started"
    }


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_status(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task not found")

    task = TASKS[task_id]
    return TaskStatusResponse(
        task_id=task_id,
        task_name=task["task_name"],
        status=task["status"],
        progress=task["progress"],
        completed=task["completed"],
        total=task["total"],
        results=task["results"],
        created_at=task["created_at"],
        completed_at=task.get("completed_at"),
        error=task.get("error")
    )


@router.get("/results/{task_id}", response_model=GenerationResultResponse)
async def get_results(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task not found")

    task = TASKS[task_id]
    if task["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Task not completed. Current status: {task['status']}"
        )

    successful = len(task["results"])
    failed = task.get("failed_count", 0)

    return GenerationResultResponse(
        task_id=task_id,
        task_name=task["task_name"],
        total_variants=successful + failed,
        successful=successful,
        failed=failed,
        files=[{"url": f} for f in task["results"]]
    )


@router.delete("/task/{task_id}")
async def delete_task(task_id: str):
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail="Task not found")

    del TASKS[task_id]
    return {"message": "Task deleted", "task_id": task_id}
