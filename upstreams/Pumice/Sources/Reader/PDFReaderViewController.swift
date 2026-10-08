import CryptoKit
import PDFKit
import PumiceCore
import UIKit

/// PDFView's inner scrollview isn't part of its public API. The
/// Cookiezby working reference exposes it via subview enumeration so
/// it can disable scrolling while editing. We use the same trick.
private extension PDFView {
    var privateScrollView: UIScrollView? {
        subviews.first as? UIScrollView
    }
}

/// PDFPage subclass returned by `PDFDocumentDelegate.classForPage()`.
/// Cookiezby's working `PDFPageOverlayViewProvider` reference uses a
/// custom subclass; we mirror that pattern in case PDFKit requires
/// it (currently empty, just a marker class).
final class PumicePDFPage: PDFPage {}

/// Standalone `PDFDocumentDelegate` so PDFKit can call `classForPage()`
/// from background queues without tripping Swift 6's MainActor
/// concurrency assertion. The view controller is implicitly
/// `@MainActor` (it's a UIViewController); routing the delegate
/// through `self` crashed in `_dispatch_assert_queue_fail`.
final class PumicePDFDocumentDelegate: NSObject, @unchecked Sendable, PDFDocumentDelegate {
    func classForPage() -> AnyClass {
        return PumicePDFPage.self
    }
}

private struct SidecarPoint: Codable {
    let x: Double
    let y: Double
    let pressure: Double
    let t_ms: Int
}

private struct SidecarStroke: Codable {
    let stroke_id: String
    let tool: String
    let color: String
    let width_pt: Double
    let points: [SidecarPoint]
}

private struct SidecarInkPage: Codable {
    let annotation_id: String
    let page_index: Int
    var strokes: [SidecarStroke]
}

private struct SidecarRect: Codable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

private struct SidecarHighlight: Codable {
    let annotation_id: String
    let page_index: Int
    let color: String
    let text: String
    let rects: [SidecarRect]
}

private struct ErasedHighlightRecord {
    let annotation: PDFAnnotation
    let annotationID: UUID?
    let draft: Data?
}

private struct PumiceReaderSidecar: Codable {
    let schema_version: Int
    let source_sha256: String
    var ink_pages: [SidecarInkPage]
    var highlights: [SidecarHighlight]
    var last_page_index: Int?
}

/// Standalone `PDFPageOverlayViewProvider`. Same motivation as
/// `PumicePDFDocumentDelegate`: PDFKit may invoke the provider's
/// methods from a non-main queue, and a `@MainActor` view controller
/// would silently get its calls dropped (or trip a concurrency
/// assert). The working Cookiezby reference uses a separate provider
/// object too; we mirror that pattern.
///
/// The provider owns the per-page canvas/path state. The view
/// controller pulls from it on save and pushes hydrated paths into
/// it on load.
final class PumiceOverlayProvider: NSObject, @unchecked Sendable {
    private let lock = NSLock()
    private var strokesForPage: [PDFPage: [StrokeRecord]] = [:]
    private var canvasByPage: [PDFPage: PumiceCanvasView] = [:]
    private var canvasSizeForPage: [PDFPage: CGSize] = [:]

    @MainActor var onCanvasReady: ((PDFPage, PumiceCanvasView, CGSize, CGSize?) -> Void)?

    /// Current tool settings. Applied to every new canvas as it is
    /// created, and pushed onto live canvases via the setters below
    /// when the user changes them from the toolbar. Pen + highlighter
    /// styles are tracked separately so switching tools restores each
    /// tool's last choice.
    @MainActor private var mode: PumiceCanvasView.Mode = .pen
    @MainActor private var penColor: UIColor = .black
    @MainActor private var penWidth: CGFloat = 3
    @MainActor private var highlightColor: UIColor = UIColor(red: 1.0, green: 0.92, blue: 0.23, alpha: 1.0)
    @MainActor private var highlightWidth: CGFloat = 14

    /// Called whenever a new pen stroke is finished on any canvas.
    /// Receives the page and the freshly committed record so the
    /// controller can register an undo action for it.
    var onPathFinished: (@MainActor (PDFPage, StrokeRecord) -> Void)?

    /// Called during an eraser gesture on every `touchesMoved`,
    /// carrying the freshly-traversed segment in canvas coords. The
    /// controller uses this to remove `/Highlight` annotations the
    /// gesture crosses in real time.
    var onEraserSegment: (@MainActor (PDFPage, CGPoint, CGPoint) -> Void)?

    /// Called when an eraser gesture finishes on a canvas, carrying
    /// every stroke the gesture rubbed out. Highlights removed during
    /// the gesture were already taken care of via `onEraserSegment`;
    /// the controller pairs them into a single undo entry.
    var onEraserStroke: (@MainActor (PDFPage, [StrokeRecord]) -> Void)?

    /// Called when a highlighter gesture finishes on a canvas, carrying
    /// the page and the first/last canvas-space points. The controller
    /// converts to PDF user space and asks PumiceCore to snap to the
    /// underlying text.
    var onHighlightStrokeFinished: (@MainActor (PDFPage, CGPoint, CGPoint) -> Void)?

    @MainActor func setStrokes(_ strokes: [StrokeRecord], for page: PDFPage) {
        lock.lock()
        strokesForPage[page] = strokes
        let canvas = canvasByPage[page]
        lock.unlock()
        canvas?.setStrokes(strokes)
    }

    func strokes(for page: PDFPage) -> [StrokeRecord]? {
        lock.lock(); defer { lock.unlock() }
        return strokesForPage[page]
    }

    func allStrokes() -> [PDFPage: [StrokeRecord]] {
        lock.lock(); defer { lock.unlock() }
        return strokesForPage
    }

    func canvasSize(for page: PDFPage) -> CGSize? {
        lock.lock(); defer { lock.unlock() }
        return canvasSizeForPage[page]
    }

    @MainActor func activeCanvas(for page: PDFPage) -> PumiceCanvasView? {
        lock.lock(); defer { lock.unlock() }
        return canvasByPage[page]
    }

    func reset() {
        lock.lock(); defer { lock.unlock() }
        strokesForPage.removeAll()
        canvasByPage.removeAll()
        canvasSizeForPage.removeAll()
    }

    /// Sync any currently-active canvases' drawings back into the
    /// stroke store. Call from save() before writing the document, to
    /// capture drawings on pages that haven't scrolled out of view.
    @MainActor func syncActiveCanvases() {
        lock.lock(); defer { lock.unlock() }
        for (page, canvas) in canvasByPage {
            strokesForPage[page] = canvas.strokes
        }
    }

    /// Append a stroke to a page's list and mirror the update on the
    /// active canvas if one is on-screen. Used by undo/redo — stroke
    /// creation goes through the canvas's own gesture path.
    @MainActor func appendStroke(_ stroke: StrokeRecord, to page: PDFPage) {
        lock.lock()
        var existing = strokesForPage[page] ?? []
        existing.append(stroke)
        strokesForPage[page] = existing
        let activeCanvas = canvasByPage[page]
        lock.unlock()
        activeCanvas?.setStrokes(existing)
    }

    /// Remove a specific stroke (matched by path object identity) from
    /// a page's list and refresh the active canvas if it's on-screen.
    @MainActor func removeStroke(_ stroke: StrokeRecord, from page: PDFPage) {
        lock.lock()
        var existing = strokesForPage[page] ?? []
        existing.removeAll { $0.id == stroke.id }
        strokesForPage[page] = existing
        let activeCanvas = canvasByPage[page]
        lock.unlock()
        activeCanvas?.setStrokes(existing)
    }

    @MainActor func setPenColor(_ color: UIColor) {
        penColor = color
        lock.lock()
        let canvases = Array(canvasByPage.values)
        lock.unlock()
        for canvas in canvases { canvas.penColor = color }
    }

    @MainActor func setPenWidth(_ width: CGFloat) {
        penWidth = width
        lock.lock()
        let canvases = Array(canvasByPage.values)
        lock.unlock()
        for canvas in canvases { canvas.penWidth = width }
    }

    @MainActor func setMode(_ newMode: PumiceCanvasView.Mode) {
        mode = newMode
        lock.lock()
        let canvases = Array(canvasByPage.values)
        lock.unlock()
        for canvas in canvases { canvas.mode = newMode }
    }

    @MainActor func setHighlightColor(_ color: UIColor) {
        highlightColor = color
        lock.lock()
        let canvases = Array(canvasByPage.values)
        lock.unlock()
        for canvas in canvases { canvas.highlightColor = color }
    }

    @MainActor func setHighlightWidth(_ width: CGFloat) {
        highlightWidth = width
        lock.lock()
        let canvases = Array(canvasByPage.values)
        lock.unlock()
        for canvas in canvases { canvas.highlightWidth = width }
    }

    @MainActor var currentPenColor: UIColor { penColor }
    @MainActor var currentPenWidth: CGFloat { penWidth }
    @MainActor var currentMode: PumiceCanvasView.Mode { mode }
}

extension PumiceOverlayProvider: @preconcurrency PDFPageOverlayViewProvider {
    @MainActor
    func pdfView(_ view: PDFView, overlayViewFor page: PDFPage) -> UIView? {
        let canvas = PumiceCanvasView()
        canvas.penColor = penColor
        canvas.penWidth = penWidth
        canvas.highlightColor = highlightColor
        canvas.highlightWidth = highlightWidth
        canvas.mode = mode
        let existing: [StrokeRecord]? = {
            lock.lock(); defer { lock.unlock() }
            return strokesForPage[page]
        }()
        if let existing { canvas.setStrokes(existing) }
        canvas.onPathFinished = { [weak self, weak page] stroke in
            guard let self, let page else { return }
            self.lock.lock()
            self.strokesForPage[page] = canvas.strokes
            self.lock.unlock()
            DispatchQueue.main.async { [weak self] in
                self?.onPathFinished?(page, stroke)
            }
        }
        canvas.onEraserSegment = { [weak self, weak page] from, to in
            guard let self, let page else { return }
            DispatchQueue.main.async { [weak self] in
                self?.onEraserSegment?(page, from, to)
            }
        }
        canvas.onEraserStroke = { [weak self, weak page] removedBatch in
            guard let self, let page else { return }
            // Canvas has already removed these strokes from its own
            // list. Mirror that into our authoritative store so save
            // and re-display stay in sync.
            self.lock.lock()
            self.strokesForPage[page] = canvas.strokes
            self.lock.unlock()
            DispatchQueue.main.async { [weak self] in
                self?.onEraserStroke?(page, removedBatch)
            }
        }
        canvas.onHighlightStrokeFinished = { [weak self, weak page] first, last in
            guard let self, let page else { return }
            DispatchQueue.main.async { [weak self] in
                self?.onHighlightStrokeFinished?(page, first, last)
            }
        }
        lock.lock()
        canvasByPage[page] = canvas
        lock.unlock()
        canvas.onBoundsChanged = { [weak self, weak page, weak canvas] size in
            guard let self, let page, let canvas else { return }
            self.lock.lock()
            let previousSize = self.canvasSizeForPage[page]
            self.canvasSizeForPage[page] = size
            self.lock.unlock()
            Task { @MainActor [weak self, weak page, weak canvas] in
                guard let self, let page, let canvas else { return }
                self.onCanvasReady?(page, canvas, size, previousSize)
            }
        }

        // Same PDFPageView.userInteractionEnabled trick as before;
        // the overlay won't see touches without it.
        for subview in view.documentView?.subviews ?? [] {
            if NSStringFromClass(type(of: subview)) == "PDFPageView" {
                subview.isUserInteractionEnabled = true
            }
        }
        return canvas
    }

    @MainActor
    func pdfView(_ pdfView: PDFView, willEndDisplayingOverlayView overlayView: UIView, for page: PDFPage) {
        guard let canvas = overlayView as? PumiceCanvasView else { return }
        lock.lock()
        strokesForPage[page] = canvas.strokes
        canvasSizeForPage[page] = canvas.bounds.size
        canvasByPage.removeValue(forKey: page)
        lock.unlock()
    }
}

/// PDFView host that uses Apple's `PDFPageOverlayViewProvider` (iOS 16+)
/// to install a `PumiceCanvasView` per PDF page. Each canvas owns its
/// own stroke list (in canvas coords, UIKit Y-down). PDFKit auto-sizes
/// the overlay to the page, so canvas coordinates ARE page-local
/// pixels and the strokes scroll/zoom with their page for free.
///
/// We deliberately do NOT use PencilKit. Multiple iterations against
/// iPadOS 26 hardware showed that `PKCanvasView` with
/// `drawingPolicy = .pencilOnly` never activates its gesture pipeline
/// inside PDFKit's overlay — the pen falls through to PDFView's
/// scroll regardless of markup mode, first responder, or
/// `userInteractionEnabled` on the underlying `PDFPageView`. Going
/// to a plain `UIGestureRecognizer` subclass that explicitly accepts
/// only `.pencil` touches gives deterministic behavior.
///
/// New strokes and Pumice highlights are stored in a separate Application
/// Support sidecar. The source PDF is never written by this controller.
/// Ink points are converted through MnemosyneGeometry into unrotated PDF
/// CropBox coordinates before serialization and mapped back when a page
/// overlay is created. Search, selection, and PDF navigation remain PDFKit
/// operations and do not wait for network activity.
final class PDFReaderViewController: UIViewController {
    private let pdfView = PDFView()
    private var pdfURL: URL?
    private var needsSave = false
    private var positionNeedsSave = false
    private var sidecarURL: URL?
    private var sidecar: PumiceReaderSidecar?
    private var sourceSHA256: String?
    private var pageInkAnnotationIDs: [Int: UUID] = [:]
    private var strokeAnnotationIDs: [UUID: UUID] = [:]
    private var highlightIDs: [ObjectIdentifier: UUID] = [:]
    private var sidecarOnlyHighlightIDs: Set<UUID> = []
    private var contractAnnotationDrafts: [UUID: Data] = [:]
    private var handledCanvasSizes: [ObjectIdentifier: CGSize] = [:]
    private var managedAnnotationIDs: Set<ObjectIdentifier> = []
    private var currentPageIndex = 0
    private var documentIdentifier: UUID?
    private var documentVersionID: String?

    private let overlayProvider = PumiceOverlayProvider()

    private let _undoManager = UndoManager()
    private let documentDelegate = PumicePDFDocumentDelegate()

    weak var controller: PDFReaderController?

    override var undoManager: UndoManager? { _undoManager }

    var canUndoChange: Bool { _undoManager.canUndo }
    var canRedoChange: Bool { _undoManager.canRedo }

    /// Fired when the user single-taps the PDF detail with a finger
    /// (Pencil drawing is excluded by touchType). VaultBrowserView
    /// uses this to collapse the sidebar to `.detailOnly` once the
    /// reader is engaged.
    var onSidebarTap: (() -> Void)?

    /// Fired whenever the user scrolls to a new page. Reports the
    /// zero-indexed page number so the browser can persist a restore
    /// point in `VaultStore`.
    var onPageChanged: ((Int) -> Void)?
    var onLocalAnnotationEdit: (@MainActor (MnemosyneLocalAnnotationEdit) throws -> Void)?
    var onAnnotationSuggestion: ((Data) -> Void)?
    var onTextSelectionChanged: (@MainActor () -> Void)?

    /// Optional restore target: when set in `load(url:restorePageIndex:)`,
    /// the document is scrolled to this page after parsing.
    private var pendingRestorePage: Int?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        configurePDFView()

        // Wire the overlay provider BEFORE any document is loaded.
        // Matches the working Cookiezby reference; setting it after
        // pdfView.document had no effect in past iterations.
        pdfView.pageOverlayViewProvider = overlayProvider
        pdfView.isInMarkupMode = true
        overlayProvider.onPathFinished = { [weak self] page, stroke in
            guard let self else { return }
            self.emitInkEdit(stroke, on: page, operation: .upsert)
            self.registerUndoForAddedStroke(stroke: stroke, on: page)
            self.needsSave = true
            self.controller?.refreshState()
            self.scheduleDebouncedSave()
        }
        overlayProvider.onEraserSegment = { [weak self] page, from, to in
            guard let self else { return }
            self.handleEraserSegment(from: from, to: to, on: page)
        }
        overlayProvider.onEraserStroke = { [weak self] page, removedBatch in
            guard let self else { return }
            self.handleEraserSweep(removedStrokes: removedBatch, on: page)
            self.scheduleDebouncedSave()
        }
        overlayProvider.onHighlightStrokeFinished = { [weak self] page, first, last in
            guard let self else { return }
            self.handleHighlightStrokeFinished(first: first, last: last, on: page)
        }
        overlayProvider.onCanvasReady = { [weak self] page, canvas, size, previousSize in
            self?.restoreSidecarStrokes(on: page, canvas: canvas, size: size, previousSize: previousSize)
        }

        installUndoRedoGestures()
        installPencilInteraction()
        installFingerTapGestures()

        // Observe page changes so the browser can persist the user's
        // current reading position. PDFViewPageChanged fires whenever
        // the visible page (the one most-on-screen) changes.
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handlePDFViewPageChanged),
            name: .PDFViewPageChanged,
            object: pdfView
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handlePDFViewSelectionChanged(_:)),
            name: .PDFViewSelectionChanged,
            object: pdfView
        )
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        overlayProvider.syncActiveCanvases()
        saveIfNeeded()
    }

    func load(url: URL, restorePageIndex: Int? = nil) {
        // Force viewDidLoad to run BEFORE we set the document.
        // SwiftUI's PDFReaderView calls load(url:) inside
        // makeUIViewController, before the view is in a hierarchy —
        // so without this nudge, viewDidLoad runs LATER and the
        // pageOverlayViewProvider gets wired AFTER PDFKit has already
        // parsed the document and decided it doesn't need overlays.
        // Touching `view` triggers the view-loading lifecycle
        // synchronously and runs viewDidLoad in line.
        _ = view

        pdfURL = url
        needsSave = false
        positionNeedsSave = false
        sidecar = loadSidecar(for: url)
        sourceSHA256 = sidecar?.source_sha256 ?? (try? Self.sha256(of: url))
        sidecarURL = try? Self.sidecarURL(for: url)
        pageInkAnnotationIDs = Dictionary(uniqueKeysWithValues: (sidecar?.ink_pages ?? []).compactMap {
            guard let id = UUID(uuidString: $0.annotation_id) else { return nil }
            return ($0.page_index, id)
        })
        strokeAnnotationIDs.removeAll()
        highlightIDs.removeAll()
        sidecarOnlyHighlightIDs.removeAll()
        contractAnnotationDrafts.removeAll()
        managedAnnotationIDs.removeAll()
        handledCanvasSizes.removeAll()
        currentPageIndex = 0
        let restoreIndex = restorePageIndex ?? sidecar?.last_page_index
        pendingRestorePage = restoreIndex
        _undoManager.removeAllActions()
        overlayProvider.reset()
        controller?.refreshState()
        saveDebounceTimer?.invalidate()
        saveDebounceTimer = nil

        guard let document = PDFDocument(url: url) else { return }
        document.delegate = documentDelegate
        pdfView.document = document

        // Scroll to the remembered page, if any. Defer to the next
        // run-loop turn so PDFKit has finished laying out the document
        // — calling `go(to:)` inside `pdfView.document =` doesn't
        // settle on iOS 26.
        if let index = restoreIndex, index > 0,
           index < document.pageCount,
           let page = document.page(at: index) {
            DispatchQueue.main.async { [weak self] in
                self?.pdfView.go(to: page)
            }
        }

        // Hydrate per-page strokes from any /Ink annotations already in
        // the file. We strip them from the model so they don't double-
        // up with what the canvas renders. Each annotation's color and
        // border width are preserved so re-saves don't flatten styling
        // back to a single palette.
        for i in 0..<document.pageCount {
            guard let page = document.page(at: i) else { continue }
            restoreSidecarHighlights(on: page, pageIndex: i)
        }
    }

    func loadIfNeeded(url: URL, restorePageIndex: Int? = nil) {
        guard pdfURL?.standardizedFileURL != url.standardizedFileURL else { return }
        load(url: url, restorePageIndex: restorePageIndex)
    }

    func saveIfNeeded() {
        guard (needsSave || positionNeedsSave), pdfURL != nil, pdfView.document != nil else { return }
        overlayProvider.syncActiveCanvases()
        do {
            guard let destination = sidecarURL else { throw CocoaError(.fileNoSuchFile) }
            let value = try makeSidecarSnapshot()
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            try encoder.encode(value).write(to: destination, options: .atomic)
            sidecar = value
            sourceSHA256 = value.source_sha256
            needsSave = false
            positionNeedsSave = false
            lastLocalSaveError = nil
        } catch {
            lastLocalSaveError = error
        }
        saveDebounceTimer?.invalidate()
        saveDebounceTimer = nil
    }

    private(set) var lastLocalSaveError: Error?

    func setMnemosyneIdentity(documentID: UUID, versionID: String) {
        documentIdentifier = documentID
        documentVersionID = versionID
    }

    func load(url: URL, restoring context: Data?, annotations: [Data]) throws {
        let contextObject = context.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
        let restoreIndex = contextObject?["page_index"] as? Int
        load(url: url, restorePageIndex: restoreIndex)
        try replaceAnnotations(annotations)
    }

    func readerContextData() throws -> Data {
        guard let document = pdfView.document,
              let documentIdentifier,
              let documentVersionID,
              let page = pdfView.currentPage else {
            throw MnemosyneReaderError.cacheMissing
        }
        let index = document.index(for: page)
        guard index >= 0, index < document.pageCount else { throw MnemosyneReaderError.documentMismatch }
        let cropBox = page.bounds(for: .cropBox)
        let pageRectInView = pdfView.convert(cropBox, from: page)
        let visibleRectInView = pdfView.bounds.intersection(pageRectInView)
        let convertedViewport = visibleRectInView.isNull || visibleRectInView.isEmpty
            ? cropBox
            : pdfView.convert(visibleRectInView, to: page).intersection(cropBox)
        let viewport = convertedViewport.isNull || convertedViewport.isEmpty ? cropBox : convertedViewport
        let context: [String: Any] = [
            "document_id": documentIdentifier.uuidString.lowercased(),
            "version_id": documentVersionID,
            "page_index": index,
            "viewport_rect": [Double(viewport.minX), Double(viewport.minY),
                              Double(viewport.width), Double(viewport.height)],
            "selection": NSNull(),
            "content_language": "und",
            "response_language": "ko"
        ]
        return try JSONSerialization.data(withJSONObject: context, options: [.sortedKeys])
    }

    @objc private func handlePDFViewSelectionChanged(_ notification: Notification) {
        onTextSelectionChanged?()
    }

    func selectedText() throws -> String? {
        guard pdfView.document != nil else { throw MnemosyneReaderError.cacheMissing }
        guard let selection = pdfView.currentSelection?.string,
              !selection.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
        return selection
    }

    func search(text: String) throws -> [Data] {
        guard let document = pdfView.document else { throw MnemosyneReaderError.cacheMissing }
        let query = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return [] }
        let selections = document.findString(query, withOptions: [.caseInsensitive, .diacriticInsensitive])
        return try selections.compactMap { selection in
            guard let page = selection.pages.first,
                  let text = selection.string, !text.isEmpty else { return nil }
            let bounds = selection.bounds(for: page)
            let value: [String: Any] = [
                "page_index": document.index(for: page),
                "page_label": page.label ?? String(document.index(for: page) + 1),
                "text": text,
                "rect": [Double(bounds.minX), Double(bounds.minY),
                         Double(bounds.width), Double(bounds.height)]
            ]
            return try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        }
    }

    func tableOfContentsData() throws -> Data {
        guard let document = pdfView.document else { throw MnemosyneReaderError.cacheMissing }
        func item(_ outline: PDFOutline) -> [String: Any] {
            let pageIndex = outline.destination?.page.map { document.index(for: $0) }
            return [
                "title": outline.label ?? "",
                "page_index": pageIndex.map { $0 as Any } ?? NSNull(),
                "children": (0..<outline.numberOfChildren).map { item(outline.child(at: $0)!) }
            ]
        }
        let children: [[String: Any]] = (0..<(document.outlineRoot?.numberOfChildren ?? 0)).compactMap {
            document.outlineRoot?.child(at: $0).map(item)
        }
        return try JSONSerialization.data(withJSONObject: ["items": children], options: [.sortedKeys])
    }

    func goToPage(index: Int) throws {
        guard let document = pdfView.document,
              index >= 0, index < document.pageCount,
              let page = document.page(at: index) else {
            throw MnemosyneReaderError.malformedContractData
        }
        pendingRestorePage = nil
        currentPageIndex = index
        pdfView.go(to: page)
        positionNeedsSave = true
        scheduleDebouncedSave()
        onPageChanged?(index)
    }

    func applyReaderEvent(_ event: Data) throws {
        guard let document = pdfView.document,
              let documentIdentifier, let documentVersionID,
              let value = try JSONSerialization.jsonObject(with: event) as? [String: Any],
              value["contract_version"] as? String == "0.1.0",
              let type = value["type"] as? String,
              let payload = value["payload"] as? [String: Any] else {
            throw MnemosyneReaderError.malformedContractData
        }

        if type == "reader.annotate" {
            guard payload["requires_confirmation"] as? Bool == true,
                  UUID(uuidString: payload["citation_id"] as? String ?? "") != nil,
                  UUID(uuidString: payload["suggested_mutation_id"] as? String ?? "") != nil,
                  let annotation = payload["annotation"] as? [String: Any],
                  annotation["document_id"] as? String == documentIdentifier.uuidString.lowercased(),
                  annotation["version_id"] as? String == documentVersionID else {
                throw MnemosyneReaderError.documentMismatch
            }
            onAnnotationSuggestion?(event)
            return
        }

        guard let target = payload["target"] as? [String: Any],
              target["document_id"] as? String == documentIdentifier.uuidString.lowercased(),
              target["version_id"] as? String == documentVersionID,
              let pageIndex = target["page_index"] as? Int,
              pageIndex >= 0, pageIndex < document.pageCount,
              let page = document.page(at: pageIndex) else {
            throw MnemosyneReaderError.documentMismatch
        }
        let cropBox = page.bounds(for: .cropBox)

        if type == "reader.goto" {
            guard UUID(uuidString: payload["citation_id"] as? String ?? "") != nil,
                  let position = payload["position"] as? [NSNumber], position.count == 2 else {
                throw MnemosyneReaderError.malformedContractData
            }
            let point = CGPoint(x: CGFloat(truncating: position[0]), y: CGFloat(truncating: position[1]))
            guard point.x.isFinite, point.y.isFinite, cropBox.contains(point) else {
                throw MnemosyneReaderError.documentMismatch
            }
            pendingRestorePage = nil
            currentPageIndex = pageIndex
            pdfView.go(to: PDFDestination(page: page, at: point))
            positionNeedsSave = true
            scheduleDebouncedSave()
            onPageChanged?(pageIndex)
            return
        }

        guard ["reader.flash", "reader.highlight"].contains(type),
              payload["persistent"] as? Bool == false,
              let citationID = UUID(uuidString: payload["citation_id"] as? String ?? ""),
              let ttl = payload["ttl_ms"] as? Int, (100...10_000).contains(ttl),
              let rectValues = payload["rects"] as? [[NSNumber]], !rectValues.isEmpty else {
            throw MnemosyneReaderError.malformedContractData
        }
        let color = UIColor.systemYellow.withAlphaComponent(0.45)
        var temporary: [PDFAnnotation] = []
        for values in rectValues {
            guard values.count == 4 else { throw MnemosyneReaderError.malformedContractData }
            let rect = CGRect(x: CGFloat(truncating: values[0]), y: CGFloat(truncating: values[1]),
                              width: CGFloat(truncating: values[2]), height: CGFloat(truncating: values[3]))
            guard rect.width > 0, rect.height > 0,
                  rect.minX >= cropBox.minX, rect.minY >= cropBox.minY,
                  rect.maxX <= cropBox.maxX, rect.maxY <= cropBox.maxY else {
                throw MnemosyneReaderError.documentMismatch
            }
            let highlight = PumiceHighlightAnnotation(quads: [Quad(rect: rect)], color: color, bounds: rect)
            page.addAnnotation(highlight)
            temporary.append(highlight)
        }
        _ = citationID
        forcePDFPageRedraw()
        Task { @MainActor [weak self, weak page] in
            try? await Task.sleep(nanoseconds: UInt64(ttl) * 1_000_000)
            guard let self, let page else { return }
            for annotation in temporary { page.removeAnnotation(annotation) }
            self.forcePDFPageRedraw()
        }
    }

    func replaceAnnotations(_ annotations: [Data]) throws {
        guard let document = pdfView.document,
              let documentIdentifier, let documentVersionID,
              let digest = sourceSHA256 else { throw MnemosyneReaderError.cacheMissing }

        var inkByPage: [Int: SidecarInkPage] = [:]
        var contractHighlights: [SidecarHighlight] = []
        var textAnnotations: [(PDFPage, PDFAnnotation)] = []
        var annotationDrafts: [UUID: Data] = [:]
        var contractAnnotationIDs: Set<UUID> = []
        var strokeAnnotationIDs: [UUID: UUID] = [:]
        for data in annotations {
            guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  object["document_id"] as? String == documentIdentifier.uuidString.lowercased(),
                  object["version_id"] as? String == documentVersionID,
                  let annotationID = UUID(uuidString: object["annotation_id"] as? String ?? ""),
                  let pageIndex = object["page_index"] as? Int,
                  pageIndex >= 0, pageIndex < document.pageCount,
                  let kind = object["kind"] as? String else {
                throw MnemosyneReaderError.documentMismatch
            }
            if object["deleted"] as? Bool == true { continue }
            contractAnnotationIDs.insert(annotationID)
            guard let page = document.page(at: pageIndex),
                  let payload = object["payload"] as? [String: Any] else {
                throw MnemosyneReaderError.malformedContractData
            }
            let draftObject: [String: Any] = [
                "annotation_id": annotationID.uuidString.lowercased(),
                "document_id": documentIdentifier.uuidString.lowercased(),
                "version_id": documentVersionID,
                "page_index": pageIndex,
                "kind": kind,
                "payload": payload
            ]
            annotationDrafts[annotationID] = try JSONSerialization.data(
                withJSONObject: draftObject, options: [.sortedKeys]
            )

            switch kind {
            case "ink":
                guard let strokes = payload["strokes"] as? [[String: Any]], !strokes.isEmpty else {
                    throw MnemosyneReaderError.malformedContractData
                }
                let strokeData = try JSONSerialization.data(withJSONObject: strokes, options: [.sortedKeys])
                let decoded = try JSONDecoder().decode([SidecarStroke].self, from: strokeData)
                for stroke in decoded {
                    if let strokeID = UUID(uuidString: stroke.stroke_id) {
                        strokeAnnotationIDs[strokeID] = annotationID
                    }
                }
                if let existing = inkByPage[pageIndex] {
                    inkByPage[pageIndex] = SidecarInkPage(annotation_id: existing.annotation_id,
                                                         page_index: pageIndex,
                                                         strokes: existing.strokes + decoded)
                } else {
                    inkByPage[pageIndex] = SidecarInkPage(annotation_id: annotationID.uuidString.lowercased(),
                                                         page_index: pageIndex, strokes: decoded)
                }
            case "highlight":
                guard let payloadAnchor = payload["anchor"] as? [String: Any],
                      let rects = payloadAnchor["rects"] as? [[NSNumber]],
                      let color = payload["color"] as? String else {
                    throw MnemosyneReaderError.malformedContractData
                }
                let quote = payloadAnchor["quote"] as? String ?? ""
                let parsedRects = rects.compactMap { values -> SidecarRect? in
                    guard values.count == 4 else { return nil }
                    return SidecarRect(x: Double(truncating: values[0]), y: Double(truncating: values[1]),
                                       width: Double(truncating: values[2]), height: Double(truncating: values[3]))
                }
                let cropBox = page.bounds(for: .cropBox)
                guard parsedRects.count == rects.count,
                      parsedRects.allSatisfy({ rect in
                          rect.width.isFinite && rect.height.isFinite && rect.width > 0 && rect.height > 0 &&
                              rect.x >= Double(cropBox.minX) && rect.y >= Double(cropBox.minY) &&
                              rect.x + rect.width <= Double(cropBox.maxX) &&
                              rect.y + rect.height <= Double(cropBox.maxY)
                      }) else { throw MnemosyneReaderError.documentMismatch }
                contractHighlights.append(SidecarHighlight(annotation_id: annotationID.uuidString.lowercased(),
                                                           page_index: pageIndex, color: color,
                                                           text: quote, rects: parsedRects))
            case "note":
                guard let position = payload["position"] as? [NSNumber], position.count == 2,
                      let body = payload["body"] as? String else {
                    throw MnemosyneReaderError.malformedContractData
                }
                let point = CGPoint(x: CGFloat(truncating: position[0]), y: CGFloat(truncating: position[1]))
                let box = page.bounds(for: .cropBox)
                let width = min(160, box.width)
                let height = min(56, box.height)
                let bounds = CGRect(x: min(max(point.x, box.minX), box.maxX - width),
                                    y: min(max(point.y, box.minY), box.maxY - height),
                                    width: width, height: height)
                let note = PDFAnnotation(bounds: bounds, forType: .freeText, withProperties: nil)
                note.contents = body
                note.font = UIFont.systemFont(ofSize: 12)
                note.fontColor = .label
                note.userName = annotationID.uuidString.lowercased()
                textAnnotations.append((page, note))
            case "bookmark":
                let label = payload["label"] as? String ?? ""
                let cropBox = page.bounds(for: .cropBox)
                let markerSize = min(20, min(cropBox.width, cropBox.height))
                guard markerSize > 0 else { throw MnemosyneReaderError.documentMismatch }
                let marker = PDFAnnotation(
                    bounds: CGRect(x: cropBox.minX, y: cropBox.maxY - markerSize,
                                   width: markerSize, height: markerSize),
                    forType: .text, withProperties: nil
                )
                marker.contents = label.isEmpty ? "Bookmark" : label
                marker.userName = annotationID.uuidString.lowercased()
                textAnnotations.append((page, marker))
            default:
                throw MnemosyneReaderError.malformedContractData
            }
        }

        var retainedSidecarHighlights: [SidecarHighlight] = []
        for index in 0..<document.pageCount {
            guard let page = document.page(at: index) else { continue }
            for annotation in page.annotations where annotation.type == "Highlight" {
                guard let id = highlightIDs[ObjectIdentifier(annotation)],
                      sidecarOnlyHighlightIDs.contains(id), !contractAnnotationIDs.contains(id) else { continue }
                let rects = Self.absoluteQuadRects(of: annotation).filter { $0.width > 0 && $0.height > 0 }
                guard !rects.isEmpty else { continue }
                retainedSidecarHighlights.append(SidecarHighlight(
                    annotation_id: id.uuidString.lowercased(), page_index: index,
                    color: Self.rgbaHex(annotation.color), text: annotation.contents ?? "",
                    rects: rects.map {
                        SidecarRect(x: Double($0.minX), y: Double($0.minY),
                                    width: Double($0.width), height: Double($0.height))
                    }
                ))
            }
        }

        for index in 0..<document.pageCount {
            guard let page = document.page(at: index) else { continue }
            for annotation in page.annotations where managedAnnotationIDs.contains(ObjectIdentifier(annotation)) {
                page.removeAnnotation(annotation)
            }
        }
        managedAnnotationIDs.removeAll()
        highlightIDs.removeAll()
        sidecarOnlyHighlightIDs.removeAll()
        for index in 0..<document.pageCount {
            guard let page = document.page(at: index) else { continue }
            overlayProvider.setStrokes([], for: page)
            if let canvas = overlayProvider.activeCanvas(for: page) {
                handledCanvasSizes.removeValue(forKey: ObjectIdentifier(canvas))
                canvas.setStrokes([])
            }
        }

        sidecar = PumiceReaderSidecar(schema_version: 1, source_sha256: digest,
                                      ink_pages: inkByPage.values.sorted { $0.page_index < $1.page_index },
                                      highlights: retainedSidecarHighlights,
                                      last_page_index: sidecar?.last_page_index)
        contractAnnotationDrafts = annotationDrafts
        self.strokeAnnotationIDs = strokeAnnotationIDs
        pageInkAnnotationIDs = Dictionary(uniqueKeysWithValues: inkByPage.values.compactMap {
            guard let id = UUID(uuidString: $0.annotation_id) else { return nil }
            return ($0.page_index, id)
        })
        for index in 0..<document.pageCount {
            guard let page = document.page(at: index) else { continue }
            restoreSidecarHighlights(on: page, pageIndex: index)
            if let canvas = overlayProvider.activeCanvas(for: page),
               let size = overlayProvider.canvasSize(for: page) {
                handledCanvasSizes.removeValue(forKey: ObjectIdentifier(canvas))
                restoreSidecarStrokes(on: page, canvas: canvas, size: size, previousSize: nil)
            }
        }
        for index in 0..<document.pageCount {
            guard let page = document.page(at: index) else { continue }
            restoreHighlights(contractHighlights.filter { $0.page_index == index }, on: page,
                              pageIndex: index, sidecarOnly: false)
        }
        for (page, annotation) in textAnnotations {
            page.addAnnotation(annotation)
            managedAnnotationIDs.insert(ObjectIdentifier(annotation))
        }
        forcePDFPageRedraw()
    }

    static func exportAnnotatedCopy(from originalURL: URL, annotations: [Data],
                                    to destination: URL) throws {
        guard originalURL.standardizedFileURL != destination.standardizedFileURL else {
            throw MnemosyneReaderError.exportWouldReplaceOriginal
        }
        guard let document = PDFDocument(url: originalURL) else {
            throw MnemosyneReaderError.cacheMissing
        }
        let digest = try sha256(of: originalURL)
        let staging = destination.deletingLastPathComponent()
            .appendingPathComponent(".\(UUID().uuidString).mnemosyne-export.pdf")
        try FileManager.default.createDirectory(at: destination.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        do {
            for data in annotations {
                guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      value["version_id"] as? String == "sha256:\(digest)",
                      let annotationID = UUID(uuidString: value["annotation_id"] as? String ?? ""),
                      let pageIndex = value["page_index"] as? Int,
                      pageIndex >= 0, pageIndex < document.pageCount,
                      let page = document.page(at: pageIndex),
                      value["deleted"] as? Bool != true,
                      let kind = value["kind"] as? String,
                      let payload = value["payload"] as? [String: Any] else { continue }

                switch kind {
                case "ink":
                    guard let strokes = payload["strokes"] as? [[String: Any]] else { continue }
                    let strokeData = try JSONSerialization.data(withJSONObject: strokes, options: [.sortedKeys])
                    let decoded = try JSONDecoder().decode([SidecarStroke].self, from: strokeData)
                    let unit = pageUserUnit(page)
                    for stroke in decoded {
                        let points = stroke.points.map { CGPoint(x: CGFloat($0.x), y: CGFloat($0.y)) }
                        let clipped = (try? MnemosyneGeometry(cropBox: page.bounds(for: .cropBox),
                                                               rotation: page.rotation, userUnit: unit))?
                            .clippedPolylines(points) ?? []
                        for (segmentIndex, segment) in clipped.enumerated() where !segment.isEmpty {
                            let id = UUID(uuidString: stroke.stroke_id) ?? annotationID
                            guard let ink = InkAnnotationBuilder.makeAnnotation(
                                pagePoints: segment,
                                pageStrokeWidth: CGFloat(stroke.width_pt) / unit,
                                color: StrokeColor(uiColor: color(fromHex: stroke.color)),
                                pageIndex: pageIndex,
                                uuid: segmentIndex == 0 ? id : UUID()
                            ) else { continue }
                            page.addAnnotation(ink)
                        }
                    }
                case "highlight":
                    guard let anchor = payload["anchor"] as? [String: Any],
                          let rects = anchor["rects"] as? [[NSNumber]],
                          let colorValue = payload["color"] as? String else { continue }
                    let quads = rects.compactMap { values -> Quad? in
                        guard values.count == 4 else { return nil }
                        let rect = CGRect(x: CGFloat(truncating: values[0]), y: CGFloat(truncating: values[1]),
                                          width: CGFloat(truncating: values[2]), height: CGFloat(truncating: values[3]))
                        guard rect.width > 0, rect.height > 0,
                              page.bounds(for: .cropBox).contains(rect) else { return nil }
                        return Quad(rect: rect)
                    }
                    guard !quads.isEmpty else { continue }
                    let color = color(fromHex: colorValue)
                    let value = Highlight(quads: quads,
                                          color: HighlightColor.closest(to: StrokeColor(uiColor: color)),
                                          pageIndex: pageIndex,
                                          extractedText: anchor["quote"] as? String ?? "")
                    page.addAnnotation(HighlightAnnotationBuilder.makeAnnotation(highlight: value,
                                                                                   uuid: annotationID))
                case "note":
                    guard let position = payload["position"] as? [NSNumber], position.count == 2,
                          let body = payload["body"] as? String else { continue }
                    let point = CGPoint(x: CGFloat(truncating: position[0]), y: CGFloat(truncating: position[1]))
                    let box = page.bounds(for: .cropBox)
                    let bounds = CGRect(x: min(max(point.x, box.minX), box.maxX - 160),
                                        y: min(max(point.y, box.minY), box.maxY - 56),
                                        width: 160, height: 56)
                    let note = PDFAnnotation(bounds: bounds, forType: .freeText, withProperties: nil)
                    note.contents = body
                    note.font = UIFont.systemFont(ofSize: 12)
                    note.fontColor = .label
                    note.userName = annotationID.uuidString.lowercased()
                    page.addAnnotation(note)
                case "bookmark":
                    let label = payload["label"] as? String ?? ""
                    let cropBox = page.bounds(for: .cropBox)
                    let markerSize = min(20, min(cropBox.width, cropBox.height))
                    guard markerSize > 0 else { throw MnemosyneReaderError.documentMismatch }
                    let marker = PDFAnnotation(
                        bounds: CGRect(x: cropBox.minX, y: cropBox.maxY - markerSize,
                                       width: markerSize, height: markerSize),
                        forType: .text, withProperties: nil
                    )
                    marker.contents = label.isEmpty ? "Bookmark" : label
                    marker.userName = annotationID.uuidString.lowercased()
                    page.addAnnotation(marker)
                default:
                    continue
                }
            }
            guard document.write(to: staging) else { throw CocoaError(.fileWriteUnknown) }
            guard !FileManager.default.fileExists(atPath: destination.path) else {
                throw CocoaError(.fileWriteFileExists)
            }
            try FileManager.default.moveItem(at: staging, to: destination)
        } catch {
            try? FileManager.default.removeItem(at: staging)
            throw error
        }
    }

    private func makeSidecarSnapshot() throws -> PumiceReaderSidecar {
        guard let document = pdfView.document,
              let digest = sourceSHA256 ?? pdfURL.flatMap({ try? Self.sha256(of: $0) }) else {
            throw MnemosyneReaderError.cacheMissing
        }
        var inkByPage = Dictionary(uniqueKeysWithValues: (sidecar?.ink_pages ?? []).map { ($0.page_index, $0) })

        for index in 0..<document.pageCount {
            guard let page = document.page(at: index),
                  let strokes = overlayProvider.strokes(for: page) else { continue }
            guard !strokes.isEmpty else {
                inkByPage.removeValue(forKey: index)
                pageInkAnnotationIDs.removeValue(forKey: index)
                continue
            }
            let annotationID = pageInkAnnotationIDs[index] ?? UUID()
            pageInkAnnotationIDs[index] = annotationID
            var savedStrokes: [SidecarStroke] = []
            for stroke in strokes {
                savedStrokes.append(contentsOf: try canonicalInkStrokes(for: stroke, on: page))
            }
            if !savedStrokes.isEmpty {
                inkByPage[index] = SidecarInkPage(annotation_id: annotationID.uuidString.lowercased(),
                                                  page_index: index, strokes: savedStrokes)
            }
        }

        var savedHighlights: [SidecarHighlight] = []
        for index in 0..<document.pageCount {
            guard let page = document.page(at: index) else { continue }
            for annotation in page.annotations where annotation.type == "Highlight" {
                guard let identifier = highlightIDs[ObjectIdentifier(annotation)],
                      sidecarOnlyHighlightIDs.contains(identifier) else { continue }
                let rects = Self.absoluteQuadRects(of: annotation).filter { $0.width > 0 && $0.height > 0 }
                guard !rects.isEmpty else { continue }
                savedHighlights.append(SidecarHighlight(
                    annotation_id: identifier.uuidString.lowercased(),
                    page_index: index,
                    color: Self.rgbaHex(annotation.color),
                    text: annotation.contents ?? "",
                    rects: rects.map {
                        SidecarRect(x: Double($0.minX), y: Double($0.minY),
                                    width: Double($0.width), height: Double($0.height))
                    }
                ))
            }
        }

        let lastPage = document.pageCount > 0 ? min(max(0, currentPageIndex), document.pageCount - 1) : nil
        return PumiceReaderSidecar(schema_version: 1, source_sha256: digest,
                                   ink_pages: inkByPage.values.sorted { $0.page_index < $1.page_index },
                                   highlights: savedHighlights, last_page_index: lastPage)
    }

    private func emitInkEdit(_ stroke: StrokeRecord, on page: PDFPage,
                             operation: MnemosyneLocalAnnotationEdit.Operation) {
        guard let onLocalAnnotationEdit,
              let document = pdfView.document,
              let documentIdentifier,
              let documentVersionID else { return }
        let pageIndex = document.index(for: page)
        guard pageIndex >= 0, pageIndex < document.pageCount else { return }
        do {
            let annotationID = stroke.annotationID ?? stroke.id
            var groupedStrokes = (overlayProvider.strokes(for: page) ?? []).filter {
                ($0.annotationID ?? $0.id) == annotationID
            }
            if operation == .upsert && !groupedStrokes.contains(where: { $0.id == stroke.id }) {
                groupedStrokes.append(stroke)
            }
            var editOperation: MnemosyneLocalAnnotationEdit.Operation =
                operation == .upsert || !groupedStrokes.isEmpty ? .upsert : .delete
            var draft: Data?
            if editOperation == .upsert {
                var strokes: [SidecarStroke] = []
                for groupedStroke in groupedStrokes {
                    strokes.append(contentsOf: try canonicalInkStrokes(for: groupedStroke, on: page))
                }
                if strokes.isEmpty {
                    editOperation = .delete
                } else {
                    let strokeData = try JSONEncoder().encode(strokes)
                    guard let payloadStrokes = try JSONSerialization.jsonObject(with: strokeData) as? [[String: Any]] else {
                        throw MnemosyneReaderError.malformedContractData
                    }
                    let object: [String: Any] = [
                        "annotation_id": annotationID.uuidString.lowercased(),
                        "document_id": documentIdentifier.uuidString.lowercased(),
                        "version_id": documentVersionID,
                        "page_index": pageIndex,
                        "kind": "ink",
                        "payload": ["strokes": payloadStrokes]
                    ]
                    draft = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
                }
            }
            if editOperation == .upsert, draft == nil {
                throw MnemosyneReaderError.malformedContractData
            }
            try onLocalAnnotationEdit(MnemosyneLocalAnnotationEdit(
                documentID: documentIdentifier,
                versionID: documentVersionID,
                annotationID: annotationID,
                pageIndex: pageIndex,
                kind: "ink",
                operation: editOperation,
                draft: draft
            ))
            lastLocalSaveError = nil
        } catch {
            lastLocalSaveError = error
        }
    }

    private func emitHighlightEdit(_ record: ErasedHighlightRecord,
                                   operation: MnemosyneLocalAnnotationEdit.Operation) {
        guard let onLocalAnnotationEdit, let annotationID = record.annotationID,
              let draft = record.draft,
              let object = try? JSONSerialization.jsonObject(with: draft) as? [String: Any],
              let documentID = UUID(uuidString: object["document_id"] as? String ?? ""),
              let versionID = object["version_id"] as? String,
              let pageIndex = object["page_index"] as? Int else { return }
        do {
            try onLocalAnnotationEdit(MnemosyneLocalAnnotationEdit(
                documentID: documentID,
                versionID: versionID,
                annotationID: annotationID,
                pageIndex: pageIndex,
                kind: "highlight",
                operation: operation,
                draft: operation == .upsert ? draft : nil
            ))
        } catch {
            lastLocalSaveError = error
        }
    }

    private func canonicalInkStrokes(for stroke: StrokeRecord, on page: PDFPage) throws -> [SidecarStroke] {
        guard let size = overlayProvider.canvasSize(for: page),
              let (geometry, scale) = Self.geometry(for: page, canvasSize: size) else {
            throw MnemosyneReaderError.cacheMissing
        }
        let samples = stroke.samples.isEmpty
            ? Self.pathPoints(stroke.path).enumerated().map {
                PencilStrokeSample(location: $0.element, pressure: 0.5, timeMilliseconds: $0.offset * 16)
            }
            : stroke.samples
        guard !samples.isEmpty else { return [] }
        let pdfPoints = samples.map {
            geometry.pdfPoint(fromViewport: $0.location, scale: scale, offset: .zero)
        }
        let physicalWidth = geometry.physicalWidth(fromViewportWidth: stroke.width, scale: scale)
        guard physicalWidth.isFinite, physicalWidth > 0, physicalWidth <= 100 else {
            throw MnemosyneReaderError.malformedContractData
        }
        return geometry.clippedPolylines(pdfPoints).enumerated().compactMap { segmentIndex, segment in
            guard !segment.isEmpty else { return nil }
            let points = segment.map { point -> SidecarPoint in
                let nearest = zip(pdfPoints.indices, pdfPoints).min {
                    hypot($0.1.x - point.x, $0.1.y - point.y) < hypot($1.1.x - point.x, $1.1.y - point.y)
                }?.0 ?? 0
                let sample = samples[min(nearest, samples.count - 1)]
                return SidecarPoint(x: Double(point.x), y: Double(point.y),
                                    pressure: Double(min(1, max(0, sample.pressure))),
                                    t_ms: max(0, sample.timeMilliseconds))
            }
            return SidecarStroke(
                stroke_id: Self.segmentUUID(base: stroke.id, index: segmentIndex).uuidString.lowercased(),
                tool: "pen",
                color: Self.rgbaHex(stroke.color),
                width_pt: Double(physicalWidth),
                points: points
            )
        }
    }

    private static func segmentUUID(base: UUID, index: Int) -> UUID {
        guard index > 0 else { return base }
        let hex = Array(base.uuidString.replacingOccurrences(of: "-", with: "").lowercased())
        let raw = Array(hex.prefix(28)) + Array(String(format: "%04x", index & 0xffff))
        let uuid = "\(String(raw[0..<8]))-\(String(raw[8..<12]))-\(String(raw[12..<16]))-" +
            "\(String(raw[16..<20]))-\(String(raw[20..<32]))"
        return UUID(uuidString: uuid) ?? base
    }

    private func loadSidecar(for source: URL) -> PumiceReaderSidecar? {
        do {
            let digest = try Self.sha256(of: source)
            let url = try Self.sidecarURL(for: source)
            guard let data = try? Data(contentsOf: url) else { return nil }
            let value = try JSONDecoder().decode(PumiceReaderSidecar.self, from: data)
            guard value.schema_version == 1, value.source_sha256 == digest else { return nil }
            return value
        } catch {
            return nil
        }
    }

    private func restoreSidecarHighlights(on page: PDFPage, pageIndex: Int) {
        guard let highlights = sidecar?.highlights.filter({ $0.page_index == pageIndex }) else { return }
        restoreHighlights(highlights, on: page, pageIndex: pageIndex, sidecarOnly: true)
    }

    private func restoreHighlights(_ highlights: [SidecarHighlight], on page: PDFPage,
                                   pageIndex: Int, sidecarOnly: Bool) {
        for item in highlights {
            guard let id = UUID(uuidString: item.annotation_id) else { continue }
            let rects = item.rects.map {
                CGRect(x: CGFloat($0.x), y: CGFloat($0.y),
                       width: CGFloat($0.width), height: CGFloat($0.height))
            }.filter { $0.width > 0 && $0.height > 0 }
            let cropBox = page.bounds(for: .cropBox)
            guard !rects.isEmpty,
                  rects.allSatisfy({ rect in
                      [rect.minX, rect.minY, rect.width, rect.height].allSatisfy(\.isFinite) &&
                          rect.minX >= cropBox.minX && rect.minY >= cropBox.minY &&
                          rect.maxX <= cropBox.maxX && rect.maxY <= cropBox.maxY
                  }) else { continue }
            let color = Self.color(fromHex: item.color)
            let highlight = Highlight(
                quads: rects.map(Quad.init(rect:)),
                color: HighlightColor.closest(to: StrokeColor(uiColor: color)),
                pageIndex: pageIndex,
                extractedText: item.text
            )
            let annotation = HighlightAnnotationBuilder.makeAnnotation(highlight: highlight, uuid: id)
            page.addAnnotation(annotation)
            highlightIDs[ObjectIdentifier(annotation)] = id
            managedAnnotationIDs.insert(ObjectIdentifier(annotation))
            if sidecarOnly { sidecarOnlyHighlightIDs.insert(id) }
        }
    }

    private func restoreSidecarStrokes(on page: PDFPage, canvas: PumiceCanvasView,
                                       size: CGSize, previousSize: CGSize?) {
        let canvasID = ObjectIdentifier(canvas)
        guard let document = pdfView.document else { return }
        let pageIndex = document.index(for: page)
        guard pageIndex != NSNotFound else { return }
        if let handledSize = handledCanvasSizes[canvasID], handledSize == size { return }
        let oldSize = handledCanvasSizes[canvasID] ?? previousSize

        if !canvas.strokes.isEmpty {
            if let oldSize,
               let (oldGeometry, oldScale) = Self.geometry(for: page, canvasSize: oldSize),
               let (newGeometry, newScale) = Self.geometry(for: page, canvasSize: size) {
                let resized = canvas.strokes.map { stroke -> StrokeRecord in
                    let samples = stroke.samples.map { sample -> PencilStrokeSample in
                        let pdfPoint = oldGeometry.pdfPoint(fromViewport: sample.location,
                                                            scale: oldScale, offset: .zero)
                        return PencilStrokeSample(
                            location: newGeometry.viewportPoint(fromPDF: pdfPoint,
                                                                scale: newScale, offset: .zero),
                            pressure: sample.pressure,
                            timeMilliseconds: sample.timeMilliseconds
                        )
                    }
                    let path = UIBezierPath()
                    if let first = samples.first {
                        path.move(to: first.location)
                        for sample in samples.dropFirst() { path.addLine(to: sample.location) }
                    } else {
                        let transform = CGAffineTransform(scaleX: size.width / oldSize.width,
                                                          y: size.height / oldSize.height)
                        let copiedPath = (stroke.path.copy() as? UIBezierPath) ?? UIBezierPath()
                        copiedPath.apply(transform)
                        path.append(copiedPath)
                    }
                    let physicalWidth = oldGeometry.physicalWidth(fromViewportWidth: stroke.width,
                                                                  scale: oldScale)
                    return StrokeRecord(
                        id: stroke.id,
                        annotationID: stroke.annotationID,
                        path: path,
                        color: stroke.color,
                        width: newGeometry.viewportWidth(fromPhysicalPoints: physicalWidth,
                                                         scale: newScale),
                        samples: samples
                    )
                }
                overlayProvider.setStrokes(resized, for: page)
            }
            handledCanvasSizes[canvasID] = size
            return
        }

        guard let savedPage = sidecar?.ink_pages.first(where: { $0.page_index == pageIndex }),
              let (geometry, scale) = Self.geometry(for: page, canvasSize: size) else {
            handledCanvasSizes[canvasID] = size
            return
        }

        let restored = savedPage.strokes.compactMap { saved -> StrokeRecord? in
            guard let id = UUID(uuidString: saved.stroke_id), !saved.points.isEmpty else { return nil }
            let color = Self.color(fromHex: saved.color)
            let samples = saved.points.map {
                PencilStrokeSample(
                    location: geometry.viewportPoint(fromPDF: CGPoint(x: CGFloat($0.x), y: CGFloat($0.y)),
                                                     scale: scale, offset: .zero),
                    pressure: CGFloat($0.pressure),
                    timeMilliseconds: $0.t_ms
                )
            }
            let path = UIBezierPath()
            if let first = samples.first {
                path.move(to: first.location)
                for sample in samples.dropFirst() { path.addLine(to: sample.location) }
            }
            return StrokeRecord(id: id, annotationID: strokeAnnotationIDs[id], path: path, color: color,
                                width: geometry.viewportWidth(fromPhysicalPoints: CGFloat(saved.width_pt), scale: scale),
                                samples: samples)
        }
        overlayProvider.setStrokes(restored, for: page)
        canvas.setStrokes(restored)
        handledCanvasSizes[canvasID] = size
    }

    private static func geometry(for page: PDFPage, canvasSize: CGSize) -> (MnemosyneGeometry, CGFloat)? {
        let cropBox = page.bounds(for: .cropBox)
        let rotation = ((page.rotation % 360) + 360) % 360
        let userUnit = pageUserUnit(page)
        guard let geometry = try? MnemosyneGeometry(cropBox: cropBox, rotation: rotation,
                                                    userUnit: userUnit) else { return nil }
        let displayWidth = (rotation == 90 || rotation == 270) ? cropBox.height : cropBox.width
        let scale = canvasSize.width / (displayWidth * userUnit)
        guard scale.isFinite, scale > 0 else { return nil }
        return (geometry, scale)
    }

    private static func pageUserUnit(_ page: PDFPage) -> CGFloat {
        guard let pageRef = page.pageRef,
              let dictionary = CGPDFPageGetDictionary(pageRef) else { return 1 }
        var value: CGPDFReal = 1
        guard CGPDFDictionaryGetNumber(dictionary, "UserUnit", &value), value.isFinite, value > 0 else {
            return 1
        }
        return CGFloat(value)
    }

    private static func pathPoints(_ path: UIBezierPath) -> [CGPoint] {
        var points: [CGPoint] = []
        path.cgPath.applyWithBlock { pointer in
            switch pointer.pointee.type {
            case .moveToPoint, .addLineToPoint: points.append(pointer.pointee.points[0])
            default: break
            }
        }
        return points
    }

    private static func rgbaHex(_ color: UIColor) -> String {
        var red: CGFloat = 0
        var green: CGFloat = 0
        var blue: CGFloat = 0
        var alpha: CGFloat = 0
        guard color.getRed(&red, green: &green, blue: &blue, alpha: &alpha) else { return "#000000FF" }
        return String(format: "#%02X%02X%02X%02X", Int((red * 255).rounded()),
                      Int((green * 255).rounded()), Int((blue * 255).rounded()),
                      Int((alpha * 255).rounded()))
    }

    private static func color(fromHex value: String) -> UIColor {
        let digits = value.hasPrefix("#") ? String(value.dropFirst()) : value
        guard digits.count == 8,
              let red = UInt8(digits.prefix(2), radix: 16),
              let green = UInt8(digits.dropFirst(2).prefix(2), radix: 16),
              let blue = UInt8(digits.dropFirst(4).prefix(2), radix: 16),
              let alpha = UInt8(digits.dropFirst(6).prefix(2), radix: 16) else { return .black }
        return UIColor(red: CGFloat(red) / 255, green: CGFloat(green) / 255,
                       blue: CGFloat(blue) / 255, alpha: CGFloat(alpha) / 255)
    }

    private static func sha256(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func sidecarURL(for source: URL) throws -> URL {
        guard let support = FileManager.default.urls(for: .applicationSupportDirectory,
                                                      in: .userDomainMask).first else {
            throw CocoaError(.fileNoSuchFile)
        }
        let directory = support.appendingPathComponent("Mnemosyne/ReaderSidecars", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(try sha256(of: source) + ".json")
    }

    // MARK: - Debounced autosave

    /// Pending 2-second timer to autosave after the last stroke. Each
    /// new stroke restarts the timer so a flurry of strokes doesn't
    /// trigger a save in the middle of drawing — only ~2s of pen
    /// inactivity fires the save. Matches Nutrient/PSPDFKit's
    /// recommendation of "save at natural pauses, never on a fixed
    /// interval."
    private var saveDebounceTimer: Timer?

    private func scheduleDebouncedSave() {
        saveDebounceTimer?.invalidate()
        saveDebounceTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.saveIfNeeded()
            }
        }
    }

    // MARK: - Tool settings

    func setPenColor(_ color: UIColor) {
        overlayProvider.setPenColor(color)
    }

    func setPenWidth(_ width: CGFloat) {
        overlayProvider.setPenWidth(width)
    }

    func setActiveTool(_ tool: Tool) {
        let mode: PumiceCanvasView.Mode
        switch tool {
        case .pen:         mode = .pen
        case .highlighter: mode = .highlighter
        case .eraser:      mode = .eraser
        }
        overlayProvider.setMode(mode)
    }

    func setHighlightColor(_ color: HighlightPenColor) {
        overlayProvider.setHighlightColor(color.uiColor)
    }

    func setHighlightWidth(_ width: CGFloat) {
        overlayProvider.setHighlightWidth(width)
    }

    // MARK: - Toolbar actions

    func undoLastChange() {
        _undoManager.undo()
        controller?.refreshState()
    }

    func redoLastChange() {
        _undoManager.redo()
        controller?.refreshState()
    }

    // MARK: - Stroke undo/redo

    /// Called from the overlay provider's onPathFinished closure right
    /// after a brand-new stroke lands in the stroke store. Registers
    /// the inverse (remove) as an undoable action; that action in turn
    /// registers its own inverse (re-add) on invocation, so the user
    /// can step through the full undo/redo chain.
    private func registerUndoForAddedStroke(stroke: StrokeRecord, on page: PDFPage) {
        _undoManager.registerUndo(withTarget: self) { target in
            target.performUndoRemoveStroke(stroke: stroke, on: page)
        }
    }

    private func performUndoRemoveStroke(stroke: StrokeRecord, on page: PDFPage) {
        overlayProvider.removeStroke(stroke, from: page)
        emitInkEdit(stroke, on: page, operation: .delete)
        _undoManager.registerUndo(withTarget: self) { target in
            target.performRedoAddStroke(stroke: stroke, on: page)
        }
        needsSave = true
        controller?.refreshState()
        scheduleDebouncedSave()
    }

    private func performRedoAddStroke(stroke: StrokeRecord, on page: PDFPage) {
        overlayProvider.appendStroke(stroke, to: page)
        emitInkEdit(stroke, on: page, operation: .upsert)
        _undoManager.registerUndo(withTarget: self) { target in
            target.performUndoRemoveStroke(stroke: stroke, on: page)
        }
        needsSave = true
        controller?.refreshState()
        scheduleDebouncedSave()
    }

    // MARK: - Eraser

    /// Hit-test radius for both stroke and highlight erasing, in canvas
    /// points. Mirrors `PumiceCanvasView.eraserRadius` so the two
    /// erasers behave identically.
    private static let eraserHitRadius: CGFloat = 12

    /// Highlights removed by the current in-flight eraser gesture.
    /// Built up per-segment by `handleEraserSegment` and consumed at
    /// gesture-end by `handleEraserSweep`, where it's folded into a
    /// single undo step alongside the canvas-removed strokes.
    private var pendingErasedHighlights: [PDFAnnotation] = []

    /// Called on every eraser `touchesMoved`. Removes any `/Highlight`
    /// annotation the freshly-traversed segment crosses, in real time,
    /// so the user sees highlights disappear under the eraser the same
    /// way scribbled strokes do. The accumulated batch is finalised at
    /// gesture-end by `handleEraserSweep`.
    private func handleEraserSegment(from: CGPoint, to: CGPoint, on page: PDFPage) {
        let pageHeight = page.bounds(for: .mediaBox).height
        // Sample one probe per ~4pt of eraser travel — same density
        // PumiceCanvasView uses for stroke hit-testing.
        let dx = to.x - from.x
        let dy = to.y - from.y
        let distance = (dx * dx + dy * dy).squareRoot()
        let steps = max(1, Int(distance / 4))
        var samplesInPageSpace: [CGPoint] = []
        samplesInPageSpace.reserveCapacity(steps + 1)
        for step in 0...steps {
            let t = CGFloat(step) / CGFloat(steps)
            let cx = from.x + dx * t
            let cy = from.y + dy * t
            samplesInPageSpace.append(CGPoint(x: cx, y: pageHeight - cy))
        }

        var newlyRemoved: [PDFAnnotation] = []
        for highlight in page.annotations where highlight.type == "Highlight" {
            if Self.highlight(highlight, isHitBy: samplesInPageSpace, radius: Self.eraserHitRadius) {
                page.removeAnnotation(highlight)
                newlyRemoved.append(highlight)
            }
        }

        guard !newlyRemoved.isEmpty else { return }
        pendingErasedHighlights.append(contentsOf: newlyRemoved)
        forcePDFPageRedraw()
    }

    /// Test whether `highlight`'s quads (expanded by `radius`) contain
    /// any of the eraser sample points (in PDF user space).
    private static func highlight(
        _ highlight: PDFAnnotation,
        isHitBy samplesInPageSpace: [CGPoint],
        radius: CGFloat
    ) -> Bool {
        for rect in absoluteQuadRects(of: highlight) {
            let expanded = rect.insetBy(dx: -radius, dy: -radius)
            for sample in samplesInPageSpace where expanded.contains(sample) {
                return true
            }
        }
        return false
    }

    /// Per-quad axis-aligned bounding rects of a markup annotation,
    /// in absolute PDF user-space coordinates. `quadrilateralPoints`
    /// are stored relative to `bounds.origin` per the PDFKit SDK
    /// header (`PDFAnnotationUtilities.h`); this helper adds the
    /// origin back to make the rects compatible with `PDFSelection`
    /// bounds and other absolute-space geometry.
    private static func absoluteQuadRects(of annotation: PDFAnnotation) -> [CGRect] {
        let origin = annotation.bounds.origin
        let quadPoints = annotation.quadrilateralPoints ?? []
        var rects: [CGRect] = []
        rects.reserveCapacity(quadPoints.count / 4)
        var i = 0
        while i + 3 < quadPoints.count {
            let pts = (i...i+3).map { quadPoints[$0].cgPointValue }
                .map { CGPoint(x: $0.x + origin.x, y: $0.y + origin.y) }
            let xs = pts.map(\.x)
            let ys = pts.map(\.y)
            rects.append(CGRect(
                x: xs.min() ?? 0,
                y: ys.min() ?? 0,
                width: (xs.max() ?? 0) - (xs.min() ?? 0),
                height: (ys.max() ?? 0) - (ys.min() ?? 0)
            ))
            i += 4
        }
        return rects
    }

    /// Called when the eraser gesture finishes on a page's canvas.
    /// The canvas has already removed crossed strokes in real time,
    /// and `handleEraserSegment` has already removed crossed highlights
    /// in real time. This pairs the two batches into a single undo
    /// step so one Undo restores everything the gesture rubbed out.
    private func handleEraserSweep(removedStrokes: [StrokeRecord], on page: PDFPage) {
        let removedHighlights = pendingErasedHighlights
        pendingErasedHighlights.removeAll()

        if removedStrokes.isEmpty && removedHighlights.isEmpty { return }
        let erasedHighlightRecords = removedHighlights.map { annotation in
            let id = highlightIDs[ObjectIdentifier(annotation)]
            return ErasedHighlightRecord(annotation: annotation, annotationID: id,
                                         draft: id.flatMap { contractAnnotationDrafts[$0] })
        }

        for stroke in removedStrokes {
            emitInkEdit(stroke, on: page, operation: .delete)
        }
        for record in erasedHighlightRecords { emitHighlightEdit(record, operation: .delete) }

        _undoManager.registerUndo(withTarget: self) { target in
            target.performUndoRestoreEraserBatch(
                strokes: removedStrokes,
                highlights: erasedHighlightRecords,
                on: page
            )
        }
        needsSave = true
        controller?.refreshState()
    }

    private func performUndoRestoreEraserBatch(
        strokes: [StrokeRecord],
        highlights: [ErasedHighlightRecord],
        on page: PDFPage
    ) {
        for stroke in strokes {
            overlayProvider.appendStroke(stroke, to: page)
            emitInkEdit(stroke, on: page, operation: .upsert)
        }
        for record in highlights {
            page.addAnnotation(record.annotation)
            if let id = record.annotationID {
                highlightIDs[ObjectIdentifier(record.annotation)] = id
                managedAnnotationIDs.insert(ObjectIdentifier(record.annotation))
                if record.draft == nil { sidecarOnlyHighlightIDs.insert(id) }
            }
        }
        if !highlights.isEmpty {
            forcePDFPageRedraw()
        }
        for record in highlights { emitHighlightEdit(record, operation: .upsert) }
        _undoManager.registerUndo(withTarget: self) { target in
            target.performRedoEraseEraserBatch(strokes: strokes, highlights: highlights, on: page)
        }
        needsSave = true
        controller?.refreshState()
    }

    private func performRedoEraseEraserBatch(
        strokes: [StrokeRecord],
        highlights: [ErasedHighlightRecord],
        on page: PDFPage
    ) {
        for stroke in strokes {
            overlayProvider.removeStroke(stroke, from: page)
            emitInkEdit(stroke, on: page, operation: .delete)
        }
        for record in highlights {
            page.removeAnnotation(record.annotation)
        }
        if !highlights.isEmpty {
            forcePDFPageRedraw()
        }
        for record in highlights { emitHighlightEdit(record, operation: .delete) }
        _undoManager.registerUndo(withTarget: self) { target in
            target.performUndoRestoreEraserBatch(strokes: strokes, highlights: highlights, on: page)
        }
        needsSave = true
        controller?.refreshState()
    }

    // MARK: - Highlighter

    /// Called when a highlighter gesture finishes. Converts the gesture
    /// endpoints from canvas (UIKit Y-down) to PDF user space (Y-up),
    /// asks PumiceCore to snap to the underlying text, and adds the
    /// resulting `/Highlight` annotation to the page. Silent no-op if
    /// no text underlies the gesture — we'd rather drop the stroke
    /// than draw freehand ink in the wrong tool mode.
    private func handleHighlightStrokeFinished(first: CGPoint, last: CGPoint, on page: PDFPage) {
        guard let document = pdfView.document else { return }
        let pageHeight = page.bounds(for: .mediaBox).height
        let firstPage = CGPoint(x: first.x, y: pageHeight - first.y)
        let lastPage = CGPoint(x: last.x, y: pageHeight - last.y)
        let pageIndex = document.index(for: page)
        let strokeColor = (controller?.highlightColor ?? .yellow).highlightColor.rgba

        guard let annotation = Self.buildSnapAnnotation(
            firstPagePoint: firstPage,
            lastPagePoint: lastPage,
            on: page,
            pageIndex: pageIndex,
            strokeColor: strokeColor
        ) else { return }

        // Don't stack highlights over already-highlighted text. We
        // compare per-quad rather than per-bounds: a multi-line
        // highlight's `.bounds` includes the gap between its lines,
        // so a bounds-only check would reject new highlights that
        // land on the gap (e.g. a single-line highlight on a line
        // between two highlighted lines). Per-quad with a small
        // overlap threshold rejects only genuine overlap.
        let newRects = Self.absoluteQuadRects(of: annotation)
        let existingHighlights = page.annotations.filter { $0.type == "Highlight" }
        let overlaps = existingHighlights.contains { existing in
            let existingRects = Self.absoluteQuadRects(of: existing)
            for newRect in newRects {
                for existingRect in existingRects {
                    let inter = newRect.intersection(existingRect)
                    // 0.5pt threshold ignores edge-touching adjacent
                    // text lines and tiny floating-point fuzz.
                    if inter.width > 0.5 && inter.height > 0.5 {
                        return true
                    }
                }
            }
            return false
        }
        if overlaps { return }

        page.addAnnotation(annotation)
        let annotationID = UUID()
        highlightIDs[ObjectIdentifier(annotation)] = annotationID
        sidecarOnlyHighlightIDs.insert(annotationID)
        managedAnnotationIDs.insert(ObjectIdentifier(annotation))
        // iOS 26 PDFKit caches each page's rendering in a PDFPageView
        // subview of pdfView.documentView. setNeedsDisplay on the PDFView
        // (or documentView) does NOT propagate to those page-level
        // caches, so a freshly-added annotation isn't drawn until the
        // page is scrolled off and back. Invalidate the per-page
        // subview directly.
        forcePDFPageRedraw()

        registerUndoForAddedHighlight(annotation, on: page)
        needsSave = true
        controller?.refreshState()
        scheduleDebouncedSave()
    }

    /// Invalidate each PDFPageView's cached rendering so PDFKit will
    /// invoke `draw(with:in:)` on the next display tick. Without this,
    /// freshly-added annotations don't draw until the page is scrolled
    /// off-screen and back (on iOS 26). Called from
    /// `handleHighlightStrokeFinished` and from the undo/redo paths
    /// that add or remove highlights.
    private func forcePDFPageRedraw() {
        for sv in pdfView.documentView?.subviews ?? [] {
            if NSStringFromClass(type(of: sv)) == "PDFPageView" {
                sv.setNeedsDisplay()
                sv.layer.setNeedsDisplay()
            }
        }
    }

    private func registerUndoForAddedHighlight(_ annotation: PDFAnnotation, on page: PDFPage) {
        _undoManager.registerUndo(withTarget: self) { target in
            target.performUndoRemoveHighlight(annotation, on: page)
        }
    }

    private func performUndoRemoveHighlight(_ annotation: PDFAnnotation, on page: PDFPage) {
        page.removeAnnotation(annotation)
        forcePDFPageRedraw()
        _undoManager.registerUndo(withTarget: self) { target in
            target.performRedoAddHighlight(annotation, on: page)
        }
        needsSave = true
        controller?.refreshState()
        scheduleDebouncedSave()
    }

    private func performRedoAddHighlight(_ annotation: PDFAnnotation, on page: PDFPage) {
        page.addAnnotation(annotation)
        forcePDFPageRedraw()
        _undoManager.registerUndo(withTarget: self) { target in
            target.performUndoRemoveHighlight(annotation, on: page)
        }
        needsSave = true
        controller?.refreshState()
        scheduleDebouncedSave()
    }

    // MARK: - Gesture shortcuts

    /// Two-finger double-tap → undo. The three-finger swipe-left/right
    /// gestures Apple ships system-wide work for free because we
    /// override `undoManager` above; iOS finds it via the responder
    /// chain and invokes undo/redo without us installing recognizers.
    /// Earlier we ALSO installed our own three-finger swipe gestures,
    /// but those raced the system pair, producing
    /// `System gesture gate timed out` errors and steady main-thread
    /// stalls that visibly jammed the toolbar Menu's tap response.
    private func installUndoRedoGestures() {
        let undoTap = UITapGestureRecognizer(target: self, action: #selector(undoGestureFired))
        undoTap.numberOfTapsRequired = 2
        undoTap.numberOfTouchesRequired = 2
        view.addGestureRecognizer(undoTap)
    }

    @objc private func undoGestureFired() {
        undoLastChange()
    }

    // MARK: - Finger gestures (single-tap = sidebar collapse, double-tap = fit page)

    /// Install single- and double-finger-tap recognizers on the
    /// reader view. Both refuse Pencil touches so they never collide
    /// with the pencil drawing gesture. `cancelsTouchesInView = false`
    /// keeps PDFView's own gestures (scroll, pinch, link tap)
    /// unaffected — we only observe.
    private func installFingerTapGestures() {
        let doubleTap = UITapGestureRecognizer(target: self, action: #selector(handleDoubleTap))
        doubleTap.numberOfTapsRequired = 2
        doubleTap.numberOfTouchesRequired = 1
        doubleTap.allowedTouchTypes = [NSNumber(value: UITouch.TouchType.direct.rawValue)]
        doubleTap.cancelsTouchesInView = false
        view.addGestureRecognizer(doubleTap)

        let singleTap = UITapGestureRecognizer(target: self, action: #selector(handleSingleTap))
        singleTap.numberOfTapsRequired = 1
        singleTap.numberOfTouchesRequired = 1
        singleTap.allowedTouchTypes = [NSNumber(value: UITouch.TouchType.direct.rawValue)]
        singleTap.cancelsTouchesInView = false
        singleTap.require(toFail: doubleTap)
        view.addGestureRecognizer(singleTap)
    }

    @objc private func handleSingleTap() {
        onSidebarTap?()
    }

    /// Toggle between "page fits the screen" and a comfortable
    /// zoomed-in factor on each double-tap. iOS PDFView's
    /// `scaleFactorForSizeToFit` matches the auto-scaled fit; bumping
    /// to ~2x of it gives a clean read-zoom that still uses pixels
    /// efficiently on retina displays.
    @objc private func handleDoubleTap() {
        let fit = pdfView.scaleFactorForSizeToFit
        let zoomed = min(fit * 2, pdfView.maxScaleFactor)
        // Compare against the fit factor with a small tolerance so we
        // don't get stuck at an arbitrarily-close value.
        if abs(pdfView.scaleFactor - fit) < 0.01 {
            pdfView.scaleFactor = zoomed
        } else {
            pdfView.scaleFactor = fit
        }
    }

    @objc private func handlePDFViewPageChanged() {
        guard let document = pdfView.document, let current = pdfView.currentPage else { return }
        let index = document.index(for: current)
        guard index != NSNotFound else { return }
        // Suppress the spurious page-changed notification PDFKit emits
        // when we restore the page in `load(url:restorePageIndex:)` —
        // otherwise the restore would immediately overwrite the saved
        // page index back to 0 (the document's initial currentPage
        // before our `go(to:)` lands).
        if let pending = pendingRestorePage {
            guard pending == index else { return }
            pendingRestorePage = nil
        }
        guard currentPageIndex != index else { return }
        currentPageIndex = index
        positionNeedsSave = true
        scheduleDebouncedSave()
        onPageChanged?(index)
    }

    // MARK: - Apple Pencil gestures

    /// Two `UIPencilInteraction` events, two distinct behaviors:
    ///   * **double-tap** (Pencil 2 or Pencil Pro side tap) alternates
    ///     between pen and highlighter — a quick way to flip between
    ///     freehand and snap-to-text without going through the menu.
    ///   * **squeeze-and-hold** (Pencil Pro only) sets the eraser for
    ///     as long as the squeeze is held; releasing the squeeze
    ///     restores whichever tool was active before. Lets the user
    ///     rub out a stray stroke mid-annotation and pop straight back
    ///     to drawing without touching the toolbar.
    ///
    /// We ignore the user's system-wide preferred-tap action — the
    /// toolbar Menu is always there as a fallback, and we want
    /// Pumice's gestures to be predictable across users.
    private func installPencilInteraction() {
        let interaction = UIPencilInteraction()
        interaction.delegate = self
        view.addInteraction(interaction)
    }

    // MARK: - Plumbing

    private func configurePDFView() {
        pdfView.translatesAutoresizingMaskIntoConstraints = false
        pdfView.autoScales = true
        pdfView.displayMode = .singlePageContinuous
        pdfView.displayDirection = .vertical
        pdfView.usePageViewController(false)
        pdfView.backgroundColor = .systemGroupedBackground
        view.addSubview(pdfView)

        NSLayoutConstraint.activate([
            pdfView.topAnchor.constraint(equalTo: view.topAnchor),
            pdfView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            pdfView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            pdfView.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])
    }

    // MARK: - Coordinate transforms

    /// Transform a `UIBezierPath` from canvas (UIKit, Y-down) to page
    /// (PDF user space, Y-up) coordinates. Mirrors the path vertically
    /// around the page's height.
    static func pagePath(fromCanvasPath canvasPath: UIBezierPath, pageHeight: CGFloat) -> UIBezierPath {
        let copy = canvasPath.copy() as! UIBezierPath
        var t = CGAffineTransform.identity
        t = t.translatedBy(x: 0, y: pageHeight)
        t = t.scaledBy(x: 1, y: -1)
        copy.apply(t)
        return copy
    }

    static func canvasPath(fromPagePath pagePath: UIBezierPath, pageHeight: CGFloat) -> UIBezierPath {
        // The same transform is its own inverse.
        return self.pagePath(fromCanvasPath: pagePath, pageHeight: pageHeight)
    }

    /// Convert a `StrokeRecord` into a standard `/Ink` PDFAnnotation
    /// via PumiceCore's builder. Flattens the canvas-coord path's
    /// move/line elements into page-coord points — the builder smooths
    /// them into a curve internally — and carries the stroke's own
    /// color and width onto the annotation so per-stroke styling
    /// survives the round-trip.
    static func inkAnnotation(
        fromStroke stroke: StrokeRecord,
        pageIndex: Int,
        pageHeight: CGFloat
    ) -> PDFAnnotation? {
        let pagePath = self.pagePath(fromCanvasPath: stroke.path, pageHeight: pageHeight)
        var pagePoints: [CGPoint] = []
        pagePath.cgPath.applyWithBlock { ptr in
            let elem = ptr.pointee
            switch elem.type {
            case .moveToPoint, .addLineToPoint:
                pagePoints.append(elem.points[0])
            default:
                break
            }
        }
        guard pagePoints.count >= 2 else { return nil }
        return InkAnnotationBuilder.makeAnnotation(
            pagePoints: pagePoints,
            pageStrokeWidth: stroke.width,
            color: StrokeColor(uiColor: stroke.color),
            pageIndex: pageIndex,
            uuid: UUID()
        )
    }

    /// Snap-to-text builder kept around for the F03 integration tests
    /// and for V2 wiring. Not called from the live path in V1.
    static func buildSnapAnnotation(
        firstPagePoint: CGPoint,
        lastPagePoint: CGPoint,
        on page: PDFPage,
        pageIndex: Int,
        strokeColor: StrokeColor
    ) -> PDFAnnotation? {
        guard let selection = page.selection(from: firstPagePoint, to: lastPagePoint),
              let text = selection.string,
              !text.isEmpty
        else { return nil }

        let quads = PDFSelectionAdapter.quads(from: selection, on: page)
        guard !quads.isEmpty else { return nil }

        let highlight = Highlight(
            quads: quads,
            color: HighlightColor.closest(to: strokeColor),
            pageIndex: pageIndex,
            extractedText: text,
            attachedNote: nil
        )
        return HighlightAnnotationBuilder.makeAnnotation(highlight: highlight, uuid: UUID())
    }
}

extension PDFReaderViewController: UIPencilInteractionDelegate {
    func pencilInteraction(_ interaction: UIPencilInteraction, didReceiveTap tap: UIPencilInteraction.Tap) {
        // Both Pencil 2 and Pencil Pro report the side double-tap
        // through this method. Alternate between pen and highlighter.
        controller?.alternatePenAndHighlighter()
    }

    func pencilInteraction(_ interaction: UIPencilInteraction, didReceiveSqueeze squeeze: UIPencilInteraction.Squeeze) {
        // Pencil Pro only. Hold = eraser; release = previous tool.
        switch squeeze.phase {
        case .began:
            controller?.beginEraserHold()
        case .ended, .cancelled:
            controller?.endEraserHold()
        case .changed:
            // The squeeze is still being held; we already entered the
            // eraser on `.began`. Re-entering would be idempotent but
            // would also re-set `preEraserTool` if the user had
            // somehow flipped tools mid-squeeze; safest to no-op.
            break
        @unknown default:
            controller?.endEraserHold()
        }
    }
}
