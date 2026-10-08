import Foundation
import SwiftUI
#if DEBUG
import PDFKit
import UIKit
import PumiceCore
#endif

/// One known vault. Bookmark data is persisted across launches; the
/// security-scoped resource is started lazily on adoption and on the
/// current vault when the app launches. `lastOpenedRelativePath`
/// remembers the most-recently-opened PDF inside this vault so we
/// restore the same document when the user returns to it.
struct VaultRecord: Codable, Identifiable, Equatable {
    let id: UUID
    let bookmark: Data
    let displayName: String
    var lastOpenedRelativePath: String?
    /// Last page the user was reading in `lastOpenedRelativePath`,
    /// zero-indexed. Reset when the user opens a different PDF.
    var lastOpenedPageIndex: Int?
}

@MainActor
final class VaultStore: ObservableObject {
    @Published private(set) var resolvedURL: URL?
    @Published private(set) var status: Status = .launching
    /// Path of the most recently opened PDF in the current vault,
    /// relative to `resolvedURL`. Mirrored from the head of
    /// `vaults` so the reader can read it via a single binding.
    @Published private(set) var lastOpenedRelativePath: String?
    /// All known vaults — current at index 0. The published copy
    /// powers the sidebar's recent-vaults section.
    @Published private(set) var vaults: [VaultRecord] = []

    // Derive UserDefaults keys from the runtime bundle identifier so
    // the reverse-DNS prefix doesn't have to be hard-coded in source
    // (per local build setup, the prefix is configured in
    // Config/Local.xcconfig and isn't checked into the repo).
    private let vaultsKey = "\(Bundle.main.bundleIdentifier ?? "Pumice").vaults"
    private let legacyBookmarkKey = "\(Bundle.main.bundleIdentifier ?? "Pumice").vaultBookmark"
    private let legacyLastOpenedKey = "\(Bundle.main.bundleIdentifier ?? "Pumice").lastOpenedPDF"

    enum Status: Equatable {
        /// Initial state on app launch, before `resolveOnLaunch()` has
        /// finished consulting saved bookmarks. The root view shows
        /// the branded `LaunchView` while we're in this state so the
        /// user doesn't see a flash of onboarding before we know
        /// whether there is a vault.
        case launching
        case idle
        case open
        case staleBookmark
        case accessDenied
        case error(String)
    }

    // MARK: - Launch

    func resolveOnLaunch() async {
        #if DEBUG
        if Self.isUITestMode {
            bootstrapUITestVault()
            return
        }
        #endif
        loadFromDefaults()
        guard let head = vaults.first else {
            status = .idle
            return
        }
        do {
            var isStale = false
            let url = try URL(
                resolvingBookmarkData: head.bookmark,
                options: [],
                relativeTo: nil,
                bookmarkDataIsStale: &isStale
            )
            if isStale {
                // Drop the stale bookmark and fall back to onboarding.
                // The other recent records may still be valid; leave
                // them in place.
                vaults.removeFirst()
                persist()
                status = vaults.isEmpty ? .staleBookmark : .idle
                return
            }
            guard url.startAccessingSecurityScopedResource() else {
                status = .accessDenied
                return
            }
            resolvedURL = url
            lastOpenedRelativePath = head.lastOpenedRelativePath
            status = .open
        } catch {
            vaults.removeFirst()
            persist()
            status = .error(error.localizedDescription)
        }
    }

    // MARK: - Mutation

    /// Set `url` as the current vault. If we already know it (by
    /// resolved path), the existing record is moved to the head;
    /// otherwise a fresh record is created. The previously-current
    /// vault remains in `vaults`, just no longer at the head.
    func adopt(pickedURL url: URL) {
        do {
            let data = try url.bookmarkData(
                options: [],
                includingResourceValuesForKeys: nil,
                relativeTo: nil
            )
            stopCurrentAccess()
            // De-dupe by resolved path. We compare standardised paths
            // because two bookmarks for the same folder will produce
            // slightly different `.bookmark` blobs.
            let targetPath = url.standardizedFileURL.path
            vaults.removeAll { record in
                guard let resolved = resolve(record) else { return false }
                return resolved.url.standardizedFileURL.path == targetPath
            }
            let record = VaultRecord(
                id: UUID(),
                bookmark: data,
                displayName: url.lastPathComponent,
                lastOpenedRelativePath: nil
            )
            vaults.insert(record, at: 0)
            persist()
            resolvedURL = url
            lastOpenedRelativePath = nil
            status = .open
        } catch {
            status = .error(error.localizedDescription)
        }
    }

    /// Switch to a previously-loaded vault by record id. Returns
    /// silently if the bookmark no longer resolves; callers should
    /// verify availability via `availableRecentVaults()` first, so
    /// this only fires on an unexpected race.
    func switchTo(_ recordID: UUID) {
        guard let index = vaults.firstIndex(where: { $0.id == recordID }) else { return }
        guard let resolved = resolve(vaults[index]) else { return }
        let url = resolved.url
        stopCurrentAccess()
        guard url.startAccessingSecurityScopedResource() else {
            status = .accessDenied
            return
        }
        let record = vaults.remove(at: index)
        vaults.insert(record, at: 0)
        persist()
        resolvedURL = url
        lastOpenedRelativePath = record.lastOpenedRelativePath
        status = .open
    }

    /// Remove a known vault from the list. If it was the current one,
    /// promote the next available record (if any) to current; if
    /// nothing is left, return to onboarding.
    func remove(_ recordID: UUID) {
        guard let index = vaults.firstIndex(where: { $0.id == recordID }) else { return }
        let wasCurrent = (index == 0 && status == .open)
        vaults.remove(at: index)
        if wasCurrent {
            stopCurrentAccess()
            resolvedURL = nil
            lastOpenedRelativePath = nil
            if let next = vaults.first, let resolved = resolve(next),
               resolved.url.startAccessingSecurityScopedResource() {
                resolvedURL = resolved.url
                lastOpenedRelativePath = next.lastOpenedRelativePath
                status = .open
            } else {
                status = .idle
            }
        }
        persist()
    }

    /// Drop the current vault but keep recents around. Used by the
    /// "Disconnect" / onboarding-fallback path; the user can pick a
    /// new vault or switch back to a recent one.
    func forget() {
        guard let current = vaults.first else { return }
        remove(current.id)
    }

    // MARK: - Last-opened PDF

    /// Remember the PDF the user just opened, scoped to the current
    /// vault. Persisted across launches as part of the vault's record
    /// so each vault keeps its own restore point. Switching to a new
    /// PDF resets the saved page index — the page is paired with a
    /// specific document, not a general read-position.
    func rememberOpenedPDF(_ pdfURL: URL) {
        guard let vaultURL = resolvedURL else { return }
        let vaultPath = vaultURL.standardizedFileURL.path
        let pdfPath = pdfURL.standardizedFileURL.path
        guard pdfPath.hasPrefix(vaultPath) else { return }
        let relative = String(pdfPath.dropFirst(vaultPath.count))
            .drop(while: { $0 == "/" })
        let relativeString = String(relative)
        guard !relativeString.isEmpty else { return }
        let changedDocument = (lastOpenedRelativePath != relativeString)
        lastOpenedRelativePath = relativeString
        if !vaults.isEmpty {
            vaults[0].lastOpenedRelativePath = relativeString
            if changedDocument {
                vaults[0].lastOpenedPageIndex = nil
            }
            persist()
        }
    }

    /// Record the page the user is currently reading in the last-
    /// opened PDF (zero-indexed). Fires on every scroll-driven page
    /// change; cheap enough that we don't need to throttle.
    func rememberOpenedPage(_ index: Int) {
        guard !vaults.isEmpty else { return }
        guard vaults[0].lastOpenedPageIndex != index else { return }
        vaults[0].lastOpenedPageIndex = index
        persist()
    }

    /// Resolve the last-opened relative path against the current vault.
    /// Returns nil if no path is remembered or the file no longer exists.
    func resolveLastOpened() -> URL? {
        guard let vaultURL = resolvedURL,
              let relative = lastOpenedRelativePath,
              !relative.isEmpty
        else { return nil }
        let candidate = vaultURL.appendingPathComponent(relative)
        guard FileManager.default.fileExists(atPath: candidate.path) else { return nil }
        return candidate
    }

    /// Last-known page index for the current vault's last-opened PDF.
    /// Paired with `resolveLastOpened()` at launch to restore the user
    /// to the page they were reading.
    func resolveLastOpenedPage() -> Int? {
        vaults.first?.lastOpenedPageIndex
    }

    // MARK: - Recent vaults UI helper

    /// Recent vaults (excluding the current one), filtered to those
    /// whose bookmark still resolves to a reachable file. Called by
    /// the sidebar Menu and the manage sheet — both want to hide
    /// records whose underlying folders have been deleted or
    /// otherwise moved out of reach.
    struct AvailableRecent: Identifiable {
        let id: UUID
        let displayName: String
        let url: URL
    }

    func availableRecentVaults() -> [AvailableRecent] {
        guard !vaults.isEmpty else { return [] }
        return vaults
            .dropFirst()
            .compactMap { record in
                guard let resolved = resolve(record) else { return nil }
                guard FileManager.default.fileExists(atPath: resolved.url.path) else { return nil }
                return AvailableRecent(
                    id: record.id,
                    displayName: record.displayName,
                    url: resolved.url
                )
            }
    }

    // MARK: - Internal

    private func resolve(_ record: VaultRecord) -> (url: URL, isStale: Bool)? {
        var isStale = false
        guard let url = try? URL(
            resolvingBookmarkData: record.bookmark,
            options: [],
            relativeTo: nil,
            bookmarkDataIsStale: &isStale
        ) else { return nil }
        return (url, isStale)
    }

    private func stopCurrentAccess() {
        if let url = resolvedURL {
            url.stopAccessingSecurityScopedResource()
        }
    }

    private func loadFromDefaults() {
        if let data = UserDefaults.standard.data(forKey: vaultsKey),
           let records = try? JSONDecoder().decode([VaultRecord].self, from: data) {
            vaults = records
            return
        }
        // Migrate from the single-bookmark layout used pre-recent-vaults.
        if let bookmark = UserDefaults.standard.data(forKey: legacyBookmarkKey) {
            var isStale = false
            let resolvedURL = try? URL(
                resolvingBookmarkData: bookmark,
                options: [],
                relativeTo: nil,
                bookmarkDataIsStale: &isStale
            )
            let displayName = resolvedURL?.lastPathComponent ?? "Vault"
            let lastOpened = UserDefaults.standard.string(forKey: legacyLastOpenedKey)
            let migrated = VaultRecord(
                id: UUID(),
                bookmark: bookmark,
                displayName: displayName,
                lastOpenedRelativePath: lastOpened
            )
            vaults = [migrated]
            persist()
            UserDefaults.standard.removeObject(forKey: legacyBookmarkKey)
            UserDefaults.standard.removeObject(forKey: legacyLastOpenedKey)
        }
    }

    private func persist() {
        if let data = try? JSONEncoder().encode(vaults) {
            UserDefaults.standard.set(data, forKey: vaultsKey)
        }
    }
}

#if DEBUG

// Screenshot capture support. When the test target launches the app with
// "PUMICE_UITEST_VAULT" as a launch argument, the app skips its normal
// vault-resolution flow and instead synthesises a vault under
// Documents/UITestSampleVault with a couple of generated PDFs. That gives
// the UI test a real reader to drive without needing the system Files
// picker, which can't be automated from XCUITest.
extension VaultStore {
    static var isUITestMode: Bool {
        ProcessInfo.processInfo.arguments.contains("PUMICE_UITEST_VAULT")
    }

    func bootstrapUITestVault() {
        let fm = FileManager.default
        guard let docs = fm.urls(for: .documentDirectory, in: .userDomainMask).first else {
            status = .error("Unable to find Documents directory for UI test vault.")
            return
        }
        // The navigation title shows `lastPathComponent` of the vault
        // URL, so the directory name IS the title the user sees in
        // screenshots. "Reading" reads better than "UITestSampleVault".
        // Old-name directory from prior runs (UITestSampleVault) is
        // cleaned up below as well.
        let vaultDir = docs.appendingPathComponent("Reading", isDirectory: true)
        try? fm.removeItem(at: docs.appendingPathComponent("UITestSampleVault"))
        try? fm.removeItem(at: vaultDir)
        let letters = vaultDir.appendingPathComponent("Letters", isDirectory: true)
        let notes = vaultDir.appendingPathComponent("Notes", isDirectory: true)
        for dir in [vaultDir, letters, notes] {
            try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        }

        // PDFs built from public-domain Frankenstein letters (Mary
        // Shelley, 1818). Reusing MarkdownPDFConverter so the sample
        // pages share the v0.3 markdown→PDF visual style; that's the
        // same code the user invokes from the Convert action.
        let pdfSamples: [(dir: URL, name: String, markdown: String)] = [
            (letters, "Letter I.pdf", Self.frankensteinLetterI),
            (letters, "Letter II.pdf", Self.frankensteinLetterII)
        ]
        for sample in pdfSamples {
            let url = sample.dir.appendingPathComponent(sample.name)
            guard !fm.fileExists(atPath: url.path) else { continue }
            let data = MarkdownPDFConverter.convert(sample.markdown)
            try? data.write(to: url)
        }

        let mdSamples: [(dir: URL, name: String, contents: String)] = [
            (notes, "Reading Notes.md", Self.readingNotesMarkdown),
            (notes, "Themes and Symbols.md", Self.themesMarkdown)
        ]
        for sample in mdSamples {
            let url = sample.dir.appendingPathComponent(sample.name)
            guard !fm.fileExists(atPath: url.path) else { continue }
            try? sample.contents.data(using: .utf8)?.write(to: url)
        }

        // No `lastOpenedRelativePath` here on purpose: starting in the
        // sidebar+pickPrompt state makes UI-test navigation easier (we
        // pick the file explicitly) and matches a fresh-vault first
        // run, which is also a useful screenshot in its own right.
        let fakeBookmark = vaultDir.absoluteString.data(using: .utf8) ?? Data()
        let record = VaultRecord(
            id: UUID(),
            bookmark: fakeBookmark,
            displayName: "Sample vault",
            lastOpenedRelativePath: nil,
            lastOpenedPageIndex: nil
        )
        vaults = [record]
        resolvedURL = vaultDir
        lastOpenedRelativePath = nil
        status = .open
    }

    // MARK: - Sample content (public domain)

    private static let frankensteinLetterI = """
    # Letter I

    *To Mrs. Saville, England.*
    *St. Petersburgh, Dec. 11th, 17—*

    You will rejoice to hear that no disaster has accompanied the commencement of an enterprise which you have regarded with such evil forebodings. I arrived here yesterday, and my first task is to assure my dear sister of my welfare and increasing confidence in the success of my undertaking.

    I am already far north of London, and as I walk in the streets of Petersburgh, I feel a cold northern breeze play upon my cheeks, which braces my nerves and fills me with delight. Do you understand this feeling? This breeze, which has travelled from the regions towards which I am advancing, gives me a foretaste of those icy climes.

    Inspirited by this wind of promise, my daydreams become more fervent and vivid. I try in vain to be persuaded that the pole is the seat of frost and desolation; it ever presents itself to my imagination as the region of beauty and delight. There, Margaret, the sun is forever visible, its broad disk just skirting the horizon and diffusing a perpetual splendour.

    There — for with your leave, my sister, I will put some trust in preceding navigators — there snow and frost are banished; and, sailing over a calm sea, we may be wafted to a land surpassing in wonders and in beauty every region hitherto discovered on the habitable globe.

    Its productions and features may be without example, as the phenomena of the heavenly bodies undoubtedly are in those undiscovered solitudes. What may not be expected in a country of eternal light? I may there discover the wondrous power which attracts the needle and may regulate a thousand celestial observations.

    I shall satiate my ardent curiosity with the sight of a part of the world never before visited, and may tread a land never before imprinted by the foot of man. These are my enticements, and they are sufficient to conquer all fear of danger or death and to induce me to commence this laborious voyage with the joy a child feels when he embarks in a little boat, with his holiday mates, on an expedition of discovery up his native river.
    """

    private static let frankensteinLetterII = """
    # Letter II

    *To Mrs. Saville, England.*
    *Archangel, 28th March, 17—*

    How slowly the time passes here, encompassed as I am by frost and snow! Yet a second step is taken towards my enterprise. I have hired a vessel and am occupied in collecting my sailors; those whom I have already engaged appear to be men on whom I can depend and are certainly possessed of dauntless courage.

    But I have one want which I have never yet been able to satisfy, and the absence of the object of which I now feel as a most severe evil. I have no friend, Margaret: when I am glowing with the enthusiasm of success, there will be none to participate my joy; if I am assailed by disappointment, no one will endeavour to sustain me in dejection.

    I shall commit my thoughts to paper, it is true; but that is a poor medium for the communication of feeling. I desire the company of a man who could sympathise with me, whose eyes would reply to mine. You may deem me romantic, my dear sister, but I bitterly feel the want of a friend.

    I have no one near me, gentle yet courageous, possessed of a cultivated as well as of a capacious mind, whose tastes are like my own, to approve or amend my plans. How would such a friend repair the faults of your poor brother! I am too ardent in execution and too impatient of difficulties.

    But it is a still greater evil to me that I am self-educated: for the first fourteen years of my life I ran wild on a common and read nothing but our Uncle Thomas' books of voyages. At that age I became acquainted with the celebrated poets of our own country; but it was only when it had ceased to be in my power to derive its most important benefits from such a conviction that I perceived the necessity of becoming acquainted with more languages than that of my native country.
    """

    private static let readingNotesMarkdown = """
    # Reading Notes: Walton's Letters

    Started this morning with the first letters from Walton to his sister Margaret. Striking how quickly Shelley establishes the **doubling** that runs through the whole novel.

    ## Walton himself

    - A man chasing the sublime in the most literal geographic terms.
    - Speaks of the pole as "the region of beauty and delight," not desolation.
    - His pursuit is self-funded, self-driven, self-justified.

    ## The letter form

    Letters as a frame device do two things here:

    1. Distance the reader from the events to come.
    2. Position Margaret, and us, as silent witnesses.

    > I desire the company of a man who could sympathise with me,
    > whose eyes would reply to mine.

    The loneliness already established before any monster appears.

    ## To follow up

    - Compare with Coleridge's *Rime of the Ancient Mariner*.
    - Note the dating conventions (`Dec. 11th, 17—`) and what they evoke.
    - Track every mention of *ice* in the first volume.
    """

    private static let themesMarkdown = """
    # Themes and Symbols

    ## Fire and ice

    Shelley repeatedly pairs the **destructive heat of creation** with the **cold remove of pursuit**. Walton heads north; Frankenstein, later, flees south. They meet on the ice.

    ## The double

    Walton and Frankenstein mirror each other: both isolated, both ambitious, both warned. Frankenstein's monologue inside the framing letters is itself a warning to Walton, who is in turn warning Margaret.

    ## Solitude

    > I have no friend, Margaret.

    A confession made in the same breath as the boast about the expedition. The work swallows the worker; the worker writes letters to no one who can answer in time.

    ## Open questions

    1. Is Walton's silence at the end of the novel itself a kind of answer?
    2. How does the epistolary distance change once Frankenstein begins his own narrative?
    """
}

#endif
