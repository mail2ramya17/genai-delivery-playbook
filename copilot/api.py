"""FastAPI front door.

Identity: in production the API sits behind APIM / an ALB that validates the Entra ID
(or Cognito / IAM Identity Center) JWT; the group claims become `User.groups`.
For local demos, `X-Demo-User` and `X-Demo-Groups` headers stand in for that token
and are rejected unless DEMO_AUTH=1.
"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import __version__
from .answer import SupportCopilot, User

app = FastAPI(title="Secure RAG Support Copilot", version=__version__)
copilot = SupportCopilot.from_directory(audit_path=os.environ.get("AUDIT_LOG", "logs/audit.jsonl"))


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def current_user(x_demo_user: str = Header(None), x_demo_groups: str = Header("")) -> User:
    if os.environ.get("DEMO_AUTH") != "1":
        raise HTTPException(401, "Configure JWT validation (Entra ID / Cognito) or set DEMO_AUTH=1 locally")
    if not x_demo_user:
        raise HTTPException(401, "missing identity")
    return User(x_demo_user, {g.strip() for g in x_demo_groups.split(",") if g.strip()})


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok", "version": __version__, "prompt_version": copilot.prompt["version"]}


@app.post("/ask")
def ask(body: Ask, user: User = Depends(current_user)) -> dict:
    return copilot.answer(body.question, user).to_dict()
