import json

from app.services.domain import Transcript, TranscriptSegment
from app.services.exporters import export_all


def test_export_all(tmp_path):
    transcript = Transcript(
        language="en",
        language_probability=0.99,
        duration=2.5,
        segments=[TranscriptSegment(0.0, 1.2, "Hello"), TranscriptSegment(1.2, 2.5, "World")],
    )
    files = export_all(
        output_dir=tmp_path,
        source_url="https://example.com/video",
        platform="generic",
        title="Example",
        metadata={"id": "1"},
        transcript=transcript,
        summary="A short summary.",
    )
    assert files["txt"].read_text(encoding="utf-8") == "Hello\nWorld\n"
    assert "00:00:00,000 --> 00:00:01,200" in files["srt"].read_text(encoding="utf-8")
    payload = json.loads(files["json"].read_text(encoding="utf-8"))
    assert payload["summary"] == "A short summary."
    assert payload["transcript"]["segments"][1]["text"] == "World"
    markdown = files["markdown"].read_text(encoding="utf-8")
    assert "## AI 摘要" in markdown
    assert "## 完整文字稿" in markdown
