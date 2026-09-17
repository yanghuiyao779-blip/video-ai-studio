from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.db.models import AppSetting


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    model: str
    api_key: str
    temperature: float
    custom_prompt: str | None
    embedding_model: str = ""


DEFAULTS = {
    # The bundled URL/model are a DeepSeek preset, not a generic custom endpoint.
    # Keeping this semantic value avoids the confusing "Custom + DeepSeek URL" UI.
    "llm.provider": "deepseek",
    "llm.base_url": "https://api.deepseek.com",
    "llm.model": "deepseek-v4-flash",
    "llm.temperature": "0.2",
    "llm.custom_prompt": "",
    "llm.embedding_model": "",
    "task.default_asr_model": "small",
    "task.default_language": "",
    "task.default_summary_enabled": "true",
    "task.default_summary_preset": "standard",
    "task.default_summary_depth": "standard",
}


def _get(db: Session, key: str) -> str | None:
    row = db.get(AppSetting, key)
    if row is None:
        return DEFAULTS.get(key)
    if row.encrypted:
        return decrypt_secret(row.value)
    return row.value


def _set(db: Session, key: str, value: str, encrypted: bool = False) -> None:
    stored = encrypt_secret(value) if encrypted else value
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=stored, encrypted=encrypted))
    else:
        row.value = stored
        row.encrypted = encrypted


def get_llm_config(db: Session, require_key: bool = True) -> LLMConfig | None:
    api_key = _get(db, "llm.api_key")
    if require_key and not api_key:
        return None
    return LLMConfig(
        provider=_get(db, "llm.provider") or "deepseek",
        base_url=_get(db, "llm.base_url") or "",
        model=_get(db, "llm.model") or "",
        api_key=api_key or "",
        temperature=float(_get(db, "llm.temperature") or "0.2"),
        custom_prompt=_get(db, "llm.custom_prompt") or None,
        embedding_model=_get(db, "llm.embedding_model") or "",
    )


def delete_setting(db: Session, key: str) -> None:
    row = db.get(AppSetting, key)
    if row is not None:
        db.delete(row)


def update_llm_config(
    db: Session,
    provider: str,
    base_url: str,
    model: str,
    api_key: str | None,
    temperature: float,
    custom_prompt: str | None,
    embedding_model: str = "",
    clear_api_key: bool = False,
) -> None:
    _set(db, "llm.provider", provider)
    _set(db, "llm.base_url", base_url.rstrip("/"))
    _set(db, "llm.model", model)
    _set(db, "llm.temperature", str(temperature))
    _set(db, "llm.custom_prompt", custom_prompt or "")
    _set(db, "llm.embedding_model", embedding_model.strip())
    if clear_api_key:
        delete_setting(db, "llm.api_key")
    elif api_key:
        _set(db, "llm.api_key", api_key.strip(), encrypted=True)
    db.commit()


def llm_public_view(db: Session) -> dict:
    config = get_llm_config(db, require_key=False)
    api_key = _get(db, "llm.api_key")
    assert config is not None
    return {
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "api_key_configured": bool(api_key),
        "api_key_masked": mask_secret(api_key),
        "temperature": config.temperature,
        "custom_prompt": config.custom_prompt,
        "embedding_model": config.embedding_model,
    }


def task_defaults_public_view(db: Session) -> dict:
    return {
        "asr_model": _get(db, "task.default_asr_model") or "small",
        "language": _get(db, "task.default_language") or "",
        "summary_enabled": (_get(db, "task.default_summary_enabled") or "true").lower() == "true",
        "summary_preset": _get(db, "task.default_summary_preset") or "standard",
        "summary_depth": _get(db, "task.default_summary_depth") or "standard",
    }


def update_task_defaults(db: Session, defaults: dict) -> None:
    _set(db, "task.default_asr_model", defaults["asr_model"])
    _set(db, "task.default_language", defaults["language"] or "")
    _set(db, "task.default_summary_enabled", "true" if defaults["summary_enabled"] else "false")
    _set(db, "task.default_summary_preset", defaults["summary_preset"])
    _set(db, "task.default_summary_depth", defaults["summary_depth"])
    db.commit()
