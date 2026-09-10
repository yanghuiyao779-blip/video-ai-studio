from app.services.chunking import chunk_segments, format_timestamp
from app.services.domain import TranscriptSegment


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(3661) == "01:01:01"


def test_chunk_segments_respects_boundary():
    segments = [
        TranscriptSegment(0, 1, "alpha"),
        TranscriptSegment(2, 3, "beta"),
        TranscriptSegment(4, 5, "gamma"),
    ]
    chunks = chunk_segments(segments, max_chars=30)
    assert len(chunks) >= 2
    assert "alpha" in chunks[0]
    assert "gamma" in chunks[-1]
