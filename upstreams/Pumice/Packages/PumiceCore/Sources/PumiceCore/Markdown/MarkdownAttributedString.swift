#if canImport(UIKit)
import Foundation
import UIKit
import Markdown

/// Render markdown source into a styled `NSAttributedString`.
///
/// Shared between the in-app `.md` preview and the markdown-to-PDF
/// converter: both consume the same attributed-string output so the
/// user's preview is honest about what the exported PDF will look like.
/// Backed by Apple's swift-markdown package; uses the `MarkupVisitor`
/// protocol to fold the AST into runs with fonts, paragraph styles, and
/// colours. Block elements end with a newline + `.paragraphStyle` so
/// `CTFramesetter` paginates naturally.
public enum MarkdownAttributedString {
    /// Visual configuration. The defaults target letter-sized PDF pages
    /// (612pt wide, 1-inch margins) but the preview overrides `pageWidth`
    /// to match the live view bounds.
    public struct Style: Sendable {
        public var pageWidth: CGFloat
        public var bodyFont: UIFont
        public var monoFont: UIFont
        public var headingFonts: [UIFont]
        public var textColor: UIColor
        public var secondaryColor: UIColor
        public var linkColor: UIColor
        public var paragraphSpacing: CGFloat
        public var listIndent: CGFloat
        public var blockquoteIndent: CGFloat

        public init(
            pageWidth: CGFloat,
            bodyFont: UIFont,
            monoFont: UIFont,
            headingFonts: [UIFont],
            textColor: UIColor,
            secondaryColor: UIColor,
            linkColor: UIColor,
            paragraphSpacing: CGFloat,
            listIndent: CGFloat,
            blockquoteIndent: CGFloat
        ) {
            self.pageWidth = pageWidth
            self.bodyFont = bodyFont
            self.monoFont = monoFont
            self.headingFonts = headingFonts
            self.textColor = textColor
            self.secondaryColor = secondaryColor
            self.linkColor = linkColor
            self.paragraphSpacing = paragraphSpacing
            self.listIndent = listIndent
            self.blockquoteIndent = blockquoteIndent
        }

        public static let `default` = Style(
            pageWidth: 468,
            bodyFont: .systemFont(ofSize: 12),
            monoFont: .monospacedSystemFont(ofSize: 10.5, weight: .regular),
            headingFonts: [
                .systemFont(ofSize: 24, weight: .semibold),
                .systemFont(ofSize: 20, weight: .semibold),
                .systemFont(ofSize: 17, weight: .semibold),
                .systemFont(ofSize: 15, weight: .semibold),
                .systemFont(ofSize: 13, weight: .semibold),
                .systemFont(ofSize: 12, weight: .semibold)
            ],
            textColor: .label,
            secondaryColor: .secondaryLabel,
            linkColor: .systemBlue,
            paragraphSpacing: 8,
            listIndent: 18,
            blockquoteIndent: 20
        )
    }

    public static func build(from source: String, style: Style = .default) -> NSAttributedString {
        let document = Document(parsing: source)
        var builder = AttributedStringBuilder(style: style)
        return builder.visit(document)
    }
}

private struct AttributedStringBuilder: MarkupVisitor {
    typealias Result = NSAttributedString

    let style: MarkdownAttributedString.Style
    var listDepth: Int = 0
    var blockquoteDepth: Int = 0

    mutating func defaultVisit(_ markup: any Markup) -> NSAttributedString {
        // Concat children so unsupported markup (raw HTML, custom blocks)
        // at least surfaces its inner content rather than vanishing.
        let result = NSMutableAttributedString()
        for child in markup.children {
            result.append(visit(child))
        }
        return result
    }

    mutating func visitDocument(_ document: Document) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for child in document.children {
            result.append(visit(child))
        }
        return result
    }

    mutating func visitHeading(_ heading: Heading) -> NSAttributedString {
        let index = max(0, min(heading.level - 1, style.headingFonts.count - 1))
        let baseFont = style.headingFonts[index]
        let inline = collectInline(of: heading, baseFont: baseFont, baseColor: style.textColor)
        let result = NSMutableAttributedString(attributedString: inline)
        result.append(NSAttributedString(string: "\n"))
        applyParagraphStyle(
            to: result,
            headIndent: currentIndent(),
            spaceAfter: style.paragraphSpacing + 4,
            spaceBefore: 6
        )
        return result
    }

    mutating func visitParagraph(_ paragraph: Paragraph) -> NSAttributedString {
        let inline = collectInline(of: paragraph, baseFont: style.bodyFont, baseColor: style.textColor)
        let result = NSMutableAttributedString(attributedString: inline)
        result.append(NSAttributedString(string: "\n"))
        applyParagraphStyle(
            to: result,
            headIndent: currentIndent(),
            spaceAfter: style.paragraphSpacing
        )
        return result
    }

    mutating func visitBlockQuote(_ blockQuote: BlockQuote) -> NSAttributedString {
        blockquoteDepth += 1
        defer { blockquoteDepth -= 1 }
        let result = NSMutableAttributedString()
        for child in blockQuote.children {
            result.append(visit(child))
        }
        let range = NSRange(location: 0, length: result.length)
        // Italicize body-sized runs only; leave heading-sized text alone.
        result.enumerateAttribute(.font, in: range, options: []) { value, sub, _ in
            guard let font = value as? UIFont, font.pointSize <= style.bodyFont.pointSize + 1 else { return }
            let traits = font.fontDescriptor.symbolicTraits.union(.traitItalic)
            if let descriptor = font.fontDescriptor.withSymbolicTraits(traits) {
                result.addAttribute(.font, value: UIFont(descriptor: descriptor, size: 0), range: sub)
            }
        }
        result.addAttribute(.foregroundColor, value: style.secondaryColor, range: range)
        return result
    }

    mutating func visitUnorderedList(_ list: UnorderedList) -> NSAttributedString {
        listDepth += 1
        defer { listDepth -= 1 }
        let result = NSMutableAttributedString()
        for item in list.listItems {
            result.append(renderListItem(item, marker: "•"))
        }
        return result
    }

    mutating func visitOrderedList(_ list: OrderedList) -> NSAttributedString {
        listDepth += 1
        defer { listDepth -= 1 }
        let result = NSMutableAttributedString()
        var number = max(1, Int(list.startIndex))
        for item in list.listItems {
            result.append(renderListItem(item, marker: "\(number)."))
            number += 1
        }
        return result
    }

    mutating func visitListItem(_ listItem: ListItem) -> NSAttributedString {
        defaultVisit(listItem)
    }

    mutating func visitCodeBlock(_ codeBlock: CodeBlock) -> NSAttributedString {
        let code = codeBlock.code.trimmingCharacters(in: .newlines)
        let result = NSMutableAttributedString(string: code + "\n", attributes: [
            .font: style.monoFont,
            .foregroundColor: style.textColor
        ])
        // ponytail: no background fill — CTFrameDraw fills behind glyphs
        // only with a custom delegate. Monospace + indented head is
        // enough to read as "this is a code block".
        let paragraph = NSMutableParagraphStyle()
        paragraph.headIndent = currentIndent() + 6
        paragraph.firstLineHeadIndent = paragraph.headIndent
        paragraph.paragraphSpacing = style.paragraphSpacing
        paragraph.paragraphSpacingBefore = 4
        result.addAttribute(
            .paragraphStyle,
            value: paragraph,
            range: NSRange(location: 0, length: result.length)
        )
        return result
    }

    mutating func visitThematicBreak(_ thematicBreak: ThematicBreak) -> NSAttributedString {
        let rule = NSMutableAttributedString(string: "\u{2014}\u{2014}\u{2014}\u{2014}\u{2014}\u{2014}\n", attributes: [
            .font: style.bodyFont,
            .foregroundColor: style.secondaryColor
        ])
        applyParagraphStyle(
            to: rule,
            headIndent: currentIndent(),
            spaceAfter: style.paragraphSpacing
        )
        return rule
    }

    // MARK: - Inline

    mutating func visitText(_ text: Markdown.Text) -> NSAttributedString {
        NSAttributedString(string: text.string, attributes: [
            .font: style.bodyFont,
            .foregroundColor: style.textColor
        ])
    }

    mutating func visitEmphasis(_ emphasis: Emphasis) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for child in emphasis.children {
            result.append(visit(child))
        }
        applyFontTrait(.traitItalic, to: result)
        return result
    }

    mutating func visitStrong(_ strong: Strong) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for child in strong.children {
            result.append(visit(child))
        }
        applyFontTrait(.traitBold, to: result)
        return result
    }

    mutating func visitInlineCode(_ inlineCode: InlineCode) -> NSAttributedString {
        NSAttributedString(string: inlineCode.code, attributes: [
            .font: style.monoFont,
            .foregroundColor: style.textColor
        ])
    }

    mutating func visitLink(_ link: Markdown.Link) -> NSAttributedString {
        let result = NSMutableAttributedString()
        for child in link.children {
            result.append(visit(child))
        }
        let range = NSRange(location: 0, length: result.length)
        if let destination = link.destination, let url = URL(string: destination) {
            result.addAttribute(.link, value: url, range: range)
        }
        result.addAttribute(.foregroundColor, value: style.linkColor, range: range)
        result.addAttribute(.underlineStyle, value: NSUnderlineStyle.single.rawValue, range: range)
        return result
    }

    mutating func visitLineBreak(_ lineBreak: LineBreak) -> NSAttributedString {
        NSAttributedString(string: "\n")
    }

    mutating func visitSoftBreak(_ softBreak: SoftBreak) -> NSAttributedString {
        NSAttributedString(string: " ")
    }

    // MARK: - Helpers

    private func currentIndent() -> CGFloat {
        let listPart = CGFloat(max(0, listDepth - 1)) * style.listIndent
        let quotePart = CGFloat(blockquoteDepth) * style.blockquoteIndent
        return listPart + quotePart
    }

    private mutating func renderListItem(_ item: ListItem, marker: String) -> NSAttributedString {
        let childBuffer = NSMutableAttributedString()
        for child in item.children {
            childBuffer.append(visit(child))
        }
        let prefix = NSMutableAttributedString(string: "\(marker)\t", attributes: [
            .font: style.bodyFont,
            .foregroundColor: style.textColor
        ])
        prefix.append(childBuffer)

        let baseIndent = CGFloat(max(0, listDepth - 1)) * style.listIndent
            + CGFloat(blockquoteDepth) * style.blockquoteIndent
        let paragraph = NSMutableParagraphStyle()
        paragraph.firstLineHeadIndent = baseIndent
        paragraph.headIndent = baseIndent + style.listIndent
        paragraph.tabStops = [NSTextTab(textAlignment: .left, location: baseIndent + style.listIndent)]
        paragraph.paragraphSpacing = 2
        prefix.addAttribute(
            .paragraphStyle,
            value: paragraph,
            range: NSRange(location: 0, length: prefix.length)
        )
        return prefix
    }

    private mutating func collectInline(
        of container: any Markup,
        baseFont: UIFont,
        baseColor: UIColor
    ) -> NSAttributedString {
        let buffer = NSMutableAttributedString()
        for child in container.children {
            buffer.append(visit(child))
        }
        let range = NSRange(location: 0, length: buffer.length)
        // Lift body-font runs onto the container's base font, preserving
        // any italic/bold traits the inline visitors applied. Runs that
        // came from inline code (mono font) stay as-is.
        buffer.enumerateAttribute(.font, in: range, options: []) { value, sub, _ in
            guard let font = value as? UIFont else {
                buffer.addAttribute(.font, value: baseFont, range: sub)
                return
            }
            if font.fontName == style.bodyFont.fontName {
                let traits = font.fontDescriptor.symbolicTraits
                let descriptor = baseFont.fontDescriptor.withSymbolicTraits(traits) ?? baseFont.fontDescriptor
                buffer.addAttribute(.font, value: UIFont(descriptor: descriptor, size: 0), range: sub)
            }
        }
        buffer.enumerateAttribute(.foregroundColor, in: range, options: []) { value, sub, _ in
            if value == nil {
                buffer.addAttribute(.foregroundColor, value: baseColor, range: sub)
            }
        }
        return buffer
    }

    private func applyParagraphStyle(
        to attr: NSMutableAttributedString,
        headIndent: CGFloat,
        spaceAfter: CGFloat,
        spaceBefore: CGFloat = 0
    ) {
        let p = NSMutableParagraphStyle()
        p.headIndent = headIndent
        p.firstLineHeadIndent = headIndent
        p.paragraphSpacing = spaceAfter
        p.paragraphSpacingBefore = spaceBefore
        attr.addAttribute(
            .paragraphStyle,
            value: p,
            range: NSRange(location: 0, length: attr.length)
        )
    }

    private func applyFontTrait(
        _ trait: UIFontDescriptor.SymbolicTraits,
        to attr: NSMutableAttributedString
    ) {
        let range = NSRange(location: 0, length: attr.length)
        attr.enumerateAttribute(.font, in: range, options: []) { value, sub, _ in
            let base = (value as? UIFont) ?? style.bodyFont
            let combined = base.fontDescriptor.symbolicTraits.union(trait)
            if let descriptor = base.fontDescriptor.withSymbolicTraits(combined) {
                attr.addAttribute(.font, value: UIFont(descriptor: descriptor, size: 0), range: sub)
            }
        }
    }
}

#endif

