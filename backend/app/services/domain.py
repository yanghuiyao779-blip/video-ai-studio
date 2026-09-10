from dataclasses import dataclass


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    language: str
    language_probability: float | None
    duration: float
    segments: list[TranscriptSegment]
