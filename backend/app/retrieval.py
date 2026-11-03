import re
from sqlalchemy import select
from .models import Chunk, Document, Notebook
from .model_service import embedding_signature
from .config import settings
from .errors import fail


def is_overview(question):
    return bool(re.search(r'主要[讲说]|讲了什么|主要(内容|主题|观点)|核心观点|核心模块|知识点范畴|内容概[览述括]|概[览述括].{0,12}(资料|文档|内容)|总结.{0,12}(资料|文档|全文)|涵盖.{0,12}(主题|知识点)|覆盖.{0,12}(模块|知识点)|资料.{0,12}(相同|不同).{0,8}观点', question))


def spread_chunks(chunks, count):
    """Cover pages before adding detail; deterministic and bounded."""
    pages = {}
    for chunk in chunks:
        pages.setdefault((getattr(chunk, "location", None) or {}).get("block_id", chunk.page), chunk)
    first = list(pages.values())
    def sample(items, n):
        n = min(n, len(items))
        return [items[round(i * (len(items)-1) / max(1, n-1))] for i in range(n)]
    chosen = sample(first, count)
    ids = {c.id for c in chosen}
    chosen += sample([c for c in chunks if c.id not in ids], count-len(chosen))
    return chosen


def overview_sources(db, user_id, notebook_id, selected, limit=24):
    q = select(Document).join(Notebook).where(
        Notebook.user_id == user_id, Notebook.id == notebook_id,
        Notebook.deleted_at.is_(None), Document.deleted_at.is_(None),
        Document.status == 'ready', Document.embedding_model == embedding_signature())
    if selected is not None:
        q = q.where(Document.id.in_(selected))
    docs = list(db.scalars(q.order_by(Document.created_at, Document.id)))
    sources = []
    for index, doc in enumerate(docs):
        quota = limit // len(docs) + (index < limit % len(docs))
        chunks = list(db.scalars(select(Chunk).where(Chunk.document_id == doc.id, Chunk.version == doc.active_version).order_by(Chunk.page, Chunk.ordinal)))
        for c in spread_chunks(chunks, quota):
            from .source_references import evidence
            sources.append(dict(evidence(db, doc, c), label=len(sources)+1))
    return sources


def validate_sources(db, user_id, notebook_id, selected):
    if selected is None:
        return
    if (
        not selected
        or len(selected) > settings().max_files
        or len(set(selected)) != len(selected)
    ):
        fail(422, "invalid_sources", "请至少选择一份可用资料")
    ids = set(
        db.scalars(
            select(Document.id)
            .join(Notebook)
            .where(
                Notebook.user_id == user_id,
                Notebook.id == notebook_id,
                Notebook.deleted_at.is_(None),
                Document.deleted_at.is_(None),
                Document.status == "ready",
                Document.id.in_(selected),
            )
        )
    )
    if ids != set(selected):
        fail(404, "invalid_sources", "所选资料不存在或尚未处理完成")


def retrieve(db, user_id, notebook_id, selected, vector):
    distance = Chunk.embedding.cosine_distance(vector)
    q = (
        select(Chunk, Document, distance.label("distance"))
        .join(Document)
        .join(Notebook)
        .where(
            Notebook.user_id == user_id,
            Notebook.id == notebook_id,
            Notebook.deleted_at.is_(None),
            Document.deleted_at.is_(None),
            Document.status == "ready",
            Document.embedding_model == embedding_signature(),
            Chunk.version == Document.active_version,
        )
    )
    if selected is not None:
        q = q.where(Document.id.in_(selected))
    rows = db.execute(q.order_by(distance).limit(8)).all()
    from .source_references import evidence
    return [dict(evidence(db, doc, c), label=i+1) for i, (c, doc, dist) in enumerate(rows)
            if dist <= settings().retrieval_max_distance]
