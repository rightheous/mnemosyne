import Foundation
import SwiftUI

/// Per-directory reload signal for the sidebar tree.
///
/// Each `VaultFolderRow` (and the root list in `VaultBrowserView`)
/// registers its folder URL here and watches the URL's generation
/// via `.onChange`. Bumping a single URL re-lists just that folder
/// without disturbing the rest of the tree — folders stay expanded,
/// row selection stays as the user left it. `bumpAll()` powers the
/// "Refresh" menu option for the cases where the user really does
/// want every visible folder re-walked. The pre-`DirectoryReloader`
/// implementation rebuilt the whole List via an `.id(UUID())`
/// modifier, which collapsed every `DisclosureGroup` on a refresh,
/// delete, or md→pdf convert; this object replaces that.
@MainActor
final class DirectoryReloader: ObservableObject {
    @Published private var generations: [URL: UUID] = [:]

    /// Read the current generation for `url`. Returns nil before the
    /// folder has been registered. Reading inside a SwiftUI view body
    /// establishes a dependency on `generations`, so `.onChange` fires
    /// when this URL's value changes.
    func generation(for url: URL) -> UUID? {
        generations[url.standardizedFileURL]
    }

    /// First-time registration. Idempotent — re-registering an existing
    /// URL doesn't bump its generation, so a row that re-appears
    /// (e.g. parent re-renders) doesn't get a spurious reload.
    func register(_ url: URL) {
        let key = url.standardizedFileURL
        if generations[key] == nil {
            generations[key] = UUID()
        }
    }

    /// Mark `url`'s contents as stale. Any row watching this URL will
    /// re-list on the next runloop turn.
    func bump(_ url: URL) {
        generations[url.standardizedFileURL] = UUID()
    }

    /// Mark every registered folder as stale. Used by the explicit
    /// Refresh menu, where the user is asking for a top-to-bottom
    /// re-walk of everything visible.
    func bumpAll() {
        for key in generations.keys {
            generations[key] = UUID()
        }
    }
}
