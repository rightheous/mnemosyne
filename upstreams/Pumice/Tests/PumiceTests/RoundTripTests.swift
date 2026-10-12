import CoreGraphics
import CryptoKit
import Foundation
import PDFKit
import PumiceCore
import Testing
import UIKit

/// Integration tests for the F03 bet: PencilKit-derived strokes and
/// snap-to-text highlights serialize to standard PDF annotations, get
/// written to disk, and survive a fresh read with their deterministic IDs
/// (persisted via /T because iOS PDFKit's writer drops /NM) and geometry
/// intact. See the InkAnnotationBuilder/HighlightAnnotationBuilder doc
/// comments for the rationale.
///
/// These tests require PDFKit + UIKit and therefore run via xcodebuild on
/// the iOS simulator. They are intentionally separate from the package's
/// pure tests (which run on macOS via `swift test`).
@Suite("F03 round-trip")
struct RoundTripTests {
    private static let pageSize = CGSize(width: 612, height: 792)

    @Test("Ink annotation survives write/read with deterministic ID and ink paths preserved")
    func inkRoundTrip() throws {
        let document = try #require(makeBlankDocument())
        let page = try #require(document.page(at: 0))

        let stroke = Stroke(
            points: [
                CGPoint(x: 100, y: 100),
                CGPoint(x: 200, y: 200),
                CGPoint(x: 300, y: 100)
            ],
            width: 2.5,
            color: StrokeColor(red: 0.2, green: 0.4, blue: 0.8, alpha: 1.0)
        )
        let geometry = PageGeometry(
            canvasSize: Self.pageSize,
            pageBounds: page.bounds(for: .mediaBox)
        )
        let uuid = UUID(uuidString: "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE")!
        let annotation = InkAnnotationBuilder.makeAnnotation(
            stroke: stroke,
            geometry: geometry,
            pageIndex: 0,
            uuid: uuid
        )
        page.addAnnotation(annotation)

        let tempURL = try writeAndExpectSuccess(document)
        defer { try? FileManager.default.removeItem(at: tempURL) }

        let reloaded = try #require(PDFDocument(url: tempURL))
        let reloadedPage = try #require(reloaded.page(at: 0))
        #expect(reloadedPage.annotations.count == 1)

        let reloadedInk = try #require(
            reloadedPage.annotations.first { $0.type == "Ink" }
        )
        let expectedID = AnnotationID(pageIndex: 0, annotationUUID: uuid).stringValue
        #expect(reloadedInk.userName == expectedID)
        #expect((reloadedInk.paths ?? []).isEmpty == false)
    }

    @Test("Highlight survives write/read with deterministic ID, quadrilateralPoints, and /Contents")
    func highlightRoundTrip() throws {
        let document = try #require(makeBlankDocument())
        let page = try #require(document.page(at: 0))

        let quads = [
            Quad(rect: CGRect(x: 50, y: 700, width: 200, height: 14)),
            Quad(rect: CGRect(x: 50, y: 680, width: 150, height: 14))
        ]
        let highlight = Highlight(
            quads: quads,
            color: .yellow,
            pageIndex: 0,
            extractedText: "First line.\nSecond line.",
            attachedNote: "Note text"
        )
        let uuid = UUID(uuidString: "11111111-2222-3333-4444-555555555555")!
        let annotation = HighlightAnnotationBuilder.makeAnnotation(
            highlight: highlight,
            uuid: uuid
        )
        page.addAnnotation(annotation)

        let tempURL = try writeAndExpectSuccess(document)
        defer { try? FileManager.default.removeItem(at: tempURL) }

        let reloaded = try #require(PDFDocument(url: tempURL))
        let reloadedPage = try #require(reloaded.page(at: 0))
        #expect(reloadedPage.annotations.count == 1)

        let reloadedHighlight = try #require(
            reloadedPage.annotations.first { $0.type == "Highlight" }
        )
        let expectedID = AnnotationID(pageIndex: 0, annotationUUID: uuid).stringValue
        #expect(reloadedHighlight.userName == expectedID)
        #expect(reloadedHighlight.contents == "First line.\nSecond line.")

        // 2 lines × 4 corners each.
        #expect(reloadedHighlight.quadrilateralPoints?.count == 8)

        // Every quad point must be local to `bounds.origin`, i.e.
        // inside `[0, 0, bounds.width, bounds.height]`. iOS PDFKit
        // silently drops the annotation otherwise (points outside
        // /Rect are ignored per the PDF spec) and the highlight
        // never renders. Without this assertion the bug we hit on
        // 2026-05-25 could regress invisibly: only on hardware, with
        // no test failure.
        let bounds = reloadedHighlight.bounds
        for (i, value) in (reloadedHighlight.quadrilateralPoints ?? []).enumerated() {
            let p = value.cgPointValue
            #expect(p.x >= -0.001 && p.x <= bounds.width + 0.001,
                    "quad point \(i) x=\(p.x) outside local bounds [0, \(bounds.width)]")
            #expect(p.y >= -0.001 && p.y <= bounds.height + 0.001,
                    "quad point \(i) y=\(p.y) outside local bounds [0, \(bounds.height)]")
        }
    }

    @Test("Ink and highlight on the same page are independently addressable by ID")
    func mixedRoundTripByNM() throws {
        let document = try #require(makeBlankDocument())
        let page = try #require(document.page(at: 0))
        let geometry = PageGeometry(
            canvasSize: Self.pageSize,
            pageBounds: page.bounds(for: .mediaBox)
        )

        let inkUUID = UUID()
        page.addAnnotation(InkAnnotationBuilder.makeAnnotation(
            stroke: Stroke(
                points: [
                    CGPoint(x: 10, y: 10),
                    CGPoint(x: 50, y: 30),
                    CGPoint(x: 100, y: 10)
                ],
                width: 1.5,
                color: StrokeColor(red: 0, green: 0, blue: 0, alpha: 1)
            ),
            geometry: geometry,
            pageIndex: 0,
            uuid: inkUUID
        ))

        let highlightUUID = UUID()
        page.addAnnotation(HighlightAnnotationBuilder.makeAnnotation(
            highlight: Highlight(
                quads: [Quad(rect: CGRect(x: 50, y: 500, width: 100, height: 14))],
                color: .green,
                pageIndex: 0,
                extractedText: "selected"
            ),
            uuid: highlightUUID
        ))

        let tempURL = try writeAndExpectSuccess(document)
        defer { try? FileManager.default.removeItem(at: tempURL) }

        let reloaded = try #require(PDFDocument(url: tempURL))
        let reloadedPage = try #require(reloaded.page(at: 0))
        #expect(reloadedPage.annotations.count == 2)

        let expectedInkID = AnnotationID(pageIndex: 0, annotationUUID: inkUUID).stringValue
        let expectedHighlightID = AnnotationID(pageIndex: 0, annotationUUID: highlightUUID).stringValue
        let stamps = reloadedPage.annotations.compactMap(\.userName)
        #expect(Set(stamps) == [expectedInkID, expectedHighlightID])
    }

    @Test("Derived export includes a local sidecar highlight and leaves the source unchanged")
    func sidecarHighlightExport() throws {
        let document = try #require(makeBlankDocument())
        let page = try #require(document.page(at: 0))
        let sourceMarker = PDFAnnotation(bounds: CGRect(x: 10, y: 10, width: 80, height: 20),
                                         forType: .freeText, withProperties: nil)
        sourceMarker.contents = UUID().uuidString
        page.addAnnotation(sourceMarker)

        let sourceURL = try writeAndExpectSuccess(document)
        defer { try? FileManager.default.removeItem(at: sourceURL) }
        let originalBytes = try Data(contentsOf: sourceURL)
        let digest = SHA256.hash(data: originalBytes).map { String(format: "%02x", $0) }.joined()
        let support = try #require(FileManager.default.urls(for: .applicationSupportDirectory,
                                                             in: .userDomainMask).first)
        let sidecarURL = support.appendingPathComponent("Mnemosyne/ReaderSidecars", isDirectory: true)
            .appendingPathComponent(digest + ".json")
        let previousSidecar = try? Data(contentsOf: sidecarURL)
        defer {
            if let previousSidecar {
                try? previousSidecar.write(to: sidecarURL, options: .atomic)
            } else {
                try? FileManager.default.removeItem(at: sidecarURL)
            }
        }
        try FileManager.default.createDirectory(at: sidecarURL.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        let sidecar: [String: Any] = [
            "schema_version": 1,
            "source_sha256": digest,
            "ink_pages": [],
            "highlights": [[
                "annotation_id": UUID().uuidString.lowercased(),
                "page_index": 0,
                "color": "#FFFF00FF",
                "text": "Offline sidecar highlight",
                "rects": [["x": 40.0, "y": 40.0, "width": 120.0, "height": 18.0]]
            ]],
            "last_page_index": 0
        ]
        try JSONSerialization.data(withJSONObject: sidecar, options: [.sortedKeys])
            .write(to: sidecarURL, options: .atomic)

        let destinationURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("pumice-sidecar-export-\(UUID().uuidString).pdf")
        defer { try? FileManager.default.removeItem(at: destinationURL) }
        try PDFReaderViewController.exportAnnotatedCopy(from: sourceURL,
                                                         annotations: [],
                                                         to: destinationURL)

        #expect(try Data(contentsOf: sourceURL) == originalBytes)
        let exported = try #require(PDFDocument(url: destinationURL))
        let exportedPage = try #require(exported.page(at: 0))
        let highlight = try #require(exportedPage.annotations.first { $0.type == "Highlight" })
        #expect(highlight.contents == "Offline sidecar highlight")
    }

    // MARK: - Helpers

    private func makeBlankDocument() -> PDFDocument? {
        let bounds = CGRect(origin: .zero, size: Self.pageSize)
        let renderer = UIGraphicsPDFRenderer(bounds: bounds)
        let data = renderer.pdfData { ctx in
            ctx.beginPage()
        }
        return PDFDocument(data: data)
    }

    private func writeAndExpectSuccess(_ document: PDFDocument) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("pumice-roundtrip-\(UUID().uuidString).pdf")
        let wrote = document.write(to: url)
        try #require(wrote, "PDFDocument.write returned false")
        return url
    }
}
