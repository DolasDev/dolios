"""Hermes agent harness.

Stub: a single persona with no tools yet. Exposes /health and /chat.
Tools and persona-from-YAML loading land once the Pegasus client exists.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from hermes.config import Settings, get_settings


log = logging.getLogger("hermes")


HERMES_SYSTEM_PROMPT = """\
You are Hermes, an AI assistant who acts as a power user inside Pegasus,
a move-and-storage management platform. You answer crisply, prefer concrete
steps over hedging, and confirm before taking destructive actions. Tools to
operate Pegasus on the user's behalf will be added in a later milestone —
until then, walk through what you would do and ask for any details you need.
"""


def build_agent(settings: Settings | None = None) -> Agent:
    s = settings or get_settings()
    provider = OpenAIProvider(base_url=s.openai_base_url, api_key=s.openai_api_key)
    model = OpenAIModel(s.model_name, provider=provider)
    return Agent(model=model, system_prompt=HERMES_SYSTEM_PROMPT)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    logging.basicConfig(level=s.log_level.upper())
    app.state.agent = build_agent(s)
    log.info("hermes ready: model=%s base=%s", s.model_name, s.openai_base_url)
    yield


app = FastAPI(title="hermes", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    agent: Agent = app.state.agent
    result = await agent.run(req.message)
    return ChatResponse(reply=result.output)
