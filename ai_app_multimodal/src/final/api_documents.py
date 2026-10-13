"""文書の入口：POST /api/documents・…/ask・…/import-recipes と GET・GET events・DELETE /api/jobs/{id}。

- 登録・ask・取り込みジョブはセッション6のまま。文書の置き場所だけを台帳（PersonalStore・30日）に替えた
- ask にはセッション14の応答キャッシュを足した（キーの preprocess に「送ったページ」を入れる）
- 取り込みジョブの使ったトークンを利用量に記録する（失敗・取り消しで終わっても、それまでの分を残す）
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Annotated

import anthropic
import anyio
from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, Field, ValidationError
from ulid import ULID

from kondate.jobs import Job, JobQueue
from kondate.llm import ChatRequest, Usage
from kondate.settings import get_settings
from kondate.sse import event
from src.final.cache import cache_key
from src.final.documents import cached, check_citation, pdf_block
from src.final.importer import import_recipes, import_total
from src.final.intake import MSG_TOO_LARGE, Rejected, inspect_pdf
from src.final.models import ANSWER_SCHEMA, Citation, DocumentAnswer
from src.final.pages import ASK_MAX_PAGES, Heading, build_index, guess_pages, select_pages
from src.final.privacy import PersonalStore
from src.final.web import Llm, UserId, error, record_llm, tokens4, total

settings = get_settings()
log = logging.getLogger(__name__)
router = APIRouter()

SYSTEM_PROMPT = (
    "添付の文書だけを根拠に答えてください。"
    "根拠にした文は文書から一字一句そのまま写し、ページ番号（1始まり）と一緒に引用として示してください。"
)
MAX_ATTEMPTS = 2
SELECTION_CACHE_SIZE = 8
MSG_NOT_FOUND = "文書が見つかりません"
MSG_UPSTREAM = "文書の読み取りに失敗しました。時間をおいて試してください"
MSG_UNGROUNDED = "回答の根拠を文書の中で確かめられませんでした"
MSG_PAGES_COUNT = f"pages は 1〜{ASK_MAX_PAGES} 個で指定してください"
MSG_PAGES_REQUIRED = "読むページを決められませんでした。pages でページ番号を指定してください"
MSG_JOB_NOT_FOUND = "ジョブが見つかりません"
ZERO_ASK_USAGE = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    pages: list[int] | None = None


class JobNotFound(Exception):
    pass


@dataclass
class StoredDocument:
    document_id: str
    sha256: str
    pages: int
    data: bytes = field(repr=False)
    page_texts: list[str] = field(repr=False)
    index: list[Heading] = field(repr=False)
    selections: dict[tuple[int, ...], bytes] = field(default_factory=dict, repr=False)

    def view(self) -> dict:
        return {"document_id": self.document_id, "pages": self.pages, "sha256": self.sha256}


def find_document(store: PersonalStore, user_id: str, sha256: str) -> StoredDocument | None:
    return next((h.data for h in store.live(user_id, "document") if h.data.sha256 == sha256), None)


def get_document(store: PersonalStore, user_id: str, document_id: str) -> StoredDocument | None:
    """自分の・期限内の文書だけ。他人の文書も、期限切れも、無いものも同じ None（存在を教えない）。"""
    held = store.get(user_id, document_id)
    return held.data if held is not None and held.kind == "document" else None


# ---------------------------------------------------------------- 登録（セッション5・6）

@router.post("/api/documents")
async def create_document(request: Request, file: UploadFile, x_user_id: UserId = "u001") -> JSONResponse:
    raw = await file.read(settings.upload_max_bytes + 1)
    if len(raw) > settings.upload_max_bytes:
        return error(request, 413, "too_large", MSG_TOO_LARGE)
    store: PersonalStore = request.app.state.data
    sha256 = hashlib.sha256(raw).hexdigest()
    if (doc := find_document(store, x_user_id, sha256)) is not None:
        return JSONResponse(doc.view(), status_code=200)
    try:
        pages, texts = await anyio.to_thread.run_sync(inspect_pdf, raw)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    if (doc := find_document(store, x_user_id, sha256)) is not None:   # 調べている間に同じ文書が登録された
        return JSONResponse(doc.view(), status_code=200)
    doc = StoredDocument(f"doc_{ULID()}", sha256, pages, raw, texts, build_index(texts))
    store.add("document", doc.document_id, x_user_id, data=doc)
    log.info("document_saved", extra={"fields": {"user_id": x_user_id, "document_id": doc.document_id,
                                                 "pages": pages, "bytes": len(raw)}})
    return JSONResponse(doc.view(), status_code=201)


# ---------------------------------------------------------------- ask（セッション6＋14）

def choose_pages(doc: StoredDocument, body: AskIn) -> list[int]:
    if body.pages is not None:
        pages = sorted(set(body.pages))
        if not 1 <= len(pages) <= ASK_MAX_PAGES:
            raise Rejected(422, "invalid_request", MSG_PAGES_COUNT)
        if pages[0] < 1 or pages[-1] > doc.pages:
            raise Rejected(422, "invalid_request", f"pages は 1〜{doc.pages} の範囲で指定してください")
        return pages
    if doc.pages <= ASK_MAX_PAGES:
        return list(range(1, doc.pages + 1))
    pages = guess_pages(doc.index, body.question)
    if not 1 <= len(pages) <= ASK_MAX_PAGES:
        raise Rejected(422, "invalid_request", MSG_PAGES_REQUIRED)
    return pages


async def selected_pdf(doc: StoredDocument, pages: list[int]) -> bytes:
    if pages == list(range(1, doc.pages + 1)):
        return doc.data
    key = tuple(pages)
    if key not in doc.selections:
        doc.selections[key] = await anyio.to_thread.run_sync(select_pages, doc.data, pages)
        while len(doc.selections) > SELECTION_CACHE_SIZE:
            del doc.selections[next(iter(doc.selections))]
    return doc.selections[key]


def grounded_answer(text: str, page_texts: list[str], sent: list[int]) -> DocumentAnswer | None:
    try:
        answer = DocumentAnswer.model_validate_json(text)
    except ValidationError:
        return None
    if not answer.citations:
        return None
    citations = []
    for c in answer.citations:
        if not 1 <= c.page <= len(sent):
            return None
        original = sent[c.page - 1]
        if not check_citation(page_texts, original, c.quote).ok:
            return None
        citations.append(Citation(page=original, quote=c.quote))
    return DocumentAnswer(answer=answer.answer, citations=citations)


@router.post("/api/documents/{document_id}/ask")
async def ask_document(request: Request, document_id: str, body: AskIn, llm: Llm,
                       x_user_id: UserId = "u001") -> JSONResponse:
    s = request.app.state
    doc = get_document(s.data, x_user_id, document_id)
    if doc is None:
        return error(request, 404, "not_found", MSG_NOT_FOUND)
    try:
        sent = choose_pages(doc, body)
    except Rejected as e:
        return error(request, e.status, e.type, e.message)
    key = cache_key(scope=x_user_id, kind="document_ask", content_sha256=doc.sha256, preprocess={"pages": sent},
                    prompt=body.question, system=SYSTEM_PROMPT, model=settings.llm_model, schema=ANSWER_SCHEMA)
    if (hit := s.cache.get(key)) is not None:
        s.usage.count_lookup(x_user_id, hit=True)
        return JSONResponse({**hit.value, "usage": ZERO_ASK_USAGE}, headers={"x-cache": "hit"})
    s.usage.count_lookup(x_user_id, hit=False)

    data = await selected_pdf(doc, sent)
    req = ChatRequest(
        messages=[{"role": "user", "content": [cached(pdf_block(data)), {"type": "text", "text": body.question}]}],
        system=SYSTEM_PROMPT, output_schema=ANSWER_SCHEMA, max_tokens=settings.llm_max_tokens,
    )
    used: list[Usage] = []
    answer = None
    try:
        for _ in range(MAX_ATTEMPTS):
            result = await llm.complete(req)
            used.append(result.usage)
            if (answer := grounded_answer(result.text, doc.page_texts, sent)) is not None:
                break
    except anthropic.APIError:
        return error(request, 503, "upstream_unavailable", MSG_UPSTREAM)
    finally:
        record_llm(request, x_user_id, used)
    if answer is None:
        return error(request, 502, "invalid_output", MSG_UNGROUNDED)

    value = {"answer": answer.answer, "citations": [c.model_dump() for c in answer.citations]}
    s.cache.put(key, x_user_id, value, total(used))
    return JSONResponse({**value, "usage": tokens4(total(used))}, headers={"x-cache": "miss"})


# ---------------------------------------------------------------- 取り込みジョブ（セッション6）

@router.post("/api/documents/{document_id}/import-recipes", status_code=202)
async def start_import(request: Request, document_id: str, llm: Llm, x_user_id: UserId = "u001") -> JSONResponse:
    s = request.app.state
    doc = get_document(s.data, x_user_id, document_id)
    if doc is None:
        return error(request, 404, "not_found", MSG_NOT_FOUND)
    request_id = request.state.request_id

    async def work(progress) -> dict:
        used: list[Usage] = []
        try:
            result = await import_recipes(llm, doc.data, doc.pages, progress, used)
        finally:
            if used:                       # 最終：失敗・取り消しでも、それまでに使った分を記録する
                s.usage.add_llm(x_user_id, settings.llm_model, total(used), request_id)
        return {"document_id": doc.document_id, **result}

    job = s.jobs.submit(work, total=import_total(doc.pages))
    s.job_owners[job.id] = x_user_id
    return JSONResponse({"job_id": job.id}, status_code=202)


async def owned_job(request: Request, job_id: str, x_user_id: UserId = "u001") -> Job:
    job = request.app.state.jobs.get(job_id)
    if job is None or request.app.state.job_owners.get(job_id) != x_user_id:
        raise JobNotFound()
    return job


OwnedJob = Annotated[Job, Depends(owned_job)]


@router.get("/api/jobs/{job_id}")
async def get_job(job: OwnedJob) -> dict:
    return {**job.snapshot(), "result": job.result}


@router.get("/api/jobs/{job_id}/events", response_class=EventSourceResponse)
async def job_events(request: Request, job: OwnedJob) -> AsyncIterator[ServerSentEvent]:
    async for snap in request.app.state.jobs.events(job.id):
        yield event("progress", snap)
    if job.status == "succeeded":
        yield event("done", {"result": job.result})
    elif job.status == "failed":
        yield event("error", {"type": "upstream_unavailable", "message": MSG_UPSTREAM,
                              "request_id": request.state.request_id})


@router.delete("/api/jobs/{job_id}")
async def cancel_job(request: Request, job: OwnedJob) -> dict:
    queue: JobQueue = request.app.state.jobs
    if queue.cancel(job.id):
        async for _ in queue.events(job.id):
            pass
    return job.snapshot()


async def forget_jobs(state, user_id: str) -> None:
    """最終：DELETE /api/me/data から呼ぶ。その利用者のジョブを止め、結果を捨て、以後は 404 にする。"""
    queue: JobQueue = state.jobs
    for job_id in [j for j, owner in state.job_owners.items() if owner == user_id]:
        if queue.cancel(job_id):
            async for _ in queue.events(job_id):   # 取り消しが終わる（利用量の記録も済む）まで待つ
                pass
        job = queue.get(job_id)
        if job is not None:
            job.result = None
        del state.job_owners[job_id]
