"""FDE 演示 API：企业文档问答"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.rag import document_qa

router = APIRouter(prefix="/api/docqa", tags=["docqa"])


class IngestRequest(BaseModel):
    name: str
    content: str


class AskRequest(BaseModel):
    question: str
    top_k: int = 4


@router.get("/documents")
def documents():
    """已入库文档清单"""
    return {"documents": document_qa.list_documents()}


@router.post("/ingest")
def ingest(req: IngestRequest):
    """导入文档（md/txt 文本）并向量化入库"""
    return document_qa.ingest_document(req.name, req.content)


@router.post("/ask")
def ask(req: AskRequest):
    """文档问答（带引用）"""
    return document_qa.ask(req.question, top_k=max(1, min(req.top_k, 8)))
