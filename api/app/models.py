from pydantic import BaseModel


class TaskResponse(BaseModel):
    task_id: str
    status: str


class TaskStatus(BaseModel):
    task_id: str
    status: str
    progress: int = 0
    filename: str = ""
    error: str = ""
    result: dict | None = None


class Segment(BaseModel):
    start: float
    end: float
    text: str
