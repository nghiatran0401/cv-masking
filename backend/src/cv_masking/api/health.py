from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from cv_masking import __version__

router = APIRouter(prefix="/api")


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"]
    version: str


@router.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
