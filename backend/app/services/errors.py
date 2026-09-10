from __future__ import annotations


def classify_exception(exc: Exception) -> tuple[str, str]:
    text = str(exc or "").lower()

    # HTTP authorization errors need context: a 401/403 from an LLM endpoint is
    # different from a video site refusing a download. Avoid telling users to
    # replace an API key when the source website is the one denying access.
    if ("401" in text or "403" in text or "unauthorized" in text) and (
        "chat/completions" in text or "api key" in text or "apikey" in text
    ):
        return "llm_auth", "AI 服务鉴权失败，请检查 API Key、模型和服务地址。"
    if "401" in text or "403" in text or "forbidden" in text:
        return "source_forbidden", "视频源拒绝访问，请确认链接可公开访问；如需登录，请配置平台 Cookie 后重试。"

    rules = [
        (("uploaded source file was not found",), "source_missing", "本地源文件已不存在，无法重新执行完整流程。"),
        (("audio extraction failed", "invalid data found when processing input"), "unsupported_media", "无法读取该媒体文件，请确认文件未损坏且格式受支持。"),
        (("private", "localhost", "loopback", "reserved address"), "unsafe_url", "该链接指向受限制的网络地址，无法处理。"),
        (("unsupported url", "no suitable extractor"), "unsupported_url", "暂不支持该视频链接，请确认链接来自受支持的平台。"),
        (("sign in", "login", "cookies", "not a bot", "authentication"), "login_required", "该视频需要登录后访问，请配置对应平台的 Cookie 后重试。"),
        (("duration", "configured limit"), "video_too_long", "视频时长超过系统限制，请使用更短的视频或调整服务器限制。"),
        (("download size", "size limit", "too large"), "video_too_large", "视频文件超过系统允许的大小，请使用较小的视频或调整服务器限制。"),
        (("disk", "no space left"), "disk_full", "服务器存储空间不足，请清理历史任务后重试。"),
        (("ffmpeg binary was not found", "ffprobe binary was not found"), "media_tool_missing", "媒体处理组件不可用，请检查服务器上的 FFmpeg/FFprobe。"),
        (("no speech", "speech was detected"), "no_speech", "没有检测到可识别的语音内容。"),
        (("out of memory", "cuda out of memory", "memory"), "asr_memory", "语音识别资源不足，请改用“均衡”或“快速”识别档位。"),
        (("429", "rate limit", "too many requests"), "llm_rate_limit", "AI 服务请求过于频繁，请稍后重试。"),
        (("empty final content", "empty content"), "llm_empty_response", "AI 服务返回了空结果，系统已自动重试仍未成功。请稍后重新生成摘要；如持续发生，可在设置中更换模型。"),
        (("invalid api key", "incorrect api key"), "llm_auth", "AI 服务鉴权失败，请检查 API Key、模型和服务地址。"),
        (("insufficient", "quota", "balance"), "llm_quota", "AI 服务额度或余额不足，请检查服务商账户。"),
        (("timeout", "timed out"), "network_timeout", "请求超时，请检查网络后重试。"),
        (("name or service not known", "connection", "network"), "network_error", "网络连接失败，请检查服务器网络后重试。"),
    ]
    for needles, code, message in rules:
        if any(needle in text for needle in needles):
            return code, message
    return "processing_error", "处理过程中发生错误，请稍后重试；如持续失败，请查看服务日志。"
