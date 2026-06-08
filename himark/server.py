from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from himark import parser
from himark.engine import execute, find
from himark.models.exceptions import CompileError

api = FastAPI(title="himark", description="HMK pattern matching API")


class Request(BaseModel):
    pattern: str
    target: str


class ExecuteResponse(BaseModel):
    results: list[str]


class FindMatch(BaseModel):
    start: int
    end: int


class FindResponse(BaseModel):
    matches: list[FindMatch]



@api.post("/execute", response_model=ExecuteResponse)
def execute_route(req: Request) -> ExecuteResponse | JSONResponse:
    try:
        trees = parser.parse(req.pattern)
        results = execute(trees, req.target)
    except CompileError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return ExecuteResponse(results=results)


@api.post("/find", response_model=FindResponse)
def find_route(req: Request) -> FindResponse | JSONResponse:
    try:
        trees = parser.parse(req.pattern)
        spans = find(trees, req.target)
    except CompileError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return FindResponse(matches=[FindMatch(start=s, end=e) for s, e in spans])
