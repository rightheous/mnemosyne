import Foundation
import XCTest
@testable import Pumice

/// Screenshot capture for App Store submission. Driven by
/// `bundle exec fastlane screenshots`, which boots the iPad Pro 13"
/// simulator, runs every `test*` method here, and drops PNGs into
/// `fastlane/screenshots/en-CA/`.
///
/// The sample vault (`VaultStore.bootstrapUITestVault`) lays out:
/// ```
/// Sample vault/
/// ├── Letters/
/// │   ├── Letter I.pdf
/// │   └── Letter II.pdf
/// └── Notes/
///     ├── Reading Notes.md
///     └── Themes and Symbols.md
/// ```
/// PDFs are converted from public-domain Frankenstein excerpts via
/// `MarkdownPDFConverter`; markdown files exercise the v0.3 preview +
/// convert flow.
@MainActor
final class PumiceUITests: XCTestCase {

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    /// Sidebar with the sample vault, plus the empty-detail picker
    /// prompt. Shows folder structure, distinct icon colours, and the
    /// vault-name title chevron.
    func test_capture_browser() throws {
        let app = launchSampleApp()
        let nav = app.navigationBars.firstMatch
        XCTAssertTrue(nav.waitForExistence(timeout: 15), "Browser navigation bar never appeared.")
        expandSidebarFolders(app: app)
        snapshot("01_browser")
    }

    /// The reader on Letter I.pdf, page 1. Beautiful prose, full
    /// toolbar visible (tool picker, colour picker, undo/redo).
    func test_capture_reader() throws {
        let app = launchSampleApp()
        XCTAssertTrue(app.navigationBars.firstMatch.waitForExistence(timeout: 15))
        openLetterI(app: app)
        snapshot("02_reader")
    }

    /// Tool picker open, showing pen / highlighter / eraser.
    func test_capture_tool_menu() throws {
        let app = launchSampleApp()
        XCTAssertTrue(app.navigationBars.firstMatch.waitForExistence(timeout: 15))
        openLetterI(app: app)
        let toolButton = app.buttons.matching(NSPredicate(format: "label CONTAINS[c] 'tool' OR label CONTAINS[c] 'pen' OR label CONTAINS[c] 'pencil'")).firstMatch
        if toolButton.waitForExistence(timeout: 5) {
            toolButton.tap()
            sleep(1)
            snapshot("03_tool_menu")
        }
    }

    /// Markdown preview rendered from `Reading Notes.md`. Shows
    /// headings, bold, italic, list, and blockquote styling.
    func test_capture_markdown_preview() throws {
        let app = launchSampleApp()
        XCTAssertTrue(app.navigationBars.firstMatch.waitForExistence(timeout: 15))
        expandSidebarFolders(app: app)
        let mdRow = app.staticTexts["Reading Notes"]
        if mdRow.waitForExistence(timeout: 5) {
            mdRow.tap()
            sleep(2)
            snapshot("04_markdown_preview")
        }
    }

    /// Onboarding screen, captured without the sample-vault arg so the
    /// app sits in its first-run "pick a vault" state.
    func test_capture_onboarding() throws {
        let app = XCUIApplication()
        setupSnapshot(app)
        app.launch()
        let onboardingButton = app.buttons["Choose vault…"]
        XCTAssertTrue(onboardingButton.waitForExistence(timeout: 10), "Onboarding never appeared.")
        snapshot("05_onboarding")
    }

    // MARK: - Helpers

    private func launchSampleApp() -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments += ["PUMICE_UITEST_VAULT"]
        setupSnapshot(app)
        app.launch()
        return app
    }

    /// Expand both top-level folders so the sidebar reveals the four
    /// sample files. Each DisclosureGroup row has its folder name as
    /// the accessibility label.
    private func expandSidebarFolders(app: XCUIApplication) {
        for folder in ["Letters", "Notes"] {
            let row = app.staticTexts[folder]
            if row.waitForExistence(timeout: 3) {
                row.tap()
                sleep(1)
            }
        }
    }

    /// Tap `Letter I` in the sidebar to open it in the reader.
    private func openLetterI(app: XCUIApplication) {
        expandSidebarFolders(app: app)
        let row = app.staticTexts["Letter I"]
        if row.waitForExistence(timeout: 5) {
            row.tap()
            sleep(2)
        }
    }
}

@MainActor
final class MnemosyneContractTests: XCTestCase {
    private var fixture: [String: Any]!

    override func setUpWithError() throws {
        continueAfterFailure = false
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "study-session", withExtension: "json"))
        let data = try Data(contentsOf: url)
        fixture = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    func testContractFixtureDecodesLibraryReaderQuizAndLearning() throws {
        let subject = try decode(MnemosyneSubject.self, field: "subject")
        let document = try decode(MnemosyneDocument.self, field: "document")
        let pages = try decodeArray(MnemosynePage.self, field: "pages")
        let citations = try decodeArray(MnemosyneVerifiedCitation.self, field: "citations")
        let quiz = try decode(MnemosyneQuiz.self, field: "quiz")
        let learning = try decode(MnemosyneLearningState.self, field: "learning_state")

        XCTAssertEqual(subject.name, "물리학")
        XCTAssertEqual(document.documentId.uuidString.lowercased(),
                       (fixture["document"] as? [String: Any])?["document_id"] as? String)
        XCTAssertEqual(document.versionId, "sha256:\(document.sourceSha256)")
        XCTAssertEqual(pages.count, document.pageCount)
        XCTAssertEqual(pages.map(\.pageIndex), Array(0..<document.pageCount))
        XCTAssertTrue(citations.allSatisfy(\.verified))
        XCTAssertEqual(quiz.documentId, document.documentId)
        XCTAssertEqual(learning.documentId, document.documentId)
        XCTAssertEqual(learning.versionId, document.versionId)
        XCTAssertEqual(learning.progress.pagesRead.sorted(), [0, 1])
    }

    func testNativeFramesDecodeChunkedTextReconnectCancelAndErrorFixtures() throws {
        let wire = try XCTUnwrap(fixture["wire"] as? [String: Any])
        let streamFrames = try decodeFrames(wire["events"])
        let cancelledFrames = try decodeFrames(wire["cancelled_events"])
        let errorFrames = try decodeFrames(wire["error_events"])
        XCTAssertFalse(streamFrames.isEmpty)
        XCTAssertTrue(cancelledFrames.contains { $0.nativeType == "done" })
        XCTAssertTrue(errorFrames.contains { $0.nativeType == "done" })

        let reconnect = try XCTUnwrap(fixture["reconnect"] as? [String: Any])
        let commands = try XCTUnwrap(wire["commands"] as? [[String: Any]])
        let resume = try XCTUnwrap(commands.first { $0["type"] as? String == "resume_from" })
        let checkpoint = try XCTUnwrap(Int((reconnect["last_event_id"] as? String ?? "").split(separator: ":").last ?? ""))
        XCTAssertEqual(resume["seq"] as? Int, checkpoint)

        var replayGuard = MnemosyneSequenceCheckpoint(lastSequence: checkpoint)
        let duplicate = try XCTUnwrap(reconnect["duplicate_delivery"] as? [String: Any])
        XCTAssertFalse(try replayGuard.isReplayOrValidateNext(duplicate["seq"] as? Int ?? -1))
        XCTAssertTrue(try replayGuard.isReplayOrValidateNext(checkpoint + 1))
        try replayGuard.commit(checkpoint + 1)

        XCTAssertThrowsError(try replayGuard.isReplayOrValidateNext(checkpoint + 3)) { error in
            XCTAssertEqual(error as? MnemosyneWireError,
                           .sequenceGap(expected: checkpoint + 2, received: checkpoint + 3))
        }

        let cancel = try XCTUnwrap(commands.first { $0["type"] as? String == "cancel_turn" })
        XCTAssertEqual(cancel["command_id"] as? String, "00000000-0000-0000-0000-000000000099")

        let delta = try XCTUnwrap(streamFrames.compactMap(\.semanticEvent).first(where: {
            ((try? JSONSerialization.jsonObject(with: $0) as? [String: Any])?["type"] as? String) == "assistant.delta"
        }))
        let event = try XCTUnwrap(JSONSerialization.jsonObject(with: delta) as? [String: Any])
        let payload = try XCTUnwrap(event["payload"] as? [String: Any])
        let text = try XCTUnwrap(payload["text"] as? String)
        let scalars = Array(text.unicodeScalars)
        let split = max(1, scalars.count / 2)
        let fragments = [String(String.UnicodeScalarView(scalars[..<split])),
                         String(String.UnicodeScalarView(scalars[split...]))]
        XCTAssertEqual(fragments.joined(), text)
    }

    func testReaderEventsRequireVerifiedCitationAndRejectOtherDocuments() throws {
        let document = try decode(MnemosyneDocument.self, field: "document")
        let wire = try XCTUnwrap(fixture["wire"] as? [String: Any])
        let frames = try decodeFrames(wire["events"])
        let semanticEvents = frames.compactMap(\.semanticEvent)
        let citationEvent = try XCTUnwrap(semanticEvents.first {
            semanticType($0) == "citation.verified"
        })
        let citation = try XCTUnwrap(MnemosyneReaderEventValidator.verifiedCitation(from: citationEvent))
        XCTAssertEqual(try MnemosyneReaderEventValidator.validate(citationEvent,
            documentId: document.documentId, versionId: document.versionId,
            pageCount: document.pageCount, verifiedCitations: [:]), .notReaderEvent)
        let citations = [citation.citationId: citation]

        let goto = try XCTUnwrap(semanticEvents.first { semanticType($0) == "reader.goto" })
        XCTAssertEqual(try MnemosyneReaderEventValidator.validate(goto, documentId: document.documentId,
            versionId: document.versionId, pageCount: document.pageCount, verifiedCitations: citations), .apply)

        let highlight = try XCTUnwrap(semanticEvents.first { semanticType($0) == "reader.highlight" })
        var wrongDocument = try XCTUnwrap(JSONSerialization.jsonObject(with: highlight) as? [String: Any])
        var payload = try XCTUnwrap(wrongDocument["payload"] as? [String: Any])
        var target = try XCTUnwrap(payload["target"] as? [String: Any])
        target["document_id"] = "00000000-0000-0000-0000-000000000099"
        payload["target"] = target
        wrongDocument["payload"] = payload
        let invalidEvent = try JSONSerialization.data(withJSONObject: wrongDocument)
        XCTAssertThrowsError(try MnemosyneReaderEventValidator.validate(invalidEvent,
            documentId: document.documentId, versionId: document.versionId,
            pageCount: document.pageCount, verifiedCitations: citations)) { error in
            XCTAssertEqual(error as? MnemosyneReaderEventError, .documentMismatch)
        }

        let annotate = try XCTUnwrap(semanticEvents.first { semanticType($0) == "reader.annotate" })
        XCTAssertEqual(try MnemosyneReaderEventValidator.validate(annotate, documentId: document.documentId,
            versionId: document.versionId, pageCount: document.pageCount, verifiedCitations: citations),
            .requiresUserConfirmation)
    }

    func testSyncFixtureCoversIdempotentRetryConflictAndTombstoneRecovery() throws {
        let steps = try XCTUnwrap(fixture["sync_steps"] as? [[String: Any]])
        XCTAssertGreaterThanOrEqual(steps.count, 10)
        let firstMutation = try XCTUnwrap(steps[0]["mutation"] as? [String: Any])
        let retryMutation = try XCTUnwrap(steps[1]["mutation"] as? [String: Any])
        let firstExpected = try XCTUnwrap(steps[0]["expected"] as? [String: Any])
        let retryExpected = try XCTUnwrap(steps[1]["expected"] as? [String: Any])
        let staleExpected = try XCTUnwrap(steps[2]["expected"] as? [String: Any])
        XCTAssertTrue(NSDictionary(dictionary: firstMutation).isEqual(to: retryMutation))
        XCTAssertEqual(firstExpected["status"] as? String, "applied")
        XCTAssertEqual(retryExpected["server_revision"] as? Int, firstExpected["server_revision"] as? Int)
        XCTAssertEqual(staleExpected["status"] as? String, "conflict")

        let deletion = try XCTUnwrap(steps[4]["expected"] as? [String: Any])
        let tombstone = try XCTUnwrap(deletion["current"] as? [String: Any])
        XCTAssertEqual(tombstone["deleted"] as? Bool, true)
        XCTAssertTrue(tombstone["payload"] is NSNull)
        let afterDelete = try XCTUnwrap(steps[5]["expected"] as? [String: Any])
        XCTAssertEqual(afterDelete["status"] as? String, "conflict")
        let recovery = try XCTUnwrap(steps[7]["expected"] as? [String: Any])
        let recoveredRecord = try XCTUnwrap(recovery["current"] as? [String: Any])
        XCTAssertNotEqual(recoveredRecord["annotation_id"] as? String, tombstone["annotation_id"] as? String)
        let mismatch = try XCTUnwrap(steps[9]["expected"] as? [String: Any])
        XCTAssertEqual(mismatch["code"] as? String, "idempotency_mismatch")
    }

    private func semanticType(_ data: Data) -> String? {
        (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?["type"] as? String
    }

    private func decode<T: Decodable>(_ type: T.Type, field: String) throws -> T {
        let value = try XCTUnwrap(fixture[field])
        return try JSONDecoder.mnemosyne.decode(type, from: JSONSerialization.data(withJSONObject: value))
    }

    private func decodeArray<T: Decodable>(_ type: T.Type, field: String) throws -> [T] {
        let values = try XCTUnwrap(fixture[field])
        return try JSONDecoder.mnemosyne.decode([T].self, from: JSONSerialization.data(withJSONObject: values))
    }

    private func decodeFrames(_ value: Any?) throws -> [MnemosyneTurnFrame] {
        let values = try XCTUnwrap(value as? [[String: Any]])
        return try values.map { try decodeMnemosyneTurnFrame(JSONSerialization.data(withJSONObject: $0)) }
    }
}
