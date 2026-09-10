from __future__ import annotations

from typing import Callable

from app.core.config import get_settings
from app.services.chunking import chunk_segments
from app.services.domain import TranscriptSegment
from app.services.llm import OpenAICompatibleLLM
from app.services.setting_store import LLMConfig
from app.services.text_normalizer import normalize_simplified_chinese

ProgressCallback = Callable[[int, str], None]

DEFAULT_SYSTEM = """You summarize video transcripts accurately. Preserve facts, names, numbers, and uncertainty. Do not invent information that is absent from the transcript. Produce structured Markdown."""

PRESET_INSTRUCTIONS = {
    "standard": "生成结构清晰的标准总结：概览、关键观点、重要细节、结论/行动项、重点时间点。",
    "detailed": "生成尽可能完整的详细笔记，保留论证过程、案例、数字、专有名词和重要时间点。",
    "course": "整理成课程学习笔记：学习目标、知识框架、核心概念、例子、易错点、复习清单和关键时间点。",
    "meeting": "整理成会议纪要：议题、关键讨论、结论、决策、待办事项、负责人/时间信息（仅在原文出现时记录）。",
    "interview": "整理成访谈记录：受访者主要观点、关键问答、立场变化、代表性案例和重点时间点。",
    "knowledge": "提取可复用知识点：定义、原则、方法、事实、数据、案例、关联关系和重点时间点。",
    "short_copy": "生成可直接使用的短视频文案：标题备选、三秒开场、核心口播、结尾行动引导；语言简洁有节奏，但不得虚构事实。",
    "custom": "按照用户提供的自定义要求整理内容。",
}


def _group_texts(items: list[str], max_chars: int) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    size = 0
    for item in items:
        item_size = len(item) + 8
        if current and size + item_size > max_chars:
            groups.append(current)
            current = []
            size = 0
        current.append(item)
        size += item_size
    if current:
        groups.append(current)
    return groups


def summarize_transcript(
    segments: list[TranscriptSegment],
    config: LLMConfig,
    output_language: str,
    summary_preset: str = "standard",
    summary_instruction: str | None = None,
    progress: ProgressCallback | None = None,
) -> str:
    settings = get_settings()
    chunks = chunk_segments(segments, settings.llm_max_chunk_chars)
    if not chunks:
        return "没有生成可用的语音文字稿。"

    system = config.custom_prompt or DEFAULT_SYSTEM
    preset = PRESET_INSTRUCTIONS.get(summary_preset, PRESET_INSTRUCTIONS["standard"])
    extra = summary_instruction.strip() if summary_instruction else ""
    task_instruction = preset + (f"\n额外要求：{extra}" if extra else "")

    partials: list[str] = []
    total = len(chunks)
    with OpenAICompatibleLLM(config) as client:
        for index, chunk in enumerate(chunks, start=1):
            prompt = (
                f"请使用 {output_language} 总结以下视频文字稿片段（{index}/{total}）。\n"
                f"总结要求：{task_instruction}\n"
                "必须忠于原文，不要补充原文没有的信息；保留有价值的时间戳。\n\n"
                f"文字稿：\n{chunk}"
            )
            partials.append(client.complete(system, prompt).content)
            if progress:
                progress(82 + int((index / total) * 8), "summarizing")

        if len(partials) == 1:
            return normalize_simplified_chinese(partials[0], output_language)

        level = 1
        current = partials
        reduce_limit = max(settings.llm_max_chunk_chars * 2, 24000)
        while len(current) > 1:
            groups = _group_texts(current, reduce_limit)
            next_level: list[str] = []
            for group_index, group in enumerate(groups, start=1):
                joined = "\n\n---\n\n".join(group)
                final_prompt = (
                    f"请把以下分块总结合并成一份准确、去重、结构化的 {output_language} 总结。\n"
                    f"总结要求：{task_instruction}\n"
                    "保留重要事实、数字、结论和时间点，不要添加原文不存在的信息。"
                    f"这是第 {level} 层归并，第 {group_index}/{len(groups)} 组。\n\n"
                    f"分块总结：\n{joined}"
                )
                next_level.append(client.complete(system, final_prompt).content)
            current = next_level
            level += 1
            if progress:
                progress(min(96, 91 + level), "synthesizing_summary")
        return normalize_simplified_chinese(current[0], output_language)
