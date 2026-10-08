import SwiftUI
import UIKit
import PumiceCore

struct VaultBrowserView: View {
    let vaultURL: URL

    @EnvironmentObject private var vault: VaultStore
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var readerController = PDFReaderController()
    /// Per-directory reload coordinator. Re-list a single folder in
    /// place after a delete/convert/refresh instead of replacing the
    /// whole sidebar identity (which collapses every `DisclosureGroup`
    /// and the user's expansion state with it).
    @StateObject private var reloader = DirectoryReloader()

    @State private var rootEntries: [VaultEntry] = []
    @State private var rootError: String?
    @State private var rootLoaded = false
    @State private var selection: URL?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @State private var showingManageSheet = false
    @State private var showingConnectPicker = false
    @State private var availableRecents: [VaultStore.AvailableRecent] = []
    /// Page index to restore on first launch of the previously-opened
    /// PDF. Consumed once by the detail view; subsequent in-session
    /// PDF switches start at page 0.
    @State private var pendingRestorePage: Int?

    /// True while a markdown→PDF conversion is in flight. Disables the
    /// Convert button so a re-tap doesn't queue a second conversion.
    @State private var isConverting = false
    @State private var conversionError: String?

    /// The file the user just asked to delete from the tree. Non-nil
    /// triggers the confirm alert; cleared on cancel or completion.
    @State private var pendingDeletion: URL?
    @State private var deletionError: String?

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            sidebar
        } detail: {
            detail
        }
        .environmentObject(reloader)
        .task(id: vaultURL) { await loadRoot() }
        .onAppear { reloader.register(vaultURL) }
        .onChange(of: reloader.generation(for: vaultURL)) { _, _ in
            Task { await loadRoot() }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active {
                readerController.saveIfNeeded()
            }
        }
        .onChange(of: selection) { _, newSelection in
            if let url = newSelection, url.pathExtension.lowercased() == "pdf" {
                vault.rememberOpenedPDF(url)
            }
        }
        .onChange(of: vault.vaults) { _, _ in
            availableRecents = vault.availableRecentVaults()
        }
        .onChange(of: vaultURL) { _, _ in
            // Vault just switched. Flush any pending strokes from the
            // previous vault's document, then drop the selection so the
            // detail view falls back to the picker prompt. Leaving the
            // prior selection up would either keep showing a PDF from
            // the old vault or, if a path collision lined up by chance,
            // open a different file with the same relative path under
            // the new vault.
            readerController.saveIfNeeded()
            selection = nil
            pendingRestorePage = nil
        }
        .alert(
            "Delete this file?",
            isPresented: Binding(
                get: { pendingDeletion != nil },
                set: { if !$0 { pendingDeletion = nil } }
            ),
            presenting: pendingDeletion
        ) { url in
            Button("Delete", role: .destructive) {
                let target = url
                pendingDeletion = nil
                Task { await deleteFile(target) }
            }
            Button("Cancel", role: .cancel) {
                pendingDeletion = nil
            }
        } message: { url in
            Text("\(url.lastPathComponent) will be removed from your vault. This can't be undone from inside Pumice.")
        }
        .alert(
            "Couldn't delete",
            isPresented: Binding(
                get: { deletionError != nil },
                set: { if !$0 { deletionError = nil } }
            ),
            presenting: deletionError
        ) { _ in
            Button("OK", role: .cancel) { deletionError = nil }
        } message: { message in
            Text(message)
        }
    }

    private var sidebar: some View {
        Group {
            if rootLoaded {
                List(selection: $selection) {
                    if let rootError {
                        Label(rootError, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.orange)
                            .font(.caption)
                    } else if rootEntries.isEmpty {
                        Text("Vault is empty")
                            .foregroundStyle(.secondary)
                            .font(.caption)
                    }
                    ForEach(rootEntries) { entry in
                        switch entry.kind {
                        case .folder:
                            VaultFolderRow(
                                folder: entry.url,
                                requestDelete: { pendingDeletion = $0 }
                            )
                            .selectionDisabled()
                        case .pdf:
                            NavigationLink(value: entry.url) {
                                VaultRowLabels.pdf(entry.displayName)
                            }
                            .contextMenu { deleteMenuButton(for: entry.url) }
                            .swipeActions(edge: .trailing) { deleteSwipeButton(for: entry.url) }
                        case .markdown:
                            NavigationLink(value: entry.url) {
                                VaultRowLabels.markdown(entry.displayName)
                            }
                            .contextMenu { deleteMenuButton(for: entry.url) }
                            .swipeActions(edge: .trailing) { deleteSwipeButton(for: entry.url) }
                        }
                    }
                }
                .listStyle(.sidebar)
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle(vaultURL.lastPathComponent)
        .toolbarTitleMenu {
            // Tapping the vault name in the navigation bar exposes the
            // menu (vault switching, connect new, manage). iOS draws a
            // disclosure chevron next to the title for free — that's
            // the only affordance the user gets, so don't suppress it.
            Button("Refresh", systemImage: "arrow.clockwise") {
                // Bump every registered folder's generation so each
                // expanded row re-lists in place. The root itself is
                // registered too; its bump fires `loadRoot()` via the
                // top-level onChange.
                reloader.bumpAll()
            }
            if !availableRecents.isEmpty {
                Section("Switch to") {
                    ForEach(availableRecents) { entry in
                        Button {
                            vault.switchTo(entry.id)
                        } label: {
                            Label(entry.displayName, systemImage: "folder")
                        }
                    }
                }
            }
            Button("Connect new vault", systemImage: "folder.badge.plus") {
                showingConnectPicker = true
            }
            if !availableRecents.isEmpty {
                Button("Manage vaults", systemImage: "slider.horizontal.3") {
                    showingManageSheet = true
                }
            }
        }
        .sheet(isPresented: $showingManageSheet) {
            VaultManageSheet()
                .environmentObject(vault)
        }
        .sheet(isPresented: $showingConnectPicker) {
            VaultPicker(
                // Start the picker in the parent of the current vault so
                // "Connect new vault" lands in a familiar place. The
                // parent may be outside the existing security-scoped
                // grant; the picker treats `directoryURL` as a hint and
                // the user re-picks from the system UI, so this never
                // violates the sandbox.
                startURL: vaultURL.deletingLastPathComponent(),
                onPick: { url in
                    showingConnectPicker = false
                    guard url.startAccessingSecurityScopedResource() else { return }
                    vault.adopt(pickedURL: url)
                },
                onCancel: { showingConnectPicker = false }
            )
            .ignoresSafeArea()
        }
    }

    @ViewBuilder
    private var detail: some View {
        if let url = selection {
            switch url.pathExtension.lowercased() {
            case "pdf":
                PDFReaderView(
                    pdfURL: url,
                    controller: readerController,
                    restorePageIndex: pendingRestorePage,
                    onSidebarTap: { columnVisibility = .detailOnly },
                    onPageChanged: { index in vault.rememberOpenedPage(index) }
                )
                    .id(url)
                    .ignoresSafeArea(edges: .bottom)
                    .navigationTitle(url.deletingPathExtension().lastPathComponent)
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbarTitleMenu { fileTitleMenu(for: url) }
                    .toolbar { readerToolbar }
                    .onAppear {
                        // Page-restore is a one-shot: clear after the
                        // reader consumes it so a subsequent PDF switch
                        // starts at page 0.
                        pendingRestorePage = nil
                    }
            case "md":
                MarkdownPreviewView(url: url)
                    .id(url)
                    .ignoresSafeArea(edges: .bottom)
                    .navigationTitle(url.deletingPathExtension().lastPathComponent)
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbarTitleMenu { fileTitleMenu(for: url) }
                    .toolbar { markdownToolbar(for: url) }
                    .alert(
                        "Couldn't convert to PDF",
                        isPresented: Binding(
                            get: { conversionError != nil },
                            set: { if !$0 { conversionError = nil } }
                        ),
                        presenting: conversionError
                    ) { _ in
                        Button("OK", role: .cancel) { conversionError = nil }
                    } message: { message in
                        Text(message)
                    }
            default:
                pickPrompt
            }
        } else {
            pickPrompt
        }
    }

    private var pickPrompt: some View {
        ContentUnavailableView(
            "Pick a PDF or note",
            systemImage: "doc.text",
            description: Text("Browse folders on the left and tap a PDF to read it, or a markdown note to preview and convert it to PDF. Draw with Apple Pencil; double-tap the pencil to alternate pen and highlighter; squeeze and hold for the eraser.")
        )
    }

    @ToolbarContentBuilder
    private var readerToolbar: some ToolbarContent {
        // Keep each menu in its OWN ToolbarItem rather than grouped.
        // Grouped items render as a tight cluster on iPad and adjacent
        // icons can get hit-test overlap. Separate ToolbarItems each
        // get a full-size 44pt hit target.
        ToolbarItem(placement: .topBarTrailing) {
            toolMenu
        }

        ToolbarItem(placement: .topBarTrailing) {
            colorMenu
        }

        ToolbarItemGroup(placement: .topBarTrailing) {
            Button {
                readerController.undo()
            } label: {
                Image(systemName: "arrow.uturn.backward")
            }
            .disabled(!readerController.canUndo)
            .help("Undo")

            Button {
                readerController.redo()
            } label: {
                Image(systemName: "arrow.uturn.forward")
            }
            .disabled(!readerController.canRedo)
            .help("Redo")

            if let url = selection, url.pathExtension.lowercased() == "pdf" {
                // ShareLink presents the iOS share sheet on tap. The
                // simultaneousGesture flushes any pending strokes to
                // disk first, so the file the share sheet hands off is
                // the latest version. PDFDocument.write is synchronous
                // and fast, so the save completes before the share
                // sheet finishes rendering.
                ShareLink(item: url) {
                    Image(systemName: "square.and.arrow.up")
                }
                .simultaneousGesture(TapGesture().onEnded {
                    readerController.saveIfNeeded()
                })
                .help("Share")
            }
        }
    }

    private var toolMenu: some View {
        Menu {
            Picker("Tool", selection: $readerController.activeTool) {
                ForEach(Tool.allCases) { tool in
                    Label(tool.displayName, systemImage: tool.symbolName)
                        .tag(tool)
                }
            }
        } label: {
            // Explicit 44pt hit target (Apple HIG minimum) plus
            // `.contentShape(Rectangle())` so taps anywhere in the
            // frame count, not just on the symbol's filled pixels.
            Image(systemName: readerController.activeTool.symbolName)
                .font(.title3)
                .frame(width: 44, height: 44, alignment: .center)
                .contentShape(Rectangle())
        }
        .accessibilityLabel("Tool picker")
    }

    /// Color + width menu. Contents are contextual to the currently
    /// active tool — only the pen pickers when the pen is active,
    /// only the highlighter pickers when the highlighter is active.
    ///
    /// The menu label shows the swatch of the active tool's selected
    /// color so the toolbar reflects what you'd be drawing with. For
    /// the eraser the menu has nothing to configure; the label dims
    /// and the menu is hidden by the toolbar (the ToolbarItem is
    /// gated on `activeTool != .eraser`).
    ///
    /// Asset-catalog images: SwiftUI Menu bridges Pickers to UIMenu,
    /// which only carries a title + UIImage per option — Shape views
    /// and SwiftUI modifiers don't survive the bridge. The pen
    /// `Swatch*` PNGs are rendering-intent "original" so iOS doesn't
    /// tint them; the `Width*` PNGs are template-rendered so menu
    /// rows tint them to match the foreground color.
    @ViewBuilder
    private var colorMenu: some View {
        Menu {
            switch readerController.activeTool {
            case .pen:
                Picker("Color", selection: $readerController.penColor) {
                    ForEach(PenColor.allCases) { color in
                        Label(color.displayName, image: color.swatchAssetName)
                            .tag(color)
                    }
                }
                Picker("Width", selection: $readerController.penWidth) {
                    ForEach(PenWidth.allCases) { width in
                        Label(width.displayName, image: width.iconAssetName)
                            .tag(width)
                    }
                }
            case .highlighter:
                Picker("Color", selection: $readerController.highlightColor) {
                    ForEach(HighlightPenColor.allCases) { color in
                        Label(color.displayName, image: color.swatchAssetName)
                            .tag(color)
                    }
                }
                Picker("Width", selection: $readerController.highlightWidth) {
                    ForEach(HighlightWidth.allCases) { width in
                        Label(width.displayName, image: width.iconAssetName)
                            .tag(width)
                    }
                }
            case .eraser:
                EmptyView()
            }
        } label: {
            colorMenuLabel
                .font(.title3)
                .frame(width: 44, height: 44, alignment: .center)
                .contentShape(Rectangle())
        }
        .accessibilityLabel("Color and width picker")
    }

    @ViewBuilder
    private var colorMenuLabel: some View {
        switch readerController.activeTool {
        case .pen:
            Image(readerController.penColor.swatchAssetName)
                .resizable()
                .scaledToFit()
                .frame(width: 22, height: 22)
        case .highlighter:
            Image(readerController.highlightColor.swatchAssetName)
                .resizable()
                .scaledToFit()
                .frame(width: 22, height: 22)
        case .eraser:
            Image(systemName: "paintpalette")
                .opacity(0.4)
        }
    }

    private func loadRoot() async {
        let url = vaultURL
        let result = await Task.detached(priority: .userInitiated) {
            VaultDirectoryLister.list(url)
        }.value
        rootEntries = result.entries
        rootError = result.error
        rootLoaded = true
        availableRecents = vault.availableRecentVaults()

        // Restore whatever PDF was open last session — only if the user
        // hasn't already picked something in this session. Collapsing
        // the sidebar puts the user straight in the reader; they can
        // re-open the sidebar to browse. The PDF doesn't have to be
        // visible in the (lazy) sidebar tree for the detail view to
        // render — `selection` drives the detail independent of which
        // folders are currently expanded.
        if selection == nil, let restored = vault.resolveLastOpened() {
            pendingRestorePage = vault.resolveLastOpenedPage()
            selection = restored
            columnVisibility = .detailOnly
        }
    }

    @ToolbarContentBuilder
    private func markdownToolbar(for url: URL) -> some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                Task { await convertToPDF(url) }
            } label: {
                if isConverting {
                    ProgressView()
                } else {
                    Label("Convert to PDF", systemImage: "doc.badge.arrow.up")
                }
            }
            .disabled(isConverting)
            .help("Convert to PDF")
        }
        ToolbarItem(placement: .topBarTrailing) {
            ShareLink(item: url) {
                Image(systemName: "square.and.arrow.up")
            }
            .help("Share")
        }
    }

    /// Convert `mdURL` to a PDF in the same directory, save through
    /// `NSFileCoordinator` so File-Provider-backed vaults actually
    /// flush, then refresh the sidebar and select the new PDF so the
    /// user lands in the reader. Collision behaviour is auto-suffix
    /// (see `MarkdownPDFConverter.destinationURL`).
    private func convertToPDF(_ mdURL: URL) async {
        guard !isConverting else { return }
        isConverting = true
        defer { isConverting = false }
        // Error message stays as a String because `any Error` isn't
        // Sendable under Swift 6 strict concurrency — easier to
        // localize once on the worker side than to wrap up an error
        // type that survives the actor hop.
        let outcome: ConvertOutcome = await Task.detached(priority: .userInitiated) {
            do {
                let source = try String(contentsOf: mdURL, encoding: .utf8)
                let destination = MarkdownPDFConverter.destinationURL(for: mdURL)
                let data = MarkdownPDFConverter.convert(source)
                let coordinator = NSFileCoordinator()
                var coordinationError: NSError?
                var writeErrorMessage: String?
                coordinator.coordinate(writingItemAt: destination, options: .forReplacing, error: &coordinationError) { coordinatedURL in
                    do {
                        try data.write(to: coordinatedURL, options: .atomic)
                    } catch {
                        writeErrorMessage = error.localizedDescription
                    }
                }
                if let coordinationError {
                    return .failure(coordinationError.localizedDescription)
                }
                if let writeErrorMessage {
                    return .failure(writeErrorMessage)
                }
                return .success(destination)
            } catch {
                return .failure(error.localizedDescription)
            }
        }.value

        switch outcome {
        case .success(let destination):
            // Re-list just the folder the new PDF landed in so the row
            // appears in place. The rest of the tree (siblings,
            // ancestors, expansion state) stays exactly as the user
            // left it. Then drop into the reader on the new PDF.
            reloader.bump(destination.deletingLastPathComponent())
            selection = destination
        case .failure(let message):
            conversionError = message
        }
    }

    /// Stand-in for `Result<URL, Error>` (see `MarkdownPreviewView` for
    /// the same workaround). `any Error` isn't Sendable under Swift 6
    /// strict concurrency; we ferry a localized message across the
    /// actor boundary instead.
    private enum ConvertOutcome: Sendable {
        case success(URL)
        case failure(String)
    }

    @ViewBuilder
    private func deleteMenuButton(for url: URL) -> some View {
        Button(role: .destructive) {
            pendingDeletion = url
        } label: {
            Label("Delete", systemImage: "trash")
        }
    }

    /// Detail-view title menu. Tapping the file's name in the nav bar
    /// surfaces the full vault-relative path so the user can confirm
    /// which file (of many same-named ones) is open; tapping the menu
    /// item copies the absolute path to the clipboard for paste-into-
    /// other-tools.
    @ViewBuilder
    private func fileTitleMenu(for url: URL) -> some View {
        Button {
            UIPasteboard.general.string = url.path
        } label: {
            Label(displayPath(for: url), systemImage: "doc.on.doc")
        }
    }

    /// Vault-relative path with the vault's display name prefixed, e.g.
    /// `My Vault/Subfolder/note.md`. Falls back to the absolute path if
    /// the file isn't under the current vault (shouldn't happen in
    /// normal use; defensive).
    private func displayPath(for fileURL: URL) -> String {
        let vault = vaultURL.standardizedFileURL.path
        let file = fileURL.standardizedFileURL.path
        guard file.hasPrefix(vault) else { return fileURL.path }
        let trimmed = String(file.dropFirst(vault.count)).drop(while: { $0 == "/" })
        let relative = String(trimmed)
        let vaultName = vaultURL.lastPathComponent
        return relative.isEmpty ? vaultName : "\(vaultName)/\(relative)"
    }

    @ViewBuilder
    private func deleteSwipeButton(for url: URL) -> some View {
        // Same alert path as the context menu — the confirm dialog
        // covers both gestures, so a full swipe still gets the
        // safety prompt.
        Button(role: .destructive) {
            pendingDeletion = url
        } label: {
            Label("Delete", systemImage: "trash")
        }
    }

    /// Remove `url` from disk via NSFileCoordinator (required for
    /// File-Provider-backed vaults to actually propagate the deletion).
    /// Refresh the sidebar afterwards so the row disappears; if the
    /// deleted file was the active selection, drop it so the detail
    /// pane falls back to the picker prompt.
    private func deleteFile(_ url: URL) async {
        let outcome: DeleteOutcome = await Task.detached(priority: .userInitiated) {
            let coordinator = NSFileCoordinator()
            var coordinationError: NSError?
            var removeErrorMessage: String?
            coordinator.coordinate(writingItemAt: url, options: .forDeleting, error: &coordinationError) { coordinatedURL in
                do {
                    try FileManager.default.removeItem(at: coordinatedURL)
                } catch {
                    removeErrorMessage = error.localizedDescription
                }
            }
            if let coordinationError {
                return .failure(coordinationError.localizedDescription)
            }
            if let removeErrorMessage {
                return .failure(removeErrorMessage)
            }
            return .success
        }.value

        switch outcome {
        case .success:
            // Close the document if it happened to be open. Use
            // `standardizedFileURL` for the comparison because the row's
            // URL (from FileManager.contentsOfDirectory) and the
            // selection (from a NavigationLink value) may differ in
            // trailing slash or symlink-resolution detail.
            if selection?.standardizedFileURL == url.standardizedFileURL {
                readerController.saveIfNeeded()
                selection = nil
            }
            // Re-list the parent folder so the row disappears in place.
            reloader.bump(url.deletingLastPathComponent())
        case .failure(let message):
            deletionError = message
        }
    }

    private enum DeleteOutcome: Sendable {
        case success
        case failure(String)
    }
}
