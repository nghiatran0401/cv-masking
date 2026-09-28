from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from cv_masking.api.errors import ApiError
from cv_masking.api.security import SESSION_COOKIE, SessionState, apply_security_headers
from cv_masking.domain.codes import ErrorCode

router = APIRouter(prefix="/api")


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    csrf_token: str


@router.get("/session")
def open_session(request: Request) -> JSONResponse:
    session = getattr(request.app.state, "session", None)
    if not isinstance(session, SessionState):
        raise ApiError(ErrorCode.INTERNAL_ERROR, 500)
    cookie = request.cookies.get(SESSION_COOKIE)
    bootstrap = request.query_params.get("bootstrap")
    if not session.bootstrap.allow(bootstrap, cookie, session.session_token):
        raise ApiError(ErrorCode.SECURITY_TOKEN_INVALID, 403)
    response = JSONResponse(SessionResponse(csrf_token=session.csrf_token).model_dump())
    response.set_cookie(
        SESSION_COOKIE,
        session.session_token,
        max_age=86_400,
        path="/",
        httponly=True,
        samesite="strict",
        secure=False,
    )
    apply_security_headers(response.headers)
    return response
