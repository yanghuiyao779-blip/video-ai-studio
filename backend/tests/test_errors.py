from app.services.errors import classify_exception


def test_error_classification_for_login_and_quota():
    code, message = classify_exception(RuntimeError("Sign in to confirm you're not a bot"))
    assert code == "login_required"
    assert "登录" in message

    code, message = classify_exception(RuntimeError("HTTP 429 too many requests"))
    assert code == "llm_rate_limit"
    assert "频繁" in message


def test_error_classification_for_local_media():
    code, _ = classify_exception(RuntimeError("Uploaded source file was not found"))
    assert code == "source_missing"
    code, _ = classify_exception(RuntimeError("Audio extraction failed: invalid data found when processing input"))
    assert code == "unsupported_media"


def test_403_error_distinguishes_video_source_from_llm_auth():
    code, message = classify_exception(RuntimeError("HTTP Error 403: Forbidden while downloading video"))
    assert code == "source_forbidden"
    assert "视频源" in message

    code, message = classify_exception(
        RuntimeError("Client error '401 Unauthorized' for url https://api.example.com/v1/chat/completions")
    )
    assert code == "llm_auth"
    assert "API Key" in message
