from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CommunitySignal:
    platform: str
    text: str
    url: str
    engagement: int = 0


@dataclass(slots=True)
class Article:
    id: str
    category: str
    title: str
    summary: str
    url: str
    source: str
    published_at_bjt: str
    language: str
    region: str = "global"
    authority_tier: int = 2
    engagement: int = 0
    full_body: str = ""
    image_url: str = ""
    image_credit: str = ""
    community_signals: list[CommunitySignal] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Article":
        payload = dict(data)
        payload["community_signals"] = [CommunitySignal(**item) for item in payload.get("community_signals", [])]
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SourceRef:
    article_id: str
    title: str
    source: str
    url: str
    published_at_bjt: str
    authority_tier: int


@dataclass(slots=True)
class FactPack:
    story_id: str
    headline: str
    facts: list[str]
    sources: list[SourceRef]
    uncertainties: list[str] = field(default_factory=list)
    community_signals: list[CommunitySignal] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FactPack":
        payload = dict(data)
        payload["sources"] = [SourceRef(**item) for item in payload.get("sources", [])]
        payload["community_signals"] = [CommunitySignal(**item) for item in payload.get("community_signals", [])]
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DailyStorySet:
    category: str
    date_bjt: str
    articles: list[Article]
    fact_packs: list[FactPack]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReadingSection:
    story_id: str
    title: str
    dek: str
    body: str
    takeaway: str
    image_url: str
    image_credit: str
    source_ids: list[str]
    source_refs: list[SourceRef]


@dataclass(slots=True)
class ReadingEdition:
    title: str
    lead: str
    sections: list[ReadingSection]
    synthesis: str


@dataclass(slots=True)
class AudioBlock:
    block_id: str
    speaker: str
    role: str
    text: str
    story_id: str = ""
    audio_file: str = ""
    start_sec: float = 0.0
    duration_sec: float = 0.0


@dataclass(slots=True)
class Chapter:
    chapter_id: str
    title: str
    start_sec: float
    story_id: str = ""


@dataclass(slots=True)
class PodcastEpisode:
    title: str
    description: str
    blocks: list[AudioBlock]
    chapters: list[Chapter] = field(default_factory=list)
    full_audio_file: str = ""
    total_duration_sec: float = 0.0
    tts_provider: str = ""


@dataclass(slots=True)
class EpisodeBundle:
    episode_id: str
    schema_version: int
    category: str
    category_name: str
    date_bjt: str
    story_set: DailyStorySet
    reading: ReadingEdition
    podcast: PodcastEpisode
    status: str = "generated"
    created_at_bjt: str = ""
    updated_at_bjt: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EpisodeBundle":
        payload = dict(data)
        story = payload["story_set"]
        payload["story_set"] = DailyStorySet(
            category=story["category"], date_bjt=story["date_bjt"],
            articles=[Article.from_dict(item) for item in story["articles"]],
            fact_packs=[FactPack.from_dict(item) for item in story["fact_packs"]],
        )
        reading = payload["reading"]
        reading["sections"] = [ReadingSection(
            **{**item, "source_refs": [SourceRef(**source) for source in item.get("source_refs", [])]}
        ) for item in reading["sections"]]
        payload["reading"] = ReadingEdition(**reading)
        podcast = payload["podcast"]
        podcast["blocks"] = [AudioBlock(**item) for item in podcast.get("blocks", [])]
        podcast["chapters"] = [Chapter(**item) for item in podcast.get("chapters", [])]
        payload["podcast"] = PodcastEpisode(**podcast)
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QualityReport:
    episode_id: str
    publishable: bool
    story_count: int
    source_count: int
    domestic_count: int
    reading_chars: int
    podcast_chars: int
    audio_duration_sec: float
    fact_alignment: float
    text_overlap: float
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualityReport":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
