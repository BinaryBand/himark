from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from marky import parser
from marky.engine import find
from marky.engine._match import find_matches
from marky.engine._render import render
from marky.models.exceptions import CompileError

api = FastAPI(title="marky", description="HMK pattern matching API")


class Request(BaseModel):
    pattern: str
    target: str


class Delta(BaseModel):
    start: int
    end: int
    text: str


class ExecuteResponse(BaseModel):
    deltas: list[Delta]


class FindMatch(BaseModel):
    start: int
    end: int


class FindResponse(BaseModel):
    matches: list[FindMatch]


@api.post("/execute", response_model=ExecuteResponse)
def execute_route(req: Request) -> ExecuteResponse | JSONResponse:
    try:
        trees = parser.parse(req.pattern)
    except CompileError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    if len(trees) < 2:
        # No template — return empty deltas (no substitutions)
        return ExecuteResponse(deltas=[])

    try:
        matches = find_matches(trees[0], req.target)
        deltas = [
            Delta(start=m.start, end=m.end, text=render(trees[-1], m)) for m in matches
        ]
    except CompileError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    return ExecuteResponse(deltas=deltas)


@api.post("/find", response_model=FindResponse)
def find_route(req: Request) -> FindResponse | JSONResponse:
    try:
        trees = parser.parse(req.pattern)
        spans = find(trees, req.target)
    except CompileError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return FindResponse(matches=[FindMatch(start=s, end=e) for s, e in spans])
