from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from himark import parser
from himark.engine import execute
from himark.models.exceptions import CompileError

api = FastAPI(title="himark", description="HMK pattern matching API")


class RunRequest(BaseModel):
    pattern: str
    target: str


class RunResponse(BaseModel):
    results: list[str]


@api.post("/run", response_model=RunResponse)
def run(req: RunRequest) -> RunResponse:
    try:
        trees = parser.parse(req.pattern)
        results = execute(trees, req.target)
    except CompileError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return RunResponse(results=results)
