import Foundation

/// One entry inside a vault folder. The browser lists these one
/// directory at a time and renders folder rows that lazily fetch
/// their own children on expansion. The pre-V0 scanner that walked
/// the entire vault upfront was scrapped because vaults can be
/// arbitrarily large and the user wants the sidebar available
/// immediately.
struct VaultEntry: Identifiable, Hashable, Sendable {
    let url: URL
    let kind: Kind

    enum Kind: Sendable, Hashable {
        case folder
        case pdf
        case markdown
    }

    var id: URL { url }

    var displayName: String {
        switch kind {
        case .folder: url.lastPathComponent
        case .pdf, .markdown: url.deletingPathExtension().lastPathComponent
        }
    }
}

/// File extensions Pumice surfaces as readable leaves in the vault
/// tree. Lowercase comparison; callers normalise.
let pumiceOpenableExtensions: Set<String> = ["pdf", "md"]

/// Lists a single directory's immediate children (no recursion). Used
/// by `VaultFolderRow` on first expand to populate its child rows.
/// Errors are returned, not thrown, so the row can surface them inline
/// without bringing down the rest of the tree — same per-directory
/// error-tolerance the old recursive scanner had.
enum VaultDirectoryLister {
    struct Result: Sendable {
        let entries: [VaultEntry]
        let error: String?
    }

    static func list(_ folder: URL) -> Result {
        let fm = FileManager.default
        let items: [URL]
        do {
            items = try fm.contentsOfDirectory(
                at: folder,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles, .skipsPackageDescendants]
            )
        } catch {
            return Result(entries: [], error: error.localizedDescription)
        }

        var entries: [VaultEntry] = []
        for item in items {
            let isDirectory = (try? item.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) ?? false
            if isDirectory {
                entries.append(VaultEntry(url: item, kind: .folder))
                continue
            }
            let ext = item.pathExtension.lowercased()
            switch ext {
            case "pdf":
                entries.append(VaultEntry(url: item, kind: .pdf))
            case "md":
                entries.append(VaultEntry(url: item, kind: .markdown))
            default:
                continue
            }
        }

        // Folders first, then leaves; alphabetical within each group.
        // Mixing PDFs and markdown together so a folder reads as a
        // single sorted list rather than two stacked partitions.
        entries.sort { lhs, rhs in
            let lhsIsFolder = lhs.kind == .folder
            let rhsIsFolder = rhs.kind == .folder
            if lhsIsFolder != rhsIsFolder {
                return lhsIsFolder
            }
            return lhs.displayName.localizedCaseInsensitiveCompare(rhs.displayName) == .orderedAscending
        }
        return Result(entries: entries, error: nil)
    }
}
