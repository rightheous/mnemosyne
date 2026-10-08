import SwiftUI
import UIKit
import PumiceCore

/// Read-only markdown viewer. Loads the file off the main actor, builds
/// an attributed string via `PumiceCore.MarkdownAttributedString`, and
/// hands it to a `UITextView` for native scroll + selection behaviour.
/// The same attributed string is what the PDF converter paginates, so
/// the preview is honest about what gets exported.
struct MarkdownPreviewView: View {
    let url: URL

    @State private var attributed: NSAttributedString?
    @State private var loadError: String?

    var body: some View {
        Group {
            if let attributed {
                MarkdownTextView(attributedString: attributed)
            } else if let loadError {
                ContentUnavailableView(
                    "Cannot open note",
                    systemImage: "doc.text",
                    description: Text(loadError)
                )
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .task(id: url) { await load() }
    }

    private func load() async {
        attributed = nil
        loadError = nil
        let target = url
        // Read off-main (file I/O may block on File-Provider paths) but
        // build the attributed string on-main — NSAttributedString isn't
        // Sendable in iOS strict concurrency so we can't ferry one across
        // actor boundaries. Markdown build is in-memory and fast enough
        // to run inline for typical note sizes.
        let readOutcome: LoadOutcome = await Task.detached(priority: .userInitiated) {
            do {
                return .success(try String(contentsOf: target, encoding: .utf8))
            } catch {
                return .failure(error.localizedDescription)
            }
        }.value
        switch readOutcome {
        case .success(let source):
            attributed = MarkdownAttributedString.build(from: source)
        case .failure(let message):
            loadError = message
        }
    }

    /// Stand-in for `Result<String, Error>`. Plain `Error` isn't Sendable
    /// under Swift 6 strict concurrency, so we cross the actor hop with
    /// a localized message instead.
    private enum LoadOutcome: Sendable {
        case success(String)
        case failure(String)
    }
}

private struct MarkdownTextView: UIViewRepresentable {
    let attributedString: NSAttributedString

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.isEditable = false
        view.isSelectable = true
        view.backgroundColor = .clear
        view.alwaysBounceVertical = true
        view.textContainerInset = UIEdgeInsets(top: 20, left: 24, bottom: 32, right: 24)
        view.dataDetectorTypes = [.link]
        return view
    }

    func updateUIView(_ uiView: UITextView, context: Context) {
        if uiView.attributedText != attributedString {
            uiView.attributedText = attributedString
        }
    }
}
