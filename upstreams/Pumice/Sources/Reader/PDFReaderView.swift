import SwiftUI

struct PDFReaderView: UIViewControllerRepresentable {
    let pdfURL: URL
    @ObservedObject var controller: PDFReaderController
    /// Zero-indexed page to scroll to after the document loads. Pass
    /// the value from `VaultStore.resolveLastOpenedPage()` so the
    /// reader restores the user to the page they were reading. Nil
    /// (or 0) opens at the first page.
    var restorePageIndex: Int? = nil
    /// Called when the user single-taps the PDF detail with a finger.
    /// Used by the browser to collapse the sidebar once the reader is
    /// engaged.
    var onSidebarTap: (() -> Void)? = nil
    /// Called whenever the visible page changes. Used by the browser
    /// to persist a restore point.
    var onPageChanged: ((Int) -> Void)? = nil
    /// Optional Mnemosyne engine. UNIT-04 supplies the same instance that was
    /// injected into PersistentMnemosyneReaderFacade.
    var mnemosyneEngine: PumiceReaderEngine? = nil

    func makeUIViewController(context: Context) -> PDFReaderViewController {
        let vc = PDFReaderViewController()
        vc.onSidebarTap = onSidebarTap
        vc.onPageChanged = onPageChanged
        mnemosyneEngine?.attach(to: vc)
        vc.load(url: pdfURL, restorePageIndex: restorePageIndex)
        controller.attach(vc)
        return vc
    }

    func updateUIViewController(_ vc: PDFReaderViewController, context: Context) {
        vc.onSidebarTap = onSidebarTap
        vc.onPageChanged = onPageChanged
        mnemosyneEngine?.attach(to: vc)
        controller.attach(vc)
        vc.loadIfNeeded(url: pdfURL, restorePageIndex: restorePageIndex)
    }
}
