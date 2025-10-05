from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class VoiceConfig(BaseModel):
    text: str
    voice: str


class GenerationRequest(BaseModel):
    task_name: str
    blocks: Dict[str, List[str]] = Field(default_factory=dict)

    class Config:
        extra = "allow"

    def __init__(self, **data):
        task_name = data.pop('task_name', 'default_task')

        blocks = {}
        for key, value in data.items():
            blocks[key] = value

        super().__init__(task_name=task_name, blocks=blocks, **data)

    def dict(self, *args, **kwargs):
        result = {'task_name': self.task_name}
        for key, value in self.blocks.items():
            result[key] = value
        return result


class TaskStatusResponse(BaseModel):
    task_id: str
    task_name: str
    status: str
    progress: float
    completed: int
    total: int
    results: List[str]
    created_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None


class GenerationResultResponse(BaseModel):
    task_id: str
    task_name: str
    total_variants: int
    successful: int
    failed: int
    files: List[dict[str, Any]]