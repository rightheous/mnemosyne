import XCTest

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
