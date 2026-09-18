"""Timestamp-preserving video retrieval with a no-API-key lexical fallback.

Indexes have their own lifecycle. They never change a successful media Job into
an error. Evidence is scoped by an explicit, authorized job-id list, not by LLM
instructions. Saved answer evidence contains a source-version hash.
"""
from __future__ import annotations
import hashlib
import json
import logging
import math
import re
from collections import Counter
from pathlib import Path

from sqlalchemy import bindparam, delete, func, select, text
from app.core.config import get_settings
from app.db.assistant import VideoChunk, VideoKnowledgeIndex, now
from app.db.models import Job
from app.db.session import SessionLocal
from app.services.embeddings import embed_texts
from app.services.setting_store import get_llm_config

logger = logging.getLogger(__name__)


def result_for_job(job: Job) -> dict:
    if not job.output_dir:
        raise ValueError("视频尚未生成文字稿")
    root = Path(job.output_dir).resolve()
    allowed = (get_settings().data_dir / "jobs").resolve()
    path = (root / "result.json").resolve()
    if allowed not in root.parents or root not in path.parents or not path.is_file():
        raise ValueError("无可用的文字稿文件")
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Transcript JSON exceeds the 50 MiB safety limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid transcript format")
    return payload


def normalized_segments(payload: dict) -> list[dict]:
    values = payload.get("transcript", {}).get("segments", [])
    output = []
    for value in values:
        start, end = float(value["start"]), float(value["end"])
        if not math.isfinite(start + end) or start < 0 or end < start:
            raise ValueError("Invalid transcript timestamp")
        content = str(value.get("text", "")).strip()
        if content:
            output.append({"start": start, "end": end, "text": content})
    return sorted(output, key=lambda item: item["start"])


def transcript_hash(segments: list[dict]) -> str:
    value = json.dumps(segments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def timed_chunks(segments: list[dict], max_chars: int = 1400) -> list[dict]:
    if max_chars < 32:
        raise ValueError("Chunk budget too small")
    result, current, size = [], [], 0
    for segment in segments:
        # A long ASR segment keeps its true time range; no invented sub-timestamps.
        for offset in range(0, len(segment["text"]), max_chars):
            piece = {**segment, "text": segment["text"][offset:offset + max_chars]}
            if current and size + len(piece["text"]) + 1 > max_chars:
                result.append({"start": current[0]["start"], "end": max(x["end"] for x in current),
                               "text": "\n".join(x["text"] for x in current)})
                current, size = [], 0
            current.append(piece)
            size += len(piece["text"]) + 1
    if current:
        result.append({"start": current[0]["start"], "end": max(x["end"] for x in current),
                       "text": "\n".join(x["text"] for x in current)})
    return result


def ensure_lexical_index(job_id: str) -> str:
    with SessionLocal() as db:
        # Serializes rebuilds for the same video on PostgreSQL.
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if not job:
            raise ValueError("视频已删除")
        segments = normalized_segments(result_for_job(job))
        if not segments:
            raise ValueError("未找到可问答的语音内容")
        digest = transcript_hash(segments)
        index = db.get(VideoKnowledgeIndex, job_id)
        if index and index.transcript_hash == digest and index.status in {"lexical_ready", "vector_ready", "degraded", "indexing"}:
            return digest
        if index is None:
            index = VideoKnowledgeIndex(job_id=job_id)
            db.add(index)
        chunks = timed_chunks(segments)
        db.execute(delete(VideoChunk).where(VideoChunk.job_id == job_id))
        db.add_all([VideoChunk(job_id=job_id, ordinal=i, start_seconds=c["start"],
            end_seconds=c["end"], content=c["text"], embedding_model="") for i, c in enumerate(chunks)])
        index.transcript_hash = digest
        index.status = "lexical_ready"
        index.embedding_model = ""
        index.error_message = None
        index.chunk_count = len(chunks)
        index.updated_at = now()
        db.commit()
        return digest


def invalidate_index(db, job_id: str) -> None:
    index = db.get(VideoKnowledgeIndex, job_id)
    if index:
        index.status, index.transcript_hash = "stale", ""
        index.updated_at = now()
    db.execute(delete(VideoChunk).where(VideoChunk.job_id == job_id))


def index_video(job_id: str) -> None:
    digest = None
    try:
        digest = ensure_lexical_index(job_id)
        with SessionLocal() as db:
            config = get_llm_config(db)
            index = db.get(VideoKnowledgeIndex, job_id)
            if not config or not config.embedding_model or not index:
                return
            if index.status == "vector_ready" and index.embedding_model == config.embedding_model:
                return
            chunks = list(db.scalars(select(VideoChunk).where(VideoChunk.job_id == job_id).order_by(VideoChunk.ordinal)))
            inputs, ids = [c.content for c in chunks], [c.id for c in chunks]
        vectors = embed_texts(config, inputs)
        with SessionLocal() as db:
            index = db.scalar(select(VideoKnowledgeIndex).where(VideoKnowledgeIndex.job_id == job_id).with_for_update())
            if not index or index.transcript_hash != digest:
                return  # The user edited the transcript while embedding was in flight.
            for chunk_id, vector in zip(ids, vectors):
                chunk = db.get(VideoChunk, chunk_id)
                if chunk:
                    chunk.embedding = json.dumps(vector, separators=(",", ":"))
                    chunk.embedding_model = config.embedding_model
            index.status, index.embedding_model = "vector_ready", config.embedding_model
            index.error_message, index.updated_at = None, now()
            db.commit()
    except Exception:
        logger.exception("Video index failed for job=%s", job_id)
        with SessionLocal() as db:
            index = db.get(VideoKnowledgeIndex, job_id)
            if index and digest and index.transcript_hash == digest:
                index.status = "degraded"
                index.error_message = "向量索引不可用，已保留关键词检索；请检查 Embedding 配置"
                index.updated_at = now()
                db.commit()
            elif not digest and db.get(Job, job_id):
                if index is None:
                    index = VideoKnowledgeIndex(job_id=job_id)
                    db.add(index)
                index.status, index.error_message = "failed", "文字稿不可用，完成转写后可重试"
                index.updated_at = now()
                db.commit()


def terms(value: str) -> list[str]:
    value = value.lower()
    result = re.findall(r"[a-z0-9_]{2,}", value)
    for group in re.findall(r"[一-鿿]+", value):
        result.extend(group[i:i + 2] for i in range(max(0, len(group) - 1)))
        if len(group) == 1:
            result.append(group)
    return result


def lexical_ranking(question: str, chunks: list[VideoChunk]) -> list[tuple[VideoChunk, float]]:
    query = set(terms(question))
    counters = [Counter(terms(c.content)) for c in chunks]
    avg = sum(sum(c.values()) for c in counters) / max(1, len(counters)) or 1
    freq = Counter(t for c in counters for t in c if t in query)
    output = []
    for chunk, counts in zip(chunks, counters):
        length = sum(counts.values())
        score = 0.0
        for term in query:
            tf = counts.get(term, 0)
            if tf:
                idf = math.log(1 + (len(chunks) - freq[term] + 0.5) / (freq[term] + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / avg))
        output.append((chunk, score))
    return sorted(output, key=lambda pair: pair[1], reverse=True)


def requested_seconds(question: str) -> float | None:
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\d)", question)
    if match:
        a, b, c = match.groups()
        return int(a) * 3600 + int(b) * 60 + int(c) if c is not None else int(a) * 60 + int(b)
    match = re.search(r"(\d+)\s*分(?:钟)?(?:\s*(\d+)\s*秒)?", question)
    if match:
        return int(match[1]) * 60 + int(match[2] or 0)
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    denom = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denom if denom else 0.0


def retrieve(job_ids: list[str], question: str, broad: bool = False, limit: int = 12) -> dict:
    """Callers MUST authorize every job_id. There is no unscoped global query."""
    job_ids = list(dict.fromkeys(job_ids))[:get_settings().assistant_max_resources]
    warnings, hashes = [], {}
    for job_id in job_ids:
        try:
            hashes[job_id] = ensure_lexical_index(job_id)
        except (ValueError, OSError, KeyError, json.JSONDecodeError):
            warnings.append(f"{job_id}: 文字稿尚不可用")
    if not hashes:
        return {"evidence": [], "summaries": [], "warnings": warnings, "coverage": {"selected_chunks": 0, "total_chunks": 0}}
    with SessionLocal() as db:
        jobs = {j.id: j for j in db.scalars(select(Job).where(Job.id.in_(hashes)))}
        total_chunks = db.scalar(select(func.count()).select_from(VideoChunk).where(VideoChunk.job_id.in_(hashes)))
        chunks = list(db.scalars(select(VideoChunk).where(VideoChunk.job_id.in_(hashes)).order_by(VideoChunk.job_id, VideoChunk.ordinal).limit(20000)))
        config = get_llm_config(db)
        ranked = lexical_ranking(question, chunks)
        by_id = {c.id: c for c in chunks}
        fusion = {c.id: 1 / (60 + i) for i, (c, score) in enumerate(ranked, 1) if score > 0}
        if not broad and config and config.embedding_model and any(c.embedding_model == config.embedding_model and c.embedding for c in chunks):
            try:
                vector = embed_texts(config, [question])[0]
                if db.bind.dialect.name == "postgresql":
                    sql = text("""SELECT id FROM video_knowledge_chunks
                        WHERE job_id IN :job_ids AND embedding IS NOT NULL AND embedding_model=:model
                        ORDER BY CAST(embedding AS vector(1536)) <=> CAST(:query AS vector(1536)) LIMIT :limit""").bindparams(bindparam("job_ids", expanding=True))
                    vector_ids = list(db.scalars(sql, {"job_ids": list(hashes), "model": config.embedding_model,
                        "query": json.dumps(vector), "limit": limit * 3}))
                else:
                    vector_ids = [c.id for c in sorted((c for c in chunks if c.embedding and c.embedding_model == config.embedding_model),
                        key=lambda c: _cosine(vector, json.loads(c.embedding)), reverse=True)[:limit * 3]]
                for rank, chunk_id in enumerate(vector_ids, 1):
                    fusion[chunk_id] = fusion.get(chunk_id, 0) + 1 / (60 + rank)
            except Exception:
                logger.warning("Query embedding unavailable; using lexical retrieval", exc_info=True)
                warnings.append("本次使用关键词检索（向量服务不可用）")
        ordered = [by_id[k] for k in sorted(fusion, key=fusion.get, reverse=True) if k in by_id]
        second = requested_seconds(question)
        if second is not None:
            at_time = [c for c in chunks if c.start_seconds <= second <= c.end_seconds]
            if not at_time:
                at_time = sorted(chunks, key=lambda c: abs(c.start_seconds - second))[:1]
                warnings.append("该时间点没有精确字幕，仅提供邻近片段")
            ordered = at_time + [c for c in ordered if c not in at_time]
        if broad:
            # Round-robin across videos and chronological coverage. Never label
            # sampled excerpts as a full transcript read.
            groups = [[c for c in chunks if c.job_id == j] for j in hashes]
            quota = max(1, limit // max(1, len(groups)))
            ordered = []
            for group in groups:
                if group:
                    indices = sorted({round(i * (len(group)-1) / max(1, quota-1)) for i in range(min(quota, len(group)))})
                    ordered.extend(group[i] for i in indices)
        elif len(hashes) > 1:
            # Guarantee each source can contribute to multi-video questions.
            per_source = [next((c for c in ordered if c.job_id == job_id), None) for job_id in hashes]
            ordered = [c for c in per_source if c] + ordered
        if not ordered:
            warnings.append("未命中直接匹配；以开头片段作为背景，不应据此确认具体事实")
            ordered = chunks[:min(3, limit)]
        unique, seen, budget = [], set(), get_settings().assistant_max_context_chars
        for chunk in ordered:
            if chunk.id in seen or len(unique) >= limit or len(chunk.content) > budget:
                continue
            seen.add(chunk.id)
            unique.append(chunk)
            budget -= len(chunk.content)
        evidence = [{"id": f"V{i+1}", "job_id": c.job_id, "title": jobs[c.job_id].title or c.job_id,
            "start_seconds": c.start_seconds, "end_seconds": c.end_seconds, "excerpt": c.content,
            "transcript_hash": hashes[c.job_id]} for i, c in enumerate(unique)]
        summaries = []
        if broad:
            for job in jobs.values():
                try:
                    summary = result_for_job(job).get("summary")
                    if summary:
                        value = str(summary)[:max(0, min(5000, budget))]
                        summaries.append({"job_id": job.id, "title": job.title, "summary": value})
                        budget -= len(value)
                except (ValueError, OSError, json.JSONDecodeError):
                    pass
        if len(unique) < total_chunks:
            warnings.append(f"本次使用 {len(unique)} / {total_chunks} 个文字稿片段，并非完整逐字阅读")
        return {"evidence": evidence, "summaries": summaries, "warnings": warnings,
            "coverage": {"selected_chunks": len(unique), "total_chunks": total_chunks, "sampling": len(unique) < total_chunks}}
