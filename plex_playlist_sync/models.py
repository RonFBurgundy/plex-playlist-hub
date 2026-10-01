from dataclasses import dataclass, field
from typing import List


@dataclass
class Track:
    title: str
    artist: str
    album: str
    url: str = ""

    def __repr__(self) -> str:
        return f"<Track: {self.artist} - {self.title}>"


@dataclass
class Playlist:
    id: str
    name: str
    description: str = ""
    poster: str = ""
    tracks: List[Track] = field(default_factory=list)

    def __repr__(self) -> str:
        return f"<Playlist: {self.name} (ID: {self.id})>"


@dataclass
class SyncResult:
    playlist_name: str
    total_tracks: int
    matched_tracks: int
    missing_tracks: int
    success: bool
    error: str = ""
