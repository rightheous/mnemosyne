from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from deeptutor.reading import ingestion as ingestion_module
from deeptutor.reading.catalog_models import IngestionStatus, SourceKind
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.extract import (
    SECTION_HARD_CHARS,
    split_into_sections,
    split_markdown_by_headings,
)
from deeptutor.reading.ingestion import (
    MAX_TRANSCRIPT_BYTES,
    TRANSCRIPT_UNAVAILABLE_TEXT,
    BilibiliMedia,
    ReadingIngestionService,
    TranscriptSegment,
    build_transcript_segments,
    normalize_transcript_segments,
    parse_bilibili_url,
    parse_youtube_url,
)
from deeptutor.reading.models import (
    Annotation,
    ReadingError,
    TextPositionSelector,
    TextQuoteSelector,
)
from deeptutor.reading.store import ReadingStore
from deeptutor.services.web_source.snapshot_assets import SnapshotAsset
from deeptutor.tools.web_fetch import FetchOutcome, _extract_readable
from deeptutor.video_learning import service as video_learning_service

_ARTICLE_FIXTURE = Path(__file__).parents[1] / "fixtures" / "web" / "vector_article.html"


@pytest.fixture
def stores(tmp_path: Path):
    root = tmp_path / "reading"
    return ReadingStore(root), ReadingCatalogStore(root)


@pytest.mark.asyncio
async def test_web_import_uses_safe_fetch_result_and_builds_sections(stores) -> None:
    reading, catalog = stores

    async def fetcher(url: str, **_kwargs):
        return FetchOutcome(
            ok=True,
            url=url,
            title="A careful article",
            markdown="# A careful article\n\nFirst claim.\n\nSecond claim.",
        )

    service = ReadingIngestionService(reading, catalog, web_fetcher=fetcher)
    queued = service.queue_url("https://example.com/article")
    ready = await service.process_url(queued.material_id)

    assert queued.status is IngestionStatus.QUEUED
    assert ready.status is IngestionStatus.READY
    assert ready.source_kind is SourceKind.WEB
    manifest = reading.manifest(ready.material_id)
    assert manifest.title == "A careful article"
    assert "First claim" in reading.unit_text(ready.material_id, 1)
    assert reading.outline(ready.material_id)[0].synthesised is True


@pytest.mark.asyncio
async def test_web_import_is_rich_localizes_images_and_preserves_old_revision(stores) -> None:
    reading, catalog = stores
    url = "https://example.com/article"

    async def fetcher(_url: str, **_kwargs):
        return FetchOutcome(
            ok=True,
            url="https://example.com/final/article",
            title="Snapshot",
            markdown=(
                "<!-- source: https://example.com/legacy -->\n"
                "# Snapshot\n\n![Diagram](https://cdn.example.com/diagram.png)"
            ),
        )

    async def image_fetcher(_url: str):
        return SnapshotAsset(b"\x89PNG\r\n\x1a\nimage", "image/png", "png")

    service = ReadingIngestionService(
        reading,
        catalog,
        web_fetcher=fetcher,
        image_fetcher=image_fetcher,
    )
    queued = service.queue_url(url)
    reading.ingest_units(
        queued.material_id,
        filename=f"{queued.material_id}.md",
        units=["<!-- source: https://example.com/old -->\n# Old snapshot"],
        source_type="url_snapshot",
        source_url=url,
    )

    ready = await service.process_url(queued.material_id)
    manifest = reading.manifest(ready.material_id)
    current = reading.unit_text(ready.material_id, 1)

    assert manifest.content_format == "web_markdown"
    assert manifest.source_url == "https://example.com/final/article"
    assert manifest.revision == 2
    assert "<!-- source:" not in current
    assert "/api/reading/materials/" in current
    assert (
        reading.asset_path(
            ready.material_id,
            next((reading._dir(ready.material_id) / "assets").iterdir()).name,
        )
        is not None
    )
    revisions = reading.revisions(ready.material_id)
    assert [row.revision for row in revisions] == [1]
    assert "# Old snapshot" in reading.revision_unit_text(ready.material_id, 1, 1)


def test_revision_migration_reanchors_reliable_quote(stores) -> None:
    reading, _catalog = stores
    material_id = "abcdef0123456789"

    reading.ingest_units(
        material_id,
        filename="article.md",
        units=["# First section\n\nThe quick brown fox jumps over the lazy dog."],
        source_type="url_snapshot",
    )
    annotation = reading.save_annotation(
        material_id,
        Annotation(
            annotation_id="test001",
            locator=1,
            quote="quick brown fox",
            selectors=(
                TextQuoteSelector(
                    exact="quick brown fox",
                    prefix="The ",
                    suffix=" jumps",
                ),
                TextPositionSelector(start=21, end=36),
            ),
        ),
    )
    assert annotation.material_revision == 1

    reading.ingest_units(
        material_id,
        filename="article-v2.md",
        units=["# Revised\n\nIntro. The quick brown fox jumps over the lazy dog. End."],
        source_type="url_snapshot",
    )
    stored = reading.annotations(material_id)
    assert len(stored) == 1
    migrated = stored[0]
    assert migrated.resolution == "resolved"
    assert migrated.material_revision == 2
    assert "quick brown fox" in migrated.quote
    quote_selector = next(s for s in migrated.selectors if isinstance(s, TextQuoteSelector))
    position_selector = next(s for s in migrated.selectors if isinstance(s, TextPositionSelector))
    unit_text = reading.unit_text(material_id, migrated.locator)
    assert unit_text[position_selector.start : position_selector.end] == quote_selector.exact


def test_revision_migration_checks_each_material_annotation_file(stores) -> None:
    reading, _catalog = stores
    material_id = "abcdef0123456789"
    reading.ingest_units(
        material_id,
        filename="article.md",
        units=["The quick brown fox jumps. A second claim stays here."],
        source_type="url_snapshot",
    )
    reading.save_annotation(
        material_id,
        Annotation(
            annotation_id="first",
            locator=1,
            quote="quick brown fox",
            selectors=(TextQuoteSelector(exact="quick brown fox"),),
        ),
    )
    second_path = reading._dir(material_id) / "annotations" / "another-material.json"
    second_path.write_text(
        json.dumps(
            [
                Annotation(
                    annotation_id="second",
                    locator=1,
                    quote="second claim",
                    selectors=(TextQuoteSelector(exact="second claim"),),
                ).to_dict(),
                Annotation(
                    annotation_id="position-only",
                    locator=1,
                    selectors=(TextPositionSelector(start=5, end=10),),
                ).to_dict(),
            ]
        ),
        encoding="utf-8",
    )

    reading.ingest_units(
        material_id,
        filename="article-v2.md",
        units=["An introduction. The quick brown fox jumps. A second claim stays here."],
        source_type="url_snapshot",
    )

    assert reading.annotations(material_id)[0].material_revision == 2
    second_rows = [Annotation.from_dict(row) for row in json.loads(second_path.read_text())]
    assert second_rows[0].material_revision == 2
    assert second_rows[0].resolution == "resolved"
    assert second_rows[1].material_revision == 1
    assert second_rows[1].resolution == "unresolved"


def test_revision_migration_marks_gone_quote_unresolved(stores) -> None:
    reading, _catalog = stores
    material_id = "abcdef0123456789"

    reading.ingest_units(
        material_id,
        filename="article.md",
        units=["# Section\n\nThe unique phrase is here."],
        source_type="url_snapshot",
    )
    reading.save_annotation(
        material_id,
        Annotation(
            annotation_id="test002",
            locator=1,
            quote="unique phrase",
            selectors=(TextQuoteSelector(exact="unique phrase", prefix="The ", suffix=" is"),),
        ),
    )

    reading.ingest_units(
        material_id,
        filename="article-v2.md",
        units=["# Rewritten\n\nEntirely different content."],
        source_type="url_snapshot",
    )
    stored = reading.annotations(material_id)
    assert len(stored) == 1
    assert stored[0].resolution == "unresolved"
    assert stored[0].material_revision == 1  # kept pinned to old revision
    assert stored[0].quote == "unique phrase"


def test_revision_migration_marks_repeated_quote_ambiguous(stores) -> None:
    reading, _catalog = stores
    material_id = "abcdef0123456789"

    reading.ingest_units(
        material_id,
        filename="article.md",
        units=["# Section\n\nA key claim with unique context."],
        source_type="url_snapshot",
    )
    reading.save_annotation(
        material_id,
        Annotation(
            annotation_id="test003",
            locator=1,
            quote="key claim",
            selectors=(TextQuoteSelector(exact="key claim", prefix="A ", suffix=" with"),),
        ),
    )

    reading.ingest_units(
        material_id,
        filename="article-v2.md",
        units=["# Duplicated\n\nA key claim here.\n\nAnother key claim there."],
        source_type="url_snapshot",
    )
    stored = reading.annotations(material_id)
    assert len(stored) == 1
    assert stored[0].resolution == "ambiguous"
    assert stored[0].material_revision == 1


def test_revision_migration_preserves_old_annotations_for_audit(stores) -> None:
    reading, _catalog = stores
    material_id = "abcdef0123456789"

    reading.ingest_units(
        material_id,
        filename="article.md",
        units=["# Section\n\nThe original phrase."],
        source_type="url_snapshot",
    )
    reading.save_annotation(
        material_id,
        Annotation(
            annotation_id="test004",
            locator=1,
            quote="original phrase",
            selectors=(TextQuoteSelector(exact="original phrase"),),
        ),
    )

    reading.ingest_units(
        material_id,
        filename="article-v2.md",
        units=["# Changed\n\nA new phrase entirely."],
        source_type="url_snapshot",
    )

    revision_dir = reading._dir(material_id) / "revisions" / "000001"
    assert revision_dir.is_dir()
    saved_annotations = revision_dir / "annotations" / f"{material_id}.json"
    assert saved_annotations.is_file()
    import json

    saved_rows = json.loads(saved_annotations.read_text(encoding="utf-8"))
    assert len(saved_rows) == 1
    assert saved_rows[0]["quote"] == "original phrase"
    assert saved_rows[0]["resolution"] == "resolved"


@pytest.mark.asyncio
async def test_web_article_fixture_builds_heading_derived_outline(stores) -> None:
    reading, catalog = stores
    title, markdown = _extract_readable(_ARTICLE_FIXTURE.read_text(encoding="utf-8"))

    async def fetcher(url: str, **_kwargs):
        return FetchOutcome(ok=True, url=url, title=title, markdown=markdown)

    service = ReadingIngestionService(reading, catalog, web_fetcher=fetcher)
    queued = service.queue_url("https://example.com/structured-article")
    ready = await service.process_url(queued.material_id)

    assert ready.status is IngestionStatus.READY
    assert reading.manifest(ready.material_id).unit_count == 4
    outline = reading.outline(ready.material_id)
    assert [(row.locator, row.title, row.level) for row in outline] == [
        (1, "Transformer (deep learning)", 1),
        (2, "History", 2),
        (3, "Predecessors", 3),
        (4, "Applications", 2),
    ]
    assert all(row.synthesised is False for row in outline)
    stored_text = "\n".join(
        reading.unit_text(ready.material_id, locator) for locator in range(1, 5)
    )
    assert "Jump to content" not in stored_text
    assert "navigation footer" not in stored_text


def test_heading_sections_keep_long_continuations_under_the_same_title() -> None:
    markdown = (
        "# Article\n\nLead.\n\n## Long section\n\n"
        + ("history detail " * (SECTION_HARD_CHARS // 8))
        + "\n\n## Finish\n\nDone."
    )

    units, outline = split_markdown_by_headings(markdown)

    long_rows = [row for row in outline if row.title == "Long section"]
    assert len(long_rows) > 1
    assert [row.locator for row in long_rows] == list(
        range(long_rows[0].locator, long_rows[-1].locator + 1)
    )
    # The first piece also carries the heading line; the paragraph payload
    # itself still obeys the existing hard-split limit.
    assert all(
        len(units[row.locator - 1]) <= SECTION_HARD_CHARS + len("## Long section\n\n")
        for row in long_rows
    )


@pytest.mark.parametrize(
    "block",
    [
        pytest.param("````md\n```py\n# Not a heading\n```\n````", id="longer-fence-around-example"),
        pytest.param("```bash\n```py\n# Not a heading\n```", id="fence-with-info-does-not-close"),
        pytest.param("~~~\n# Not a heading\n~~~", id="tilde-fence"),
    ],
)
def test_heading_splitter_ignores_headings_inside_fenced_code(block: str) -> None:
    markdown = f"# Guide\n\nIntro.\n\n{block}\n\n## Next\n\nDone."

    units, outline = split_markdown_by_headings(markdown)

    assert [row.title for row in outline] == ["Guide", "Next"]
    assert "# Not a heading" in units[0]


def test_heading_splitter_does_not_open_a_fence_on_inline_backticks() -> None:
    markdown = "# Guide\n\n```inline``` code.\n\n## Next\n\nDone."

    _units, outline = split_markdown_by_headings(markdown)

    assert [row.title for row in outline] == ["Guide", "Next"]


def test_heading_splitter_falls_back_when_only_the_page_title_exists() -> None:
    markdown = "# Article title\n\nA flat article paragraph.\n\nAnother paragraph."

    units, outline = split_markdown_by_headings(markdown)

    assert units == split_into_sections(markdown)
    assert outline == ()


@pytest.mark.asyncio
async def test_failed_url_import_is_retryable(stores, caplog: pytest.LogCaptureFixture) -> None:
    _reading, catalog = stores

    async def fetcher(_url: str, **_kwargs):
        return FetchOutcome(ok=False, error="blocked by host policy")

    service = ReadingIngestionService(stores[0], catalog, web_fetcher=fetcher)
    queued = service.queue_url("https://example.com/private")
    with caplog.at_level(logging.ERROR, logger="deeptutor.reading.ingestion"):
        failed = await service.process_url(queued.material_id)

    assert failed.status is IngestionStatus.FAILED
    assert failed.error_code == "web_fetch_failed"
    assert "blocked" in failed.error_detail
    assert "Reading URL ingestion failed" in caplog.text


@pytest.mark.asyncio
async def test_youtube_import_prefers_timed_captions(stores) -> None:
    reading, catalog = stores

    async def youtube_loader(_url: str, _languages):
        return (
            "Retrieval Lecture",
            "https://i.ytimg.com/vi/abc123xyz00/hqdefault.jpg",
            [
                TranscriptSegment(0, 12, "Welcome to the lecture."),
                TranscriptSegment(12, 28, "We now define dense retrieval."),
            ],
        )

    service = ReadingIngestionService(reading, catalog, youtube_loader=youtube_loader)
    queued = service.queue_url("https://youtu.be/abc123xyz00")
    ready = await service.process_url(queued.material_id)

    assert ready.source_kind is SourceKind.YOUTUBE
    assert ready.render_mode == "video"
    assert ready.cover_url.endswith("hqdefault.jpg")
    assert reading.manifest(ready.material_id).unit == "segment"
    assert reading.manifest(ready.material_id).render_mode == "video"
    assert reading.unit_references(ready.material_id)[1].source_href == "#t=12"


@pytest.mark.asyncio
async def test_youtube_ingestion_default_uses_native_provider(
    stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    reading, catalog = stores
    monkeypatch.setattr(
        video_learning_service,
        "load_video_learning_settings",
        lambda: video_learning_service.DEFAULT_VIDEO_LEARNING_SETTINGS,
    )

    async def metadata(_request):
        return {"title": "Native lecture", "thumbnail_url": "https://img/native.jpg"}

    async def transcript(_video_id, _language):
        return (
            [{"start": 0, "end": 14, "text": "Native caption."}],
            "en",
            "youtube_transcript_api",
        )

    monkeypatch.setattr(video_learning_service, "_youtube_metadata", metadata)
    monkeypatch.setattr(video_learning_service, "_youtube_transcript", transcript)

    service = ReadingIngestionService(reading, catalog)
    queued = service.queue_url("https://youtu.be/abc123xyz00")
    ready = await service.process_url(queued.material_id)
    manifest = reading.manifest(ready.material_id)

    assert ready.status is IngestionStatus.READY
    assert manifest.title == "Native lecture"
    assert ready.cover_url == "https://img/native.jpg"
    assert manifest.extractor == "youtube-captions"
    assert reading.unit_text(ready.material_id, 1) == "Native caption."


@pytest.mark.asyncio
async def test_youtube_ingestion_uses_configured_invidious_captions(
    stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    reading, catalog = stores
    monkeypatch.setattr(
        video_learning_service,
        "load_video_learning_settings",
        lambda: {
            "version": 1,
            "default_provider": "invidious",
            "youtube": {"transcript_provider": "youtube_transcript_api"},
            "invidious": {"api_base_url": "http://localhost:3000", "public_base_url": ""},
        },
    )

    async def metadata(_client, _base, _video_id):
        return {
            "title": "Mirrored lecture",
            "thumbnail_url": "https://img/mirror.jpg",
            "captions": [{"label": "English", "languageCode": "en"}],
        }

    async def transcript(_client, _base, _video_id, _captions, _language, **_kwargs):
        assert _language == ["zh-CN", "zh", "en"]
        return ([{"start": 0, "end": 14, "text": "Mirrored caption."}], "en", "invidious")

    monkeypatch.setattr(video_learning_service, "_invidious_metadata", metadata)
    monkeypatch.setattr(video_learning_service, "_invidious_transcript", transcript)

    service = ReadingIngestionService(reading, catalog)
    queued = service.queue_url("https://youtu.be/abc123xyz00")
    ready = await service.process_url(queued.material_id)
    manifest = reading.manifest(ready.material_id)

    assert ready.status is IngestionStatus.READY
    assert manifest.title == "Mirrored lecture"
    assert ready.cover_url == "https://img/mirror.jpg"
    assert manifest.extractor == "youtube-captions"
    assert reading.unit_text(ready.material_id, 1) == "Mirrored caption."


@pytest.mark.asyncio
async def test_youtube_ingestion_keeps_playback_when_invidious_provider_fails(
    stores, monkeypatch: pytest.MonkeyPatch
) -> None:
    reading, catalog = stores
    monkeypatch.setattr(
        video_learning_service,
        "load_video_learning_settings",
        lambda: {
            "version": 1,
            "default_provider": "invidious",
            "youtube": {"transcript_provider": "youtube_transcript_api"},
            "invidious": {"api_base_url": "http://localhost:3000", "public_base_url": ""},
        },
    )

    async def metadata(_client, _base, _video_id):
        raise video_learning_service.TimedMediaError("Invidious request failed with HTTP 503.")

    monkeypatch.setattr(video_learning_service, "_invidious_metadata", metadata)
    service = ReadingIngestionService(reading, catalog)
    queued = service.queue_url("https://youtu.be/abc123xyz00")
    ready = await service.process_url(queued.material_id)

    assert ready.status is IngestionStatus.READY
    assert ready.cover_url.endswith("hqdefault.jpg")
    assert reading.manifest(ready.material_id).extractor == "youtube-no-captions"
    assert reading.unit_text(ready.material_id, 1) == TRANSCRIPT_UNAVAILABLE_TEXT


@pytest.mark.parametrize(
    ("url", "video_id", "start"),
    [
        ("https://youtu.be/abc123xyz00?t=82", "abc123xyz00", 82),
        ("https://www.youtube.com/watch?v=abc123xyz00&t=1m2s&si=tracking", "abc123xyz00", 62),
        ("https://youtube.com/shorts/abc123xyz00", "abc123xyz00", 0),
        ("https://youtube.com/live/abc123xyz00?start=12", "abc123xyz00", 12),
        ("https://youtube.com/embed/abc123xyz00", "abc123xyz00", 0),
    ],
)
def test_youtube_url_shapes_are_canonical(url: str, video_id: str, start: int) -> None:
    parsed = parse_youtube_url(url)
    assert parsed.video_id == video_id
    assert parsed.entry_time_seconds == start
    assert "si=" not in parsed.canonical_url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.com/watch?v=abc123xyz00",
        "https://youtube.com/watch?v=../../etc",
        "https://youtube.com.evil.test/watch?v=abc123xyz00",
    ],
)
def test_invalid_youtube_urls_are_rejected(url: str) -> None:
    with pytest.raises(ReadingError):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    ("url", "bvid", "page", "start"),
    [
        ("https://www.bilibili.com/video/BV1E7wtzaEdq/", "BV1E7wtzaEdq", 1, 0),
        ("https://m.bilibili.com/video/BV1E7wtzaEdq?p=2&t=82", "BV1E7wtzaEdq", 2, 82),
        ("https://player.bilibili.com/player.html?bvid=BV1E7wtzaEdq&p=3", "BV1E7wtzaEdq", 3, 0),
        ("https://b23.tv/BV1E7wtzaEdq", "BV1E7wtzaEdq", 1, 0),
    ],
)
def test_bilibili_url_shapes_are_canonical(url: str, bvid: str, page: int, start: int) -> None:
    parsed = parse_bilibili_url(url)
    assert parsed.bvid == bvid
    assert parsed.page_number == page
    assert parsed.entry_time_seconds == start
    assert "spm_id_from=" not in parsed.canonical_url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.com/video/BV1E7wtzaEdq",
        "https://bilibili.com.evil.test/video/BV1E7wtzaEdq",
        "https://www.bilibili.com/video/not-a-bvid",
        "https://b23.tv/some-short-link",
    ],
)
def test_invalid_bilibili_urls_are_rejected(url: str) -> None:
    with pytest.raises(ReadingError):
        parse_bilibili_url(url)


@pytest.mark.asyncio
async def test_bilibili_import_uses_native_video_metadata_and_subtitles(stores) -> None:
    reading, catalog = stores

    async def bilibili_loader(_url: str, _languages):
        return BilibiliMedia(
            title="Agent Skill",
            cover_url="https://i0.hdslb.com/cover.jpg",
            duration_seconds=1951,
            page_number=1,
            cid=36694721904,
            segments=[TranscriptSegment(0, 31, "视频内容介绍")],
            chapters=[TranscriptSegment(0, 31, "视频内容介绍")],
        )

    service = ReadingIngestionService(reading, catalog, bilibili_loader=bilibili_loader)
    queued = service.queue_url("https://www.bilibili.com/video/BV1E7wtzaEdq/?spm_id_from=tracking")
    ready = await service.process_url(queued.material_id)

    assert queued.source_kind is SourceKind.BILIBILI
    assert ready.source_kind is SourceKind.BILIBILI
    assert ready.duration_seconds == 1951
    assert ready.cover_url.endswith("cover.jpg")
    assert reading.manifest(ready.material_id).extractor == "bilibili-subtitles"
    assert reading.unit_references(ready.material_id)[0].source_href == "#t=0"


@pytest.mark.asyncio
async def test_bilibili_chapters_remain_navigable_without_claiming_transcript(stores) -> None:
    reading, catalog = stores

    async def bilibili_loader(_url: str, _languages):
        return BilibiliMedia(
            title="Chaptered lecture",
            cover_url="",
            duration_seconds=120,
            page_number=1,
            cid=123,
            segments=[],
            chapters=[
                TranscriptSegment(0, 60, "LLM"),
                TranscriptSegment(60, 120, "Agent"),
            ],
        )

    service = ReadingIngestionService(reading, catalog, bilibili_loader=bilibili_loader)
    queued = service.queue_url("https://www.bilibili.com/video/BV1E7wtzaEdq")
    ready = await service.process_url(queued.material_id)

    manifest = reading.manifest(ready.material_id)
    assert manifest.extractor == "bilibili-chapters-only"
    assert reading.unit_references(ready.material_id)[1].source_href == "#t=60"
    assert "Chapter marker: Agent" in reading.unit_text(ready.material_id, 2)
    assert "Spoken transcript unavailable" in reading.unit_text(ready.material_id, 2)


def test_caption_flashes_become_stable_learning_segments() -> None:
    cues = [
        TranscriptSegment(0.0, 10.0, "One"),
        TranscriptSegment(10.0, 22.0, "sentence."),
        TranscriptSegment(22.0, 45.0, "Next concept."),
    ]
    segments = build_transcript_segments(cues)
    assert segments[0] == TranscriptSegment(0.0, 22.0, "One sentence.")
    assert segments[1].start_seconds == 22.0


def test_transcript_normalization_has_a_storage_budget(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.reading.ingestion.MAX_TRANSCRIPT_BYTES", 8)
    cues = normalize_transcript_segments(
        [
            {"start": 0, "duration": 1, "text": "1234"},
            {"start": 1, "duration": 1, "text": "5678"},
            {"start": 2, "duration": 1, "text": "overflow"},
        ]
    )
    assert MAX_TRANSCRIPT_BYTES > 8
    assert [cue.text for cue in cues] == ["1234", "5678"]


@pytest.mark.asyncio
async def test_missing_youtube_captions_does_not_block_native_playback(stores) -> None:
    reading, catalog = stores

    async def youtube_loader(_url: str, _languages):
        return "Visual lecture", "", []

    service = ReadingIngestionService(reading, catalog, youtube_loader=youtube_loader)
    queued = service.queue_url("https://youtube.com/live/abc123xyz00?start=12")
    ready = await service.process_url(queued.material_id)

    manifest = reading.manifest(ready.material_id)
    assert ready.status is IngestionStatus.READY
    assert manifest.extractor == "youtube-no-captions"
    assert reading.unit_text(ready.material_id, 1) == TRANSCRIPT_UNAVAILABLE_TEXT
    assert reading.unit_references(ready.material_id)[0].source_href == "#t=12"


@pytest.mark.asyncio
async def test_local_video_keeps_playable_raw_and_transcribes_chunks(
    stores, tmp_path: Path
) -> None:
    reading, catalog = stores
    source = tmp_path / "lecture.mp4"
    source.write_bytes(b"fake but stable video bytes")

    async def chunker(_path: Path):
        return [(0.0, 600.0, b"audio-one"), (600.0, 720.0, b"audio-two")]

    async def transcriber(audio: bytes, **_kwargs):
        return "first section" if audio == b"audio-one" else "second section"

    service = ReadingIngestionService(
        reading,
        catalog,
        media_chunker=chunker,
        transcriber=transcriber,
    )
    ready = await service.import_media(source, filename="lecture.mp4")

    assert ready.status is IngestionStatus.READY
    assert ready.source_kind is SourceKind.VIDEO
    assert reading.manifest(ready.material_id).render_mode == "video"
    assert reading.raw_path(ready.material_id).read_bytes() == source.read_bytes()
    assert reading.unit_text(ready.material_id, 2) == "second section"


@pytest.mark.asyncio
async def test_media_without_a_configured_provider_fails_before_running_ffmpeg(
    stores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Name the missing setting, and do not spend ffmpeg proving it is missing."""
    reading, catalog = stores
    source = tmp_path / "lecture.mp4"
    source.write_bytes(b"video bytes")
    ran = {"chunker": False}

    async def chunker(_path: Path):
        ran["chunker"] = True
        return []

    monkeypatch.setattr(
        ingestion_module,
        "_probe_stt_configuration",
        lambda: "No active STT model is configured. Set it in Settings > Voice.",
    )
    service = ReadingIngestionService(reading, catalog, media_chunker=chunker)
    service._probes_stt = True

    queued = await service.queue_media(source, filename="lecture.mp4")
    failed = await service.process_media(queued.material_id)

    assert failed.status is IngestionStatus.FAILED
    assert failed.error_code == "stt_not_configured"
    assert "Settings > Voice" in failed.error_detail
    assert ran["chunker"] is False
    # The upload survives the failure, so configuring a provider and retrying
    # is all the user has to do.
    assert reading.raw_path(queued.material_id).read_bytes() == b"video bytes"


@pytest.mark.asyncio
async def test_media_retry_reruns_transcription_from_the_stored_original(
    stores, tmp_path: Path
) -> None:
    """A failed transcription must not cost the user the upload.

    The original is stored before speech-to-text is attempted, so retrying is
    a server-side re-run — not "please find that two-gigabyte lecture again".
    """
    reading, catalog = stores
    source = tmp_path / "lecture.mp4"
    source.write_bytes(b"stable video bytes")
    attempts = {"n": 0}

    async def chunker(_path: Path):
        return [(0.0, 600.0, b"audio-one")]

    async def transcriber(_audio: bytes, **_kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("No endpoint URL configured for STT.")
        return "the transcript, second time around"

    service = ReadingIngestionService(
        reading, catalog, media_chunker=chunker, transcriber=transcriber
    )
    queued = await service.queue_media(source, filename="lecture.mp4")
    failed = await service.process_media(queued.material_id)

    assert failed.status is IngestionStatus.FAILED
    # Still playable while it is broken: the bytes never depended on the text.
    assert reading.raw_path(queued.material_id).read_bytes() == b"stable video bytes"

    recovered = await service.retry(queued.material_id)

    assert recovered.status is IngestionStatus.READY
    assert reading.unit_text(queued.material_id, 1) == "the transcript, second time around"
    assert reading.raw_path(queued.material_id).read_bytes() == b"stable video bytes"


@pytest.mark.asyncio
async def test_media_ingestion_failure_is_logged_and_persisted(
    stores,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reading, catalog = stores
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"broken video")

    async def failing_chunker(_path: Path):
        raise RuntimeError("decoder crashed")

    monkeypatch.setattr(ingestion_module, "_probe_stt_configuration", lambda: "")
    service = ReadingIngestionService(*stores, media_chunker=failing_chunker)
    with caplog.at_level(logging.ERROR, logger="deeptutor.reading.ingestion"):
        with pytest.raises(RuntimeError, match="decoder crashed"):
            await service.import_media(source)

    material_id = next(row.material_id for row in catalog.list_materials())
    failed = catalog.get_material(material_id)
    assert failed is not None
    assert failed.status is IngestionStatus.FAILED
    assert "Reading media ingestion failed" in caplog.text


def test_mnemosyne_pdf_upload_annotation_sync_restart_and_export(tmp_path: Path) -> None:
    """Exercise the real PDF fixture through UNIT-01's persistent service boundary."""
    import asyncio
    import copy
    import hashlib
    import uuid

    import pymupdf

    from deeptutor.mnemosyne.library import LibraryAdapter, LibraryError, viewport_point

    repository_root = Path(__file__).resolve().parents[4]
    source = repository_root / "contracts" / "fixtures" / "bilingual-geometry.pdf"
    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    data_root = tmp_path / "user" / "workspace" / "reading"
    adapter = LibraryAdapter(ReadingStore(data_root))

    document = adapter.upload_pdf(source_bytes, "bilingual-geometry.pdf", title="Geometry fixture")
    document_id, version_id = document["document_id"], document["version_id"]
    assert document["source_sha256"] == source_sha
    assert version_id == f"sha256:{source_sha}"
    assert document["parse_state"] == "ready"
    assert document["page_count"] == 2
    assert document["index_state"] == "failed"
    assert document["index_error_code"] == "embedding_provider_unavailable"
    assert adapter.download_original(document_id, version_id) == source_bytes

    page0 = adapter.get_page(document_id, version_id, 0)
    page1 = adapter.get_page(document_id, version_id, 1)
    assert page0["geometry"]["rotation_degrees"] == 0
    assert page1["geometry"]["rotation_degrees"] == 90
    assert page0["geometry"]["crop_box"] == [20.0, 30.0, 580.0, 760.0]
    assert page1["geometry"]["crop_box"] == [10.0, 20.0, 590.0, 770.0]
    search_anchors = adapter.search_anchors(document_id, version_id, "CAPACITOR")
    assert search_anchors
    search_anchor = search_anchors[0]
    assert search_anchor["quote"].casefold() == "capacitor"
    assert page0["text"][search_anchor["start_scalar"]:search_anchor["end_scalar"]] == search_anchor["quote"]
    probe_point = [80.0, 120.0]
    assert all(
        abs(a - b) < 1e-6
        for a, b in zip(
            viewport_point(viewport_point(probe_point, page1["geometry"]), page1["geometry"], inverse=True),
            probe_point,
        )
    )

    def uid() -> str:
        return str(uuid.uuid4())

    def mutation(operation: str, annotation_id: str, base_revision: int, annotation=None, client_id=None):
        row = {
            "client_mutation_id": uid(),
            "client_id": client_id or uid(),
            "document_id": document_id,
            "version_id": version_id,
            "annotation_id": annotation_id,
            "base_revision": base_revision,
            "created_at": "2026-10-09T01:00:00Z",
            "operation": operation,
        }
        if operation == "upsert":
            row["annotation"] = annotation
        return row

    first_segment = page0["segments"][0]
    anchor = {
        "document_id": document_id,
        "version_id": version_id,
        "page_index": 0,
        "parse_revision": page0["parse_revision"],
        "text_sha256": page0["text_sha256"],
        "start_scalar": first_segment["start_scalar"],
        "end_scalar": first_segment["end_scalar"],
        "quote": page0["text"][first_segment["start_scalar"]:first_segment["end_scalar"]],
        "rects": [first_segment["rect"]],
    }
    highlight_id, note_id, bookmark_id, ink_id = uid(), uid(), uid(), uid()
    client_a, client_b = uid(), uid()
    initial = [
        mutation("upsert", highlight_id, 0, {
            "annotation_id": highlight_id, "document_id": document_id, "version_id": version_id,
            "page_index": 0, "kind": "highlight",
            "payload": {"anchor": anchor, "color": "#FFDD4480"},
        }, client_a),
        mutation("upsert", note_id, 0, {
            "annotation_id": note_id, "document_id": document_id, "version_id": version_id,
            "page_index": 1, "kind": "note",
            "payload": {"position": [30.0, 30.0], "body": "회전 페이지 메모", "anchor": None},
        }, client_a),
        mutation("upsert", bookmark_id, 0, {
            "annotation_id": bookmark_id, "document_id": document_id, "version_id": version_id,
            "page_index": 1, "kind": "bookmark", "payload": {"label": "둘째 페이지"},
        }, client_a),
        mutation("upsert", ink_id, 0, {
            "annotation_id": ink_id, "document_id": document_id, "version_id": version_id,
            "page_index": 1, "kind": "ink", "payload": {"strokes": [{
                "stroke_id": uid(), "tool": "pen", "color": "#2040C0FF", "width_pt": 2,
                "points": [
                    {"x": 40.0, "y": 100.0, "pressure": 1, "t_ms": 0},
                    {"x": 80.0, "y": 120.0, "pressure": 1.0, "t_ms": 15},
                ],
            }]},
        }, client_a),
    ]
    batch = {"contract_version": "0.1.0", "document_id": document_id,
             "version_id": version_id, "mutations": initial}
    receipt = asyncio.run(adapter.apply_mutations(batch))
    assert [row["status"] for row in receipt["results"]] == ["applied"] * 4
    assert [row["server_revision"] for row in receipt["results"]] == [1, 2, 3, 4]
    replay = asyncio.run(adapter.apply_mutations(copy.deepcopy(batch)))
    assert replay == receipt

    # JSON key order and mathematical equality of finite numbers are ignored
    # for an idempotency replay; the original receipt and watermark are stable.
    numeric_replay = copy.deepcopy(batch)
    numeric_replay["mutations"][3]["annotation"]["payload"]["strokes"][0]["width_pt"] = 2.0
    assert asyncio.run(adapter.apply_mutations(numeric_replay)) == receipt

    snapshot_a = asyncio.run(adapter.snapshot(document_id, version_id))
    assert snapshot_a["snapshot_revision"] == 4
    assert {row["kind"] for row in snapshot_a["annotations"]} == {"highlight", "note", "bookmark", "ink"}
    cursor = snapshot_a["next_cursor"]

    note = next(row for row in snapshot_a["annotations"] if row["annotation_id"] == note_id)
    edit = mutation("upsert", note_id, note["server_revision"], {
        "annotation_id": note_id, "document_id": document_id, "version_id": version_id,
        "page_index": 1, "kind": "note",
        "payload": {"position": [35.0, 35.0], "body": "기기 B 수정", "anchor": None},
    }, client_b)
    edit_batch = {**batch, "mutations": [edit]}
    applied_edit = asyncio.run(adapter.apply_mutations(edit_batch))["results"][0]
    assert applied_edit["status"] == "applied" and applied_edit["server_revision"] == 5

    stale_edit = mutation("upsert", note_id, note["server_revision"], {
        "annotation_id": note_id, "document_id": document_id, "version_id": version_id,
        "page_index": 1, "kind": "note",
        "payload": {"position": [40.0, 40.0], "body": "기기 A 오래된 수정", "anchor": None},
    }, client_a)
    conflict_batch = {**batch, "mutations": [stale_edit]}
    conflict = asyncio.run(adapter.apply_mutations(conflict_batch))["results"][0]
    assert conflict["status"] == "conflict" and conflict["current"]["server_revision"] == 5
    assert asyncio.run(adapter.apply_mutations(copy.deepcopy(conflict_batch)))["results"][0] == conflict

    change_page = asyncio.run(adapter.changes(cursor, limit=1))
    assert len(change_page["changes"]) == 1 and change_page["changes"][0]["server_revision"] == 5
    assert change_page["changes"][0]["payload"]["body"] == "기기 B 수정"
    assert change_page["has_more"] is False

    export = adapter.export_annotated_pdf(document_id, version_id, 5, include_ink=True)
    exported = adapter.download_export(export["export_id"])
    assert export["original_sha256"] == source_sha
    assert export["export_sha256"] == hashlib.sha256(exported).hexdigest()
    assert exported != source_bytes
    with pymupdf.open(stream=exported, filetype="pdf") as exported_pdf:
        assert any(row[1] == "둘째 페이지" for row in exported_pdf.get_toc())
        assert list(exported_pdf[0].annots() or [])
        assert list(exported_pdf[1].annots() or [])
        assert exported_pdf.page_count == 2

    # Restart from the same on-disk state: source, cursors, tombstones, and log
    # remain durable. A stale delete cannot erase the newer edit.
    restarted = LibraryAdapter(ReadingStore(data_root))
    assert restarted.download_original(document_id, version_id) == source_bytes
    restarted_snapshot = asyncio.run(restarted.snapshot(document_id, version_id))
    assert restarted_snapshot["snapshot_revision"] == 5
    current_note = next(row for row in restarted_snapshot["annotations"] if row["annotation_id"] == note_id)
    delete = mutation("delete", note_id, current_note["server_revision"], client_id=client_b)
    deleted = asyncio.run(restarted.apply_mutations({**batch, "mutations": [delete]}))["results"][0]
    assert deleted["status"] == "applied" and deleted["current"]["deleted"] is True

    revive = mutation("upsert", note_id, deleted["current"]["server_revision"], {
        "annotation_id": note_id, "document_id": document_id, "version_id": version_id,
        "page_index": 1, "kind": "note",
        "payload": {"position": [35.0, 35.0], "body": "되살리기 시도", "anchor": None},
    }, client_a)
    tombstone_conflict = asyncio.run(restarted.apply_mutations({**batch, "mutations": [revive]}))["results"][0]
    assert tombstone_conflict["status"] == "conflict" and tombstone_conflict["current"]["deleted"] is True

    assert hashlib.sha256(restarted.download_original(document_id, version_id)).hexdigest() == source_sha
    with pytest.raises(LibraryError, match="UUID"):
        restarted.get_document("../../etc/passwd")
    with pytest.raises(LibraryError, match="page_index"):
        restarted.get_page(document_id, version_id, -1)
    invalid_anchor = copy.deepcopy(anchor)
    invalid_anchor["quote"] = "not the source quote"
    with pytest.raises(LibraryError, match="citation text"):
        restarted.verify_anchor(invalid_anchor, page0)


def test_library_http_router_settings_and_pdf_round_trip(tmp_path: Path) -> None:
    """Verify the UNIT-01 router contract without mounting shared auth/middleware."""
    import hashlib
    import sqlite3

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from deeptutor.mnemosyne.library import LibraryAdapter, build_library_router

    repository_root = Path(__file__).resolve().parents[4]
    source = repository_root / "contracts" / "fixtures" / "bilingual-geometry.pdf"
    source_bytes = source.read_bytes()
    secret_store: dict[str, str] = {}
    data_root = tmp_path / "router" / "workspace" / "reading"
    library = LibraryAdapter(
        ReadingStore(data_root),
        settings_defaults_provider=lambda: {
            "provider": {
                "adapter": "openai-compatible",
                "base_url": "https://llm.example.test/v1",
                "model": "fixture-model",
            },
            "response_language": "ko",
        },
        settings_secret_writer=lambda value: secret_store.__setitem__("api_key", value),
        settings_credential_reader=lambda: "api_key" in secret_store,
    )
    app = FastAPI()
    app.include_router(build_library_router(library))
    headers = {"X-Mnemosyne-Contract-Version": "0.1.0"}

    with TestClient(app) as client:
        settings = client.get("/v1/settings", headers=headers)
        assert settings.status_code == 200, settings.text
        assert settings.headers["ETag"] == '"1"'
        updated = client.put(
            "/v1/settings",
            headers={**headers, "If-Match": '"1"', "X-Confirm-Action": "settings.update"},
            json={
                "provider": {
                    "adapter": "openai-compatible",
                    "base_url": "https://llm.example.test/v1",
                    "model": "fixture-model-v2",
                    "api_key": "unit-test-secret-must-not-enter-sqlite",
                },
                "response_language": "ko",
            },
        )
        assert updated.status_code == 200
        assert updated.headers["ETag"] == '"2"'
        assert updated.json()["provider"]["credential_configured"] is True
        assert "api_key" not in updated.text
        assert secret_store["api_key"] == "unit-test-secret-must-not-enter-sqlite"
        with sqlite3.connect(data_root / "_mnemosyne.sqlite3") as db:
            serialized = " ".join(str(row) for row in db.execute("SELECT public_json FROM mnemosyne_public_settings"))
        assert "unit-test-secret-must-not-enter-sqlite" not in serialized

        upload = client.post(
            "/v1/documents",
            headers=headers,
            files={"file": ("bilingual-geometry.pdf", source_bytes, "application/pdf")},
            data={"title": "Router fixture"},
        )
        assert upload.status_code == 201, upload.text
        document = upload.json()
        assert document["source_sha256"] == hashlib.sha256(source_bytes).hexdigest()
        assert document["parse_state"] == "ready"
        original = client.get(
            f"/v1/documents/{document['document_id']}/file",
            params={"version_id": document["version_id"]},
            headers=headers,
        )
        assert original.status_code == 200
        assert original.content == source_bytes
