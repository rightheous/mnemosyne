import CoreGraphics
import CryptoKit
import Foundation
import Testing
@testable import PumiceCore

@Suite("PageGeometry")
struct PageGeometryTests {
    private static let usLetter = CGRect(x: 0, y: 0, width: 612, height: 792)
    private static let canvas = CGSize(width: 306, height: 396)

    @Test("Canvas top-left maps to PDF top-left of pageBounds")
    func topLeft() {
        let g = PageGeometry(canvasSize: Self.canvas, pageBounds: Self.usLetter)
        let pdf = g.pdfPoint(fromCanvas: CGPoint(x: 0, y: 0))
        #expect(pdf.x == 0)
        #expect(pdf.y == 792)
    }

    @Test("Canvas bottom-right maps to PDF bottom-right of pageBounds")
    func bottomRight() {
        let g = PageGeometry(canvasSize: Self.canvas, pageBounds: Self.usLetter)
        let pdf = g.pdfPoint(fromCanvas: CGPoint(x: 306, y: 396))
        #expect(pdf.x == 612)
        #expect(pdf.y == 0)
    }

    @Test("Canvas center maps to PDF center")
    func center() {
        let g = PageGeometry(canvasSize: Self.canvas, pageBounds: Self.usLetter)
        let pdf = g.pdfPoint(fromCanvas: CGPoint(x: 153, y: 198))
        #expect(pdf.x == 306)
        #expect(pdf.y == 396)
    }

    @Test("PDF-to-canvas inverts canvas-to-PDF")
    func roundTrip() {
        let g = PageGeometry(canvasSize: Self.canvas, pageBounds: Self.usLetter)
        let original = CGPoint(x: 42.5, y: 173.25)
        let pdf = g.pdfPoint(fromCanvas: original)
        let back = g.canvasPoint(fromPDF: pdf)
        #expect(abs(back.x - original.x) < 1e-9)
        #expect(abs(back.y - original.y) < 1e-9)
    }

    @Test("Non-zero pageBounds origin is respected")
    func nonZeroOrigin() {
        let bounds = CGRect(x: 50, y: 100, width: 612, height: 792)
        let g = PageGeometry(canvasSize: Self.canvas, pageBounds: bounds)
        let topLeft = g.pdfPoint(fromCanvas: .zero)
        #expect(topLeft.x == 50)
        #expect(topLeft.y == 892) // 100 + 792
        let bottomRight = g.pdfPoint(fromCanvas: CGPoint(x: 306, y: 396))
        #expect(bottomRight.x == 662) // 50 + 612
        #expect(bottomRight.y == 100)
    }

    @Test("Scale is page over canvas")
    func scale() {
        let g = PageGeometry(canvasSize: Self.canvas, pageBounds: Self.usLetter)
        #expect(g.scale.width == 2)
        #expect(g.scale.height == 2)
    }

    @Test("pdfLength averages x and y scale")
    func pdfLength() {
        let g = PageGeometry(
            canvasSize: CGSize(width: 100, height: 100),
            pageBounds: CGRect(x: 0, y: 0, width: 100, height: 200)
        )
        // scale.width == 1, scale.height == 2 → average == 1.5
        #expect(g.pdfLength(fromCanvas: 4) == 6)
    }
}

@Suite("MnemosyneGeometry")
struct MnemosyneGeometryTests {
    @Test("Crop origin, rotation, zoom, and scroll round-trip", arguments: [0, 90, 180, 270])
    func roundTrip(rotation: Int) throws {
        let geometry = try MnemosyneGeometry(
            cropBox: CGRect(x: 10, y: 20, width: 580, height: 750),
            rotation: rotation,
            userUnit: 2
        )
        let original = CGPoint(x: 127.25, y: 604.5)
        let viewport = geometry.viewportPoint(fromPDF: original, scale: 1.75,
                                              offset: CGPoint(x: 31, y: -12))
        let restored = geometry.pdfPoint(fromViewport: viewport, scale: 1.75,
                                         offset: CGPoint(x: 31, y: -12))
        #expect(abs(restored.x - original.x) < 1e-8)
        #expect(abs(restored.y - original.y) < 1e-8)
    }

    @Test("Stroke clipping splits at CropBox and rejects invalid points")
    func clipping() throws {
        let geometry = try MnemosyneGeometry(
            cropBox: CGRect(x: 10, y: 20, width: 100, height: 200), rotation: 90
        )
        let paths = geometry.clippedPolylines([
            CGPoint(x: 20, y: 30), CGPoint(x: 120, y: 30),
            CGPoint(x: 120, y: 250), CGPoint(x: 60, y: 250), CGPoint(x: 60, y: 70)
        ])
        #expect(paths.count == 2)
        #expect(paths.flatMap { $0 }.allSatisfy(geometry.contains))
        #expect(paths[0].first == CGPoint(x: 20, y: 30))
        #expect(paths[0].last == CGPoint(x: 110, y: 30))
        #expect(paths[1].first == CGPoint(x: 60, y: 220))
        #expect(paths[1].last == CGPoint(x: 60, y: 70))
        #expect(geometry.clippedPolylines([CGPoint(x: .nan, y: 0)]).isEmpty)
    }

    @Test("Width uses physical points and zoom only")
    func widthTransform() throws {
        let geometry = try MnemosyneGeometry(
            cropBox: CGRect(x: 0, y: 0, width: 100, height: 200),
            rotation: 270,
            userUnit: 2
        )
        let viewportWidth = geometry.viewportWidth(fromPhysicalPoints: 3, scale: 1.5)
        #expect(viewportWidth == 4.5)
        #expect(geometry.physicalWidth(fromViewportWidth: viewportWidth, scale: 1.5) == 3)
    }

    @Test("Saved viewport scale respects page rotation, CropBox, and UserUnit",
          arguments: [0, 90, 180, 270])
    func viewportScale(rotation: Int) throws {
        let geometry = try MnemosyneGeometry(
            cropBox: CGRect(x: 10, y: 20, width: 580, height: 750),
            rotation: rotation,
            userUnit: 2
        )
        let scale = try #require(geometry.scaleToFitPDFRect(
            CGRect(x: 100, y: 100, width: 200, height: 300),
            in: CGSize(width: 600, height: 400)
        ))
        #expect(abs(scale - ((rotation == 90 || rotation == 270) ? 1 : 2.0 / 3.0)) < 1e-8)
        #expect(geometry.scaleToFitPDFRect(
            CGRect(x: 700, y: 900, width: 10, height: 10),
            in: CGSize(width: 600, height: 400)
        ) == nil)
    }
}

@MainActor
private final class StubMnemosyneReaderEngine: MnemosyneReaderEngine {
    var context: Data
    var selection: String?
    private var editHandler: (@MainActor (MnemosyneLocalAnnotationEdit) throws -> Void)?
    private var selectionChangeHandler: (@MainActor () -> Void)?

    init(context: Data, selection: String?) {
        self.context = context
        self.selection = selection
    }

    func openDocument(at url: URL, documentID: UUID, versionID: String,
                      restoring context: Data?, annotations: [Data]) async throws {
        if let context { self.context = context }
    }
    func currentReaderContext() throws -> Data { context }
    func selectedText() throws -> String? { selection }
    func setLocalEditHandler(_ handler: (@MainActor (MnemosyneLocalAnnotationEdit) throws -> Void)?) {
        editHandler = handler
    }
    func setSelectionChangeHandler(_ handler: (@MainActor () -> Void)?) {
        selectionChangeHandler = handler
    }
    func updateSelection(_ selection: String?) {
        self.selection = selection
        selectionChangeHandler?()
    }
    func search(text: String) throws -> [Data] { [] }
    func tableOfContents() throws -> Data { Data("{}".utf8) }
    func goToPage(index: Int) throws {}
    func applyReaderEvent(_ event: Data) throws {}
    func replaceAnnotations(_ annotations: [Data]) throws {}
    func undo() throws {}
    func redo() throws {}
    func exportAnnotatedCopy(originalURL: URL, annotations: [Data],
                             to destination: URL) async throws {}
}

@Suite("Mnemosyne local persistence")
@MainActor
struct MnemosyneLocalStoreTests {
    private let documentID = UUID(uuidString: "00000000-0000-0000-0000-000000000001")!
    private let annotationID = UUID(uuidString: "00000000-0000-0000-0000-00000000000a")!
    private let mutationID = UUID(uuidString: "00000000-0000-0000-0000-00000000000b")!
    private let clientID = UUID(uuidString: "00000000-0000-0000-0000-00000000000c")!
    private let versionID = "sha256:" + String(repeating: "a", count: 64)

    @Test("Immutable original cache and read context survive store recreation")
    func cacheAndContextRestore() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("download.pdf")
        let bytes = Data("synthetic PDF fixture bytes".utf8)
        try bytes.write(to: source)
        let versionID = "sha256:" + SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
        let store = try FileMnemosyneLocalStore(rootDirectory: root.appendingPathComponent("store"))
        let cached = try store.installOriginal(from: source, documentID: documentID,
                                               versionID: versionID)
        #expect(try Data(contentsOf: source) == bytes)
        #expect(try Data(contentsOf: cached) == bytes)

        let context = try json([
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "page_index": 1,
            "viewport_rect": [10, 20, 100, 200],
            "selection": NSNull(),
            "content_language": "ko",
            "response_language": "ko"
        ])
        try store.saveReaderContext(context, documentID: documentID, versionID: versionID)

        let reopened = try FileMnemosyneLocalStore(rootDirectory: root.appendingPathComponent("store"))
        #expect(try reopened.cachedOriginalURL(documentID: documentID, versionID: versionID) == cached)
        #expect(try reopened.cachedVersionID(documentID: documentID) == versionID)
        #expect(try reopened.readerContext(documentID: documentID, versionID: versionID) != nil)
    }

    @Test("Verified selection anchors round-trip only for the active document version and page")
    func verifiedSelectionContext() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let source = root.appendingPathComponent("selection-fixture.pdf")
        let bytes = Data("synthetic PDF selection fixture".utf8)
        try bytes.write(to: source)
        let versionID = "sha256:" + SHA256.hash(data: bytes).map {
            String(format: "%02x", $0)
        }.joined()
        let store = try FileMnemosyneLocalStore(rootDirectory: root.appendingPathComponent("store"))
        _ = try store.installOriginal(from: source, documentID: documentID, versionID: versionID)
        let engineContext = try json([
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "page_index": 1,
            "viewport_rect": [10, 20, 300, 400],
            "selection": NSNull(),
            "content_language": "und",
            "response_language": "ko"
        ])
        let engine = StubMnemosyneReaderEngine(context: engineContext, selection: "energy")
        let facade = PersistentMnemosyneReaderFacade(localStore: store, engine: engine)
        try await facade.openCached(documentID: documentID, versionID: versionID)
        #expect(try facade.selectedText() == "energy")

        let anchor: [String: Any] = [
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "page_index": 1,
            "parse_revision": "parser-nfc-v1",
            "text_sha256": String(repeating: "a", count: 64),
            "start_scalar": 2,
            "end_scalar": 8,
            "quote": "energy",
            "rects": [[10, 20, 100, 12]]
        ]
        try facade.setVerifiedSelectionAnchor(json(anchor))
        let saved = try JSONSerialization.jsonObject(with: facade.readerContext()) as! [String: Any]
        let savedAnchor = try #require(saved["selection"] as? [String: Any])
        #expect(savedAnchor["quote"] as? String == "energy")
        #expect(try store.readerContext(documentID: documentID, versionID: versionID) != nil)

        let restartedStore = try FileMnemosyneLocalStore(rootDirectory: root.appendingPathComponent("store"))
        let restartedEngine = StubMnemosyneReaderEngine(context: engineContext, selection: nil)
        let restartedFacade = PersistentMnemosyneReaderFacade(localStore: restartedStore,
                                                               engine: restartedEngine)
        try await restartedFacade.openCached(documentID: documentID, versionID: versionID)
        let restartedContext = try JSONSerialization.jsonObject(with: restartedFacade.readerContext()) as! [String: Any]
        #expect((restartedContext["selection"] as? [String: Any])?["quote"] as? String == "energy")

        restartedEngine.updateSelection(nil)
        let clearedAfterSelectionChange = try JSONSerialization.jsonObject(with: restartedFacade.readerContext()) as! [String: Any]
        #expect(clearedAfterSelectionChange["selection"] is NSNull)

        #expect(try facade.selectedText() == "energy")
        let cleared = try JSONSerialization.jsonObject(with: facade.readerContext()) as! [String: Any]
        #expect(cleared["selection"] is NSNull)

        var wrongPage = anchor
        wrongPage["page_index"] = 0
        #expect(throws: MnemosyneReaderError.self) {
            try facade.setVerifiedSelectionAnchor(json(wrongPage))
        }
        var malformedObject = try JSONSerialization.jsonObject(with: engineContext) as! [String: Any]
        malformedObject["selection"] = "unverified text"
        let malformedContext = try json(malformedObject)
        #expect(throws: MnemosyneReaderError.self) {
            try store.saveReaderContext(malformedContext, documentID: documentID, versionID: versionID)
        }
    }

    @Test("Local drafts survive remote changes, failure, retry, and applied receipt")
    func outboxAndRemoteMerge() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try FileMnemosyneLocalStore(rootDirectory: root)
        let mutation = try makeMutation(body: "local draft")
        try store.commitEditAndOutbox(mutation)
        #expect(try store.pendingMutations(limit: 10).count == 1)

        let remote = annotationRecord(body: "remote value", revision: 5)
        try store.commitChangesAndCursor(try json([
            "contract_version": "0.1.0",
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "changes": [remote],
            "next_cursor": "cursor-6",
            "has_more": false
        ]))
        #expect(try store.receivedCursor(documentID: documentID, versionID: versionID) == "cursor-6")
        let localProjection = try #require(store.annotations(documentID: documentID, versionID: versionID).first)
        let localObject = try JSONSerialization.jsonObject(with: localProjection) as? [String: Any]
        let localPayload = localObject?["payload"] as? [String: Any]
        #expect(localPayload?["body"] as? String == "local draft")

        try store.markMutationFailed(mutationID, reason: "temporary offline")
        let reopened = try FileMnemosyneLocalStore(rootDirectory: root)
        #expect(try reopened.pendingMutations(limit: 10).isEmpty)
        #expect(try reopened.failedMutations().count == 1)
        try reopened.retryMutation(mutationID)
        #expect(try reopened.pendingMutations(limit: 10).count == 1)

        let applied = annotationRecord(body: "local draft", revision: 6)
        try reopened.commitReceipts(try json([
            "contract_version": "0.1.0",
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "results": [[
                "client_mutation_id": mutationID.uuidString.lowercased(),
                "status": "applied",
                "code": "ok",
                "server_revision": 6,
                "current": applied
            ]]
        ]))
        #expect(try reopened.pendingMutations(limit: 10).isEmpty)
        try reopened.commitEditAndOutbox(mutation)
        #expect(try reopened.pendingMutations(limit: 10).isEmpty)

        let changedPayload = try makeMutation(body: "different payload")
        #expect(throws: MnemosyneReaderError.self) {
            try reopened.commitEditAndOutbox(changedPayload)
        }
    }

    @Test("Same-annotation outbox edits wait for the prior receipt and advance revision")
    func sameAnnotationOutboxAdvancesRevision() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try FileMnemosyneLocalStore(rootDirectory: root)
        let initial = annotationRecord(body: "server value", revision: 5)
        try store.commitChangesAndCursor(try json([
            "contract_version": "0.1.0",
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "changes": [initial],
            "next_cursor": "cursor-5",
            "has_more": false
        ]))

        let secondMutationID = UUID(uuidString: "00000000-0000-0000-0000-00000000000d")!
        let first = try makeMutation(body: "first local value")
        let second = try makeMutation(body: "second local value", mutationID: secondMutationID)
        try store.commitEditAndOutbox(first)
        try store.commitEditAndOutbox(second)

        let firstPending = try store.pendingMutations(limit: 10)
        #expect(firstPending.count == 1)
        let firstObject = try JSONSerialization.jsonObject(with: #require(firstPending.first)) as! [String: Any]
        #expect(firstObject["client_mutation_id"] as? String == mutationID.uuidString.lowercased())
        #expect(firstObject["base_revision"] as? Int == 5)

        try store.markMutationFailed(mutationID, reason: "temporary offline")
        #expect(try store.pendingMutations(limit: 10).isEmpty)
        try store.retryMutation(mutationID)

        let firstCurrent = annotationRecord(body: "first local value", revision: 6)
        try store.commitReceipts(try json([
            "contract_version": "0.1.0",
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "results": [[
                "client_mutation_id": mutationID.uuidString.lowercased(),
                "status": "applied",
                "code": "ok",
                "server_revision": 6,
                "current": firstCurrent
            ]]
        ]))

        let secondPending = try store.pendingMutations(limit: 10)
        #expect(secondPending.count == 1)
        let secondObject = try JSONSerialization.jsonObject(with: #require(secondPending.first)) as! [String: Any]
        #expect(secondObject["client_mutation_id"] as? String == secondMutationID.uuidString.lowercased())
        #expect(secondObject["base_revision"] as? Int == 6)

        let secondCurrent = annotationRecord(body: "second local value", revision: 7)
        try store.commitReceipts(try json([
            "contract_version": "0.1.0",
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "results": [[
                "client_mutation_id": secondMutationID.uuidString.lowercased(),
                "status": "applied",
                "code": "ok",
                "server_revision": 7,
                "current": secondCurrent
            ]]
        ]))
        #expect(try store.pendingMutations(limit: 10).isEmpty)
        let visible = try #require(store.annotations(documentID: documentID, versionID: versionID).first)
        let visibleObject = try JSONSerialization.jsonObject(with: visible) as! [String: Any]
        let visiblePayload = visibleObject["payload"] as? [String: Any]
        #expect(visiblePayload?["body"] as? String == "second local value")
    }

    @Test("Approved annotation event and outbox survive restart and replay")
    func approvedEventIsDurableAndIdempotent() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let eventID = "turn_1791442800000_0000000001:8"
        let mutation = try makeMutation(body: "approved suggestion")
        let store = try FileMnemosyneLocalStore(rootDirectory: root)
        let accepted = try store.commitApprovedEvent(eventID, mutation: mutation)
        #expect(try store.pendingMutations(limit: 10).count == 1)

        let reopened = try FileMnemosyneLocalStore(rootDirectory: root)
        #expect(try reopened.commitApprovedEvent(eventID, mutation: mutation) == accepted)
        var replayObject = try JSONSerialization.jsonObject(with: mutation) as! [String: Any]
        replayObject["created_at"] = "2026-10-09T12:00:00Z"
        #expect(try reopened.commitApprovedEvent(eventID, mutation: json(replayObject)) == accepted)
        #expect(try reopened.pendingMutations(limit: 10).count == 1)

        let changedPayload = try makeMutation(body: "changed suggestion")
        #expect(throws: MnemosyneReaderError.self) {
            try reopened.commitApprovedEvent(eventID, mutation: changedPayload)
        }
        #expect(throws: MnemosyneReaderError.self) {
            try reopened.commitApprovedEvent("turn_1791442800000_0000000001:9", mutation: mutation)
        }
    }

    @Test("Malformed text anchors are rejected before local sync staging")
    func invalidCitationAnchorIsRejected() throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = try FileMnemosyneLocalStore(rootDirectory: root)
        let invalidAnnotationID = UUID()
        let invalidMutationID = UUID()
        let invalidDraft: [String: Any] = [
            "annotation_id": invalidAnnotationID.uuidString.lowercased(),
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "page_index": 0,
            "kind": "highlight",
            "payload": [
                "anchor": [
                    "document_id": documentID.uuidString.lowercased(),
                    "version_id": versionID,
                    "page_index": 0,
                    "parse_revision": "",
                    "text_sha256": "not-a-hash",
                    "start_scalar": 3,
                    "end_scalar": 2,
                    "quote": "",
                    "rects": []
                ],
                "color": "#FFE08280"
            ]
        ]
        let mutation = try json([
            "client_mutation_id": invalidMutationID.uuidString.lowercased(),
            "client_id": clientID.uuidString.lowercased(),
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "annotation_id": invalidAnnotationID.uuidString.lowercased(),
            "base_revision": 0,
            "created_at": "2026-10-08T00:00:00Z",
            "operation": "upsert",
            "annotation": invalidDraft
        ])
        #expect(throws: MnemosyneReaderError.self) {
            try store.commitEditAndOutbox(mutation)
        }
        #expect(try store.pendingMutations(limit: 10).isEmpty)
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try! FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }

    private func makeMutation(body: String, mutationID: UUID? = nil) throws -> Data {
        let draft: [String: Any] = [
            "annotation_id": annotationID.uuidString.lowercased(),
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "page_index": 0,
            "kind": "note",
            "payload": ["position": [10, 20], "body": body, "anchor": NSNull()]
        ]
        return try json([
            "client_mutation_id": (mutationID ?? self.mutationID).uuidString.lowercased(),
            "client_id": clientID.uuidString.lowercased(),
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "annotation_id": annotationID.uuidString.lowercased(),
            "base_revision": 0,
            "created_at": "2026-10-08T00:00:00Z",
            "operation": "upsert",
            "annotation": draft
        ])
    }

    private func annotationRecord(body: String, revision: Int) -> [String: Any] {
        [
            "annotation_id": annotationID.uuidString.lowercased(),
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "page_index": 0,
            "kind": "note",
            "payload": ["position": [10, 20], "body": body, "anchor": NSNull()],
            "server_revision": revision,
            "deleted": false,
            "updated_at": "2026-10-08T00:00:01Z",
            "deleted_at": NSNull()
        ]
    }

    private func json(_ value: Any) throws -> Data {
        try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    }
}
