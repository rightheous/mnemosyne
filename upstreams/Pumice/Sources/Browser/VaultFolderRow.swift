import SwiftUI
import UIKit

/// Sidebar row for a vault folder. Wraps its children in a
/// `DisclosureGroup` that lists the folder's contents on first
/// expand, so the browser never enumerates more of the filesystem
/// than the user is currently looking at. Recursive: each child
/// folder is itself a `VaultFolderRow` with its own expansion state.
///
/// Reload behaviour is mediated by a shared `DirectoryReloader`
/// injected via the environment. Each row registers its own folder
/// URL on appear; bumping that URL re-fires `load()` without touching
/// `isExpanded`, so a delete/convert/refresh refreshes contents in
/// place rather than collapsing the tree.
struct VaultFolderRow: View {
    let folder: URL
    /// Bubbled up to `VaultBrowserView` when the user invokes Delete on
    /// a leaf row. The browser owns the confirm-alert state and the
    /// FileManager call so all rows share one delete flow.
    let requestDelete: ((URL) -> Void)?

    @EnvironmentObject private var reloader: DirectoryReloader

    @State private var entries: [VaultEntry] = []
    @State private var loadError: String?
    @State private var isLoaded = false
    @State private var isLoading = false
    @State private var isExpanded = false

    init(
        folder: URL,
        requestDelete: ((URL) -> Void)? = nil
    ) {
        self.folder = folder
        self.requestDelete = requestDelete
    }

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            content
        } label: {
            Label {
                Text(folder.lastPathComponent)
            } icon: {
                Image(systemName: "folder")
                    .foregroundStyle(Color.pumiceFolderTint)
            }
        }
        .onChange(of: isExpanded) { _, expanded in
            if expanded && !isLoaded && !isLoading {
                load()
            }
        }
        .onAppear {
            reloader.register(folder)
        }
        .onChange(of: reloader.generation(for: folder)) { _, _ in
            guard isLoaded else { return }
            load()
        }
    }

    @ViewBuilder
    private var content: some View {
        if let loadError {
            Label(loadError, systemImage: "exclamationmark.triangle")
                .foregroundStyle(.orange)
                .font(.caption)
        } else if isLoading {
            HStack(spacing: 6) {
                ProgressView().controlSize(.mini)
                Text("Loading…").font(.caption).foregroundStyle(.secondary)
            }
        } else if isLoaded && entries.isEmpty {
            Text("Empty folder")
                .foregroundStyle(.secondary)
                .font(.caption)
        } else {
            ForEach(entries) { entry in
                switch entry.kind {
                case .folder:
                    VaultFolderRow(
                        folder: entry.url,
                        requestDelete: requestDelete
                    )
                    .selectionDisabled()
                case .pdf:
                    NavigationLink(value: entry.url) {
                        VaultRowLabels.pdf(entry.displayName)
                    }
                    .contextMenu { deleteButton(for: entry.url) }
                    .swipeActions(edge: .trailing) { deleteButton(for: entry.url) }
                case .markdown:
                    NavigationLink(value: entry.url) {
                        VaultRowLabels.markdown(entry.displayName)
                    }
                    .contextMenu { deleteButton(for: entry.url) }
                    .swipeActions(edge: .trailing) { deleteButton(for: entry.url) }
                }
            }
        }
    }

    @ViewBuilder
    private func deleteButton(for url: URL) -> some View {
        Button(role: .destructive) {
            requestDelete?(url)
        } label: {
            Label("Delete", systemImage: "trash")
        }
    }

    private func load() {
        isLoading = true
        let url = folder
        Task {
            let result = await Task.detached(priority: .userInitiated) {
                VaultDirectoryLister.list(url)
            }.value
            entries = result.entries
            loadError = result.error
            isLoaded = true
            isLoading = false
        }
    }
}

/// Shared file-row label styling so the root list and every nested
/// `VaultFolderRow` render PDFs and markdown notes the same way.
enum VaultRowLabels {
    static func pdf(_ displayName: String) -> some View {
        Label {
            Text(displayName)
        } icon: {
            Image(systemName: "doc.richtext")
                .foregroundStyle(.orange)
        }
    }

    static func markdown(_ displayName: String) -> some View {
        Label {
            Text(displayName)
        } icon: {
            Image(systemName: "doc.text")
                .foregroundStyle(.blue)
        }
    }
}

extension Color {
    /// Warm pumice-stone tint for folder icons. Sits between the orange
    /// of PDF rows and the blue of markdown rows so folders read as the
    /// calm container they are while still feeling like part of the
    /// rock palette rather than system grey. Dynamic across appearance
    /// so the stone reads as warm-mid-tone on both light and dark.
    static var pumiceFolderTint: Color {
        Color(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark
                ? UIColor(red: 0.72, green: 0.66, blue: 0.56, alpha: 1)
                : UIColor(red: 0.50, green: 0.44, blue: 0.36, alpha: 1)
        })
    }
}
