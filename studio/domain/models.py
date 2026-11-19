"""Stable result contracts for CLI and UI. No I/O or provider dependency."""
from dataclasses import dataclass

@dataclass
class VideoResult:
    video_id: str
    title: str = ""
    status: str = "pending"
    audio: str = ""
    transcript: str = ""
    article: str = ""
    error: str = ""

    def table_row(self) -> list[str]:
        return [self.video_id, self.title[:55], self.status, self.audio, self.transcript, self.article, self.error[:240]]

