import Foundation

public enum MnemosyneDownloadState: Sendable {
    case missing, downloading, cached, invalid
}

/// UNIT-03 implements this boundary over the existing PDF/Pencil engine.
/// JSON data uses the pinned MnemosyneContracts bundle, never a second DTO contract.
@MainActor public protocol MnemosyneReaderFacade: AnyObject {
    func openCached(documentID: UUID, versionID: String) async throws
    func installDownloadedOriginal(from temporaryURL: URL, documentID: UUID,
                                   versionID: String) async throws
    func downloadState(documentID: UUID, versionID: String) throws -> MnemosyneDownloadState
    func readerContext() throws -> Data
    func applyReaderEvent(_ event: Data) throws
    func commitLocalEdit(_ mutation: Data) throws
    func undo() throws
    func redo() throws
    func pendingMutations(limit: Int) throws -> [Data]
    func applySyncReceipts(_ receipts: Data) throws
    func applyRemotePage(_ changesAndCursor: Data) throws
    func exportAnnotatedCopy(to destination: URL) async throws
}

/// Local input and its outbox mutation commit together before UI reports saved.
@MainActor public protocol MnemosyneLocalStore: AnyObject {
    func commitEditAndOutbox(_ mutation: Data) throws
    func pendingMutations(limit: Int) throws -> [Data]
    func commitReceipts(_ receipts: Data) throws
    func commitChangesAndCursor(_ page: Data) throws
}

/// Registration requires a real implementation; there is no silent no-op facade.
@MainActor public func makeReaderFacade(
    factory: (any MnemosyneLocalStore) throws -> any MnemosyneReaderFacade,
    localStore: any MnemosyneLocalStore
) throws -> any MnemosyneReaderFacade {
    try factory(localStore)
}
