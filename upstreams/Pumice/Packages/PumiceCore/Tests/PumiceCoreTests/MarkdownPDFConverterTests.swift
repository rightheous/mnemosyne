#if canImport(UIKit)
import Foundation
import Testing
import PDFKit
@testable import PumiceCore

@Suite("MarkdownPDFConverter")
struct MarkdownPDFConverterTests {
    @Test("destinationURL picks .pdf when free")
    func destinationFree() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let source = dir.appendingPathComponent("notes.md")
        try Data().write(to: source)
        let dest = MarkdownPDFConverter.destinationURL(for: source)
        #expect(dest.lastPathComponent == "notes.pdf")
    }

    @Test("destinationURL auto-suffixes when .pdf exists")
    func destinationSuffix() throws {
        let dir = try makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let source = dir.appendingPathComponent("notes.md")
        try Data().write(to: source)
        try Data([0x25, 0x50, 0x44, 0x46]).write(to: dir.appendingPathComponent("notes.pdf"))
        let dest1 = MarkdownPDFConverter.destinationURL(for: source)
        #expect(dest1.lastPathComponent == "notes (Pumice).pdf")
        try Data().write(to: dest1)
        let dest2 = MarkdownPDFConverter.destinationURL(for: source)
        #expect(dest2.lastPathComponent == "notes (Pumice 2).pdf")
    }

    @Test("convert produces parsable PDF data with at least one page")
    func convertProducesPDF() throws {
        let markdown = """
        # Heading

        Paragraph one with **bold** and *italic*.

        - bullet a
        - bullet b

        ```
        code block
        ```
        """
        let data = MarkdownPDFConverter.convert(markdown)
        let document = try #require(PDFDocument(data: data))
        #expect(document.pageCount >= 1)
    }

    @Test("convert tolerates empty input")
    func convertEmpty() throws {
        let data = MarkdownPDFConverter.convert("")
        let document = try #require(PDFDocument(data: data))
        #expect(document.pageCount >= 1)
    }

    private func makeTempDir() throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("MarkdownPDFConverterTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}

#endif

