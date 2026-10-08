#if canImport(UIKit)
import Foundation
import UIKit
import CoreText

/// On-device markdown to PDF conversion. The PumiceCore side handles the
/// pure logic: building the attributed string, paginating it with Core
/// Text, picking a non-clobbering destination filename. The file write
/// itself happens at the call site so it can run inside
/// `NSFileCoordinator.coordinate(writingItemAt:)` against a security-
/// scoped vault URL.
public enum MarkdownPDFConverter {
    /// US letter (612 x 792pt) with a 72pt (1-inch) margin on every
    /// side. Matches the sample-vault PDFs Pumice generates so converted
    /// notes share a visual baseline with the rest of the vault.
    public static let defaultPageSize = CGSize(width: 612, height: 792)
    public static let defaultMargin: CGFloat = 72

    /// Render `markdown` to PDF data. Returns at least one blank page
    /// even for empty input.
    public static func convert(
        _ markdown: String,
        pageSize: CGSize = defaultPageSize,
        margin: CGFloat = defaultMargin
    ) -> Data {
        let style = makeStyle(pageSize: pageSize, margin: margin)
        let attributed = MarkdownAttributedString.build(from: markdown, style: style)
        return paginate(attributed, pageSize: pageSize, margin: margin)
    }

    /// Pick a free filename for the converted PDF in the directory
    /// holding `sourceURL`. `foo.md` becomes `foo.pdf` if that slot is
    /// free; otherwise `foo (Pumice).pdf`, then `foo (Pumice 2).pdf`,
    /// and so on. Never overwrites — collision behaviour matches macOS
    /// Finder duplicate naming.
    public static func destinationURL(
        for sourceURL: URL,
        fileManager: FileManager = .default
    ) -> URL {
        let directory = sourceURL.deletingLastPathComponent()
        let baseName = sourceURL.deletingPathExtension().lastPathComponent
        let primary = directory.appendingPathComponent("\(baseName).pdf")
        if !fileManager.fileExists(atPath: primary.path) {
            return primary
        }
        var attempt = 1
        while attempt <= 1000 {
            let suffix = attempt == 1 ? " (Pumice)" : " (Pumice \(attempt))"
            let candidate = directory.appendingPathComponent("\(baseName)\(suffix).pdf")
            if !fileManager.fileExists(atPath: candidate.path) {
                return candidate
            }
            attempt += 1
        }
        // ponytail: 1000-deep collision is "user hates us specifically".
        // Fall through to a UUID suffix rather than infinite-looping.
        return directory.appendingPathComponent("\(baseName) (Pumice \(UUID().uuidString.prefix(6))).pdf")
    }

    private static func makeStyle(
        pageSize: CGSize,
        margin: CGFloat
    ) -> MarkdownAttributedString.Style {
        var style = MarkdownAttributedString.Style.default
        style.pageWidth = pageSize.width - 2 * margin
        // Dynamic system colours (.label, .secondaryLabel, .systemBlue)
        // resolve against the current trait collection. Inside a
        // UIGraphicsPDFRenderer's off-screen context there's no live
        // trait collection, so they can resolve to white-on-white and
        // ship a PDF with invisible glyphs. Bake the colours to
        // light-mode static values for the converted output.
        let lightTraits = UITraitCollection(userInterfaceStyle: .light)
        style.textColor = style.textColor.resolvedColor(with: lightTraits)
        style.secondaryColor = style.secondaryColor.resolvedColor(with: lightTraits)
        style.linkColor = style.linkColor.resolvedColor(with: lightTraits)
        return style
    }

    private static func paginate(
        _ attr: NSAttributedString,
        pageSize: CGSize,
        margin: CGFloat
    ) -> Data {
        let pageRect = CGRect(origin: .zero, size: pageSize)
        let textRect = CGRect(
            x: margin,
            y: margin,
            width: pageSize.width - 2 * margin,
            height: pageSize.height - 2 * margin
        )
        let framesetter = CTFramesetterCreateWithAttributedString(attr as CFAttributedString)
        let totalLength = attr.length
        let renderer = UIGraphicsPDFRenderer(bounds: pageRect)
        return renderer.pdfData { ctx in
            var rendered = 0
            repeat {
                ctx.beginPage()
                let path = CGPath(rect: textRect, transform: nil)
                let frame = CTFramesetterCreateFrame(
                    framesetter,
                    CFRange(location: rendered, length: 0),
                    path,
                    nil
                )
                let visible = CTFrameGetVisibleStringRange(frame)
                let cg = ctx.cgContext
                cg.saveGState()
                // UIKit PDF context uses top-left origin; Core Text wants
                // bottom-left. Flip the CTM so glyphs land in the right
                // place. (PumiceCore mirrors this transform in
                // VaultStore.makeSamplePDF's NSAttributedString path.)
                cg.translateBy(x: 0, y: pageSize.height)
                cg.scaleBy(x: 1, y: -1)
                CTFrameDraw(frame, cg)
                cg.restoreGState()
                if visible.length == 0 {
                    // Pathological input (single token wider than the
                    // text rect): bail rather than spin forever.
                    break
                }
                rendered += visible.length
            } while rendered < totalLength
        }
    }
}

#endif

