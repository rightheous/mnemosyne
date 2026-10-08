import CryptoKit
import Foundation

public enum MnemosyneDownloadState: Sendable, Equatable {
    case missing, downloading, cached, invalid
}

public enum MnemosyneReaderError: Error, Sendable {
    case invalidVersion
    case sourceHashMismatch
    case cacheMissing
    case malformedContractData
    case documentMismatch
    case idempotencyMismatch
    case mutationNotFound
    case exportWouldReplaceOriginal
}

public struct MnemosyneLocalAnnotationEdit {
    public enum Operation: Sendable, Equatable { case upsert, delete }
    public let documentID: UUID
    public let versionID: String
    public let annotationID: UUID
    public let pageIndex: Int
    public let kind: String
    public let operation: Operation
    public let draft: Data?
    public let mutationID: UUID

    public init(documentID: UUID, versionID: String, annotationID: UUID,
                pageIndex: Int, kind: String, operation: Operation,
                draft: Data? = nil, mutationID: UUID = UUID()) {
        self.documentID = documentID
        self.versionID = versionID
        self.annotationID = annotationID
        self.pageIndex = pageIndex
        self.kind = kind
        self.operation = operation
        self.draft = draft
        self.mutationID = mutationID
    }
}

/// The platform PDF engine stays outside PumiceCore. A UIKit/PDFKit adapter
/// must implement this protocol and is injected by the app composition root.
@MainActor public protocol MnemosyneReaderEngine: AnyObject {
    func openDocument(at url: URL, documentID: UUID, versionID: String,
                      restoring context: Data?, annotations: [Data]) async throws
    func currentReaderContext() throws -> Data
    /// Returns raw PDFKit selection text. It is not a verified citation anchor.
    func selectedText() throws -> String?
    func setLocalEditHandler(_ handler: (@MainActor (MnemosyneLocalAnnotationEdit) throws -> Void)?)
    func setSelectionChangeHandler(_ handler: (@MainActor () -> Void)?)
    func search(text: String) throws -> [Data]
    func tableOfContents() throws -> Data
    func goToPage(index: Int) throws
    func applyReaderEvent(_ event: Data) throws
    func replaceAnnotations(_ annotations: [Data]) throws
    func undo() throws
    func redo() throws
    func exportAnnotatedCopy(originalURL: URL, annotations: [Data],
                             to destination: URL) async throws
}

@MainActor public protocol MnemosyneReaderFacade: AnyObject {
    func openCached(documentID: UUID, versionID: String) async throws
    func installDownloadedOriginal(from temporaryURL: URL, documentID: UUID,
                                   versionID: String) async throws
    func downloadState(documentID: UUID, versionID: String) throws -> MnemosyneDownloadState
    func readerContext() throws -> Data
    func selectedText() throws -> String?
    /// Accepts only a server-verified TextAnchor for the currently selected page.
    /// Passing nil clears the anchor; PDFKit selection changes clear it automatically.
    func setVerifiedSelectionAnchor(_ anchor: Data?) throws
    func search(_ text: String) throws -> [Data]
    func tableOfContents() throws -> Data
    func goToPage(_ index: Int) throws
    func applyReaderEvent(_ event: Data) throws
    func approveAnnotationSuggestion(_ event: Data) throws -> Data
    func commitLocalEdit(_ mutation: Data) throws
    func addPermanentAnnotation(_ draft: Data, mutationID: UUID) throws -> Data
    func deleteAnnotation(documentID: UUID, versionID: String, annotationID: UUID,
                          pageIndex: Int, kind: String, mutationID: UUID) throws -> Data
    func annotations(documentID: UUID, versionID: String) throws -> [Data]
    func originalVersionID(documentID: UUID) throws -> String?
    func receivedCursor(documentID: UUID, versionID: String) throws -> String?
    func goTo(_ event: Data) throws
    func flash(_ event: Data) throws
    func undo() throws
    func redo() throws
    func pendingMutations(limit: Int) throws -> [Data]
    func failedMutations() throws -> [Data]
    func markMutationFailed(_ mutationID: UUID, reason: String) throws
    func retryMutation(_ mutationID: UUID) throws
    func applySyncReceipts(_ receipts: Data) throws
    func applyRemotePage(_ changesAndCursor: Data) throws
    func exportAnnotatedCopy(to destination: URL) async throws
}

/// Local persistence boundary. Implementations commit each edit and its
/// outbox entry together, and apply remote records and their cursor together.
@MainActor public protocol MnemosyneLocalStore: AnyObject {
    func installOriginal(from temporaryURL: URL, documentID: UUID,
                         versionID: String) throws -> URL
    func cachedOriginalURL(documentID: UUID, versionID: String) throws -> URL?
    func cachedVersionID(documentID: UUID) throws -> String?
    func readerContext(documentID: UUID, versionID: String) throws -> Data?
    func saveReaderContext(_ context: Data, documentID: UUID,
                           versionID: String) throws
    func annotations(documentID: UUID, versionID: String) throws -> [Data]
    func commitEditAndOutbox(_ mutation: Data) throws
    func commitApprovedEvent(_ eventID: String, mutation: Data) throws -> Data
    func pendingMutations(limit: Int) throws -> [Data]
    func failedMutations() throws -> [Data]
    func markMutationFailed(_ mutationID: UUID, reason: String) throws
    func retryMutation(_ mutationID: UUID) throws
    func commitReceipts(_ receipts: Data) throws
    func commitChangesAndCursor(_ page: Data) throws
    func clientID() throws -> UUID
    func receivedCursor(documentID: UUID, versionID: String) throws -> String?
    func baseRevision(annotationID: UUID, documentID: UUID,
                      versionID: String) throws -> Int
}

/// JSON-backed local store. A single atomically replaced state file contains
/// the annotation projection, sync receipts, cursors, read positions, and
/// outbox. Original PDFs are installed as separate immutable cache files.
@MainActor public final class FileMnemosyneLocalStore: MnemosyneLocalStore {
    private struct CachedDocument: Codable {
        var versionID: String
        var fileName: String
    }

    private struct StoredMutation: Codable {
        enum Status: String, Codable { case pending, failed }
        var mutationID: String
        var documentID: String
        var versionID: String
        var annotationID: String
        var operation: String
        var data: Data
        var status: Status
        var failureReason: String?
    }

    private struct State: Codable {
        var schemaVersion = 1
        var clientID = UUID().uuidString.lowercased()
        var documents: [String: CachedDocument] = [:]
        var currentVersions: [String: String] = [:]
        var contexts: [String: Data] = [:]
        var remoteAnnotations: [String: [String: Data]] = [:]
        var outbox: [StoredMutation] = []
        var completedMutations: [String: Data] = [:]
        var acceptedEventIDs: [String: Data]? = [:]
        var cursors: [String: String] = [:]
        var receipts: [Data] = []
    }

    fileprivate struct MutationFields {
        var mutationID: UUID
        var documentID: UUID
        var versionID: String
        var annotationID: UUID
        var operation: String
        var baseRevision: Int
        var annotation: Data?
        var canonicalData: Data
    }

    private let rootDirectory: URL
    private let stateURL: URL
    private let fileManager = FileManager.default
    private var state: State

    public init(rootDirectory: URL) throws {
        self.rootDirectory = rootDirectory
        self.stateURL = rootDirectory.appendingPathComponent("reader-state-v1.json")
        try FileManager.default.createDirectory(at: rootDirectory, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(
            at: rootDirectory.appendingPathComponent("originals", isDirectory: true),
            withIntermediateDirectories: true
        )
        if FileManager.default.fileExists(atPath: stateURL.path) {
            let data = try Data(contentsOf: stateURL)
            let decoded = try JSONDecoder().decode(State.self, from: data)
            guard decoded.schemaVersion == 1 else { throw MnemosyneReaderError.malformedContractData }
            state = decoded
        } else {
            state = State()
        }
    }

    public static func applicationSupportStore() throws -> FileMnemosyneLocalStore {
        guard let support = FileManager.default.urls(for: .applicationSupportDirectory,
                                                      in: .userDomainMask).first else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try FileMnemosyneLocalStore(
            rootDirectory: support.appendingPathComponent("Mnemosyne/Reader", isDirectory: true)
        )
    }

    public func installOriginal(from temporaryURL: URL, documentID: UUID,
                                versionID: String) throws -> URL {
        guard Self.isValidVersionID(versionID) else { throw MnemosyneReaderError.invalidVersion }
        guard try Self.sha256(of: temporaryURL) == String(versionID.dropFirst("sha256:".count)) else {
            throw MnemosyneReaderError.sourceHashMismatch
        }

        let fileName = "\(documentID.uuidString.lowercased())-\(versionID.dropFirst(7)).pdf"
        let originals = rootDirectory.appendingPathComponent("originals", isDirectory: true)
        let destination = originals.appendingPathComponent(fileName)
        if fileManager.fileExists(atPath: destination.path) {
            guard try Self.sha256(of: destination) == String(versionID.dropFirst(7)) else {
                throw MnemosyneReaderError.sourceHashMismatch
            }
            try withTransaction {
                state.documents[Self.key(documentID, versionID)] = CachedDocument(versionID: versionID,
                                                                                    fileName: fileName)
                state.currentVersions[documentID.uuidString.lowercased()] = versionID
            }
            return destination
        }

        let staging = originals.appendingPathComponent(".\(UUID().uuidString).partial")
        try fileManager.copyItem(at: temporaryURL, to: staging)
        do {
            guard try Self.sha256(of: staging) == String(versionID.dropFirst(7)) else {
                throw MnemosyneReaderError.sourceHashMismatch
            }
            try fileManager.moveItem(at: staging, to: destination)
            try withTransaction {
                state.documents[Self.key(documentID, versionID)] = CachedDocument(versionID: versionID,
                                                                                    fileName: fileName)
                state.currentVersions[documentID.uuidString.lowercased()] = versionID
            }
            return destination
        } catch {
            try? fileManager.removeItem(at: staging)
            if fileManager.fileExists(atPath: destination.path) {
                try? fileManager.removeItem(at: destination)
            }
            throw error
        }
    }

    public func cachedOriginalURL(documentID: UUID, versionID: String) throws -> URL? {
        guard Self.isValidVersionID(versionID),
              let cached = state.documents[Self.key(documentID, versionID)],
              cached.versionID == versionID else { return nil }
        let url = rootDirectory.appendingPathComponent("originals", isDirectory: true)
            .appendingPathComponent(cached.fileName)
        guard fileManager.fileExists(atPath: url.path) else { return nil }
        guard try Self.sha256(of: url) == String(versionID.dropFirst(7)) else {
            throw MnemosyneReaderError.sourceHashMismatch
        }
        return url
    }

    public func cachedVersionID(documentID: UUID) throws -> String? {
        state.currentVersions[documentID.uuidString.lowercased()]
    }

    public func readerContext(documentID: UUID, versionID: String) throws -> Data? {
        state.contexts[Self.key(documentID, versionID)]
    }

    public func saveReaderContext(_ context: Data, documentID: UUID,
                                  versionID: String) throws {
        let object = try Self.object(context)
        guard Self.hasExactlyKeys(object, ["document_id", "version_id", "page_index", "viewport_rect",
                                           "selection", "content_language", "response_language"]),
              object["document_id"] as? String == documentID.uuidString.lowercased(),
              object["version_id"] as? String == versionID,
              let pageIndex = object["page_index"] as? Int,
              pageIndex >= 0, pageIndex <= 9_007_199_254_740_991 else {
            throw MnemosyneReaderError.documentMismatch
        }
        guard let viewport = object["viewport_rect"] as? [NSNumber], viewport.count == 4,
              viewport.allSatisfy({ $0.doubleValue.isFinite }),
              viewport[2].doubleValue > 0, viewport[3].doubleValue > 0,
              let contentLanguage = object["content_language"] as? String,
              Self.isValidLanguageTag(contentLanguage),
              let responseLanguage = object["response_language"] as? String,
              Self.isValidLanguageTag(responseLanguage),
              let selection = object["selection"] else {
            throw MnemosyneReaderError.malformedContractData
        }
        if let anchor = selection as? [String: Any] {
            try Self.checkTextAnchor(anchor, documentID: documentID,
                                     versionID: versionID, pageIndex: pageIndex)
        } else if !(selection is NSNull) {
            throw MnemosyneReaderError.malformedContractData
        }
        try withTransaction {
            state.contexts[Self.key(documentID, versionID)] = try Self.canonicalJSON(object)
        }
    }

    private static func isValidLanguageTag(_ value: String) -> Bool {
        value.range(of: #"^(und|[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)$"#,
                    options: .regularExpression) != nil
    }

    public func annotations(documentID: UUID, versionID: String) throws -> [Data] {
        let docKey = Self.key(documentID, versionID)
        var visible = state.remoteAnnotations[docKey] ?? [:]
        for mutation in state.outbox where mutation.documentID == documentID.uuidString.lowercased()
            && mutation.versionID == versionID {
            let object = try Self.object(mutation.data)
            if mutation.operation == "delete" {
                visible.removeValue(forKey: mutation.annotationID)
            } else if let draft = object["annotation"] as? [String: Any] {
                visible[mutation.annotationID] = try Self.canonicalJSON(draft)
            }
        }
        return visible.keys.sorted().compactMap { id in
            guard let data = visible[id] else { return nil }
            if let object = try? Self.object(data), object["deleted"] as? Bool == true { return nil }
            return data
        }
    }

    public func commitEditAndOutbox(_ mutation: Data) throws {
        let fields = try Self.parseMutation(mutation)
        let mutationID = fields.mutationID.uuidString.lowercased()
        if let completed = state.completedMutations[mutationID] {
            guard completed == fields.canonicalData else { throw MnemosyneReaderError.idempotencyMismatch }
            return
        }
        if let existing = state.outbox.first(where: { $0.mutationID == mutationID }) {
            guard existing.data == fields.canonicalData else { throw MnemosyneReaderError.idempotencyMismatch }
            return
        }
        try withTransaction {
            state.outbox.append(StoredMutation(
                mutationID: mutationID,
                documentID: fields.documentID.uuidString.lowercased(),
                versionID: fields.versionID,
                annotationID: fields.annotationID.uuidString.lowercased(),
                operation: fields.operation,
                data: fields.canonicalData,
                status: .pending,
                failureReason: nil
            ))
        }
    }

    public func commitApprovedEvent(_ eventID: String, mutation: Data) throws -> Data {
        guard Self.isValidEventID(eventID) else { throw MnemosyneReaderError.malformedContractData }
        let fields = try Self.parseMutation(mutation)
        let mutationID = fields.mutationID.uuidString.lowercased()
        let accepted = state.acceptedEventIDs ?? [:]
        guard fields.operation == "upsert", fields.annotation != nil else {
            throw MnemosyneReaderError.malformedContractData
        }

        if let acceptedMutation = accepted[eventID] {
            let acceptedFields = try Self.parseMutation(acceptedMutation)
            guard Self.sameApprovedMutation(acceptedFields, fields) else {
                throw MnemosyneReaderError.idempotencyMismatch
            }
            return acceptedMutation
        }
        guard !(try accepted.values.contains(where: {
            try Self.parseMutation($0).mutationID.uuidString.lowercased() == mutationID
        })) else {
            throw MnemosyneReaderError.idempotencyMismatch
        }

        if let completed = state.completedMutations[mutationID] {
            guard completed == fields.canonicalData else { throw MnemosyneReaderError.idempotencyMismatch }
            try withTransaction {
                var updated = state.acceptedEventIDs ?? [:]
                updated[eventID] = fields.canonicalData
                state.acceptedEventIDs = updated
            }
            return completed
        }
        if let existing = state.outbox.first(where: { $0.mutationID == mutationID }) {
            guard existing.data == fields.canonicalData else { throw MnemosyneReaderError.idempotencyMismatch }
            try withTransaction {
                var updated = state.acceptedEventIDs ?? [:]
                updated[eventID] = fields.canonicalData
                state.acceptedEventIDs = updated
            }
            return existing.data
        }

        try withTransaction {
            var updated = state.acceptedEventIDs ?? [:]
            updated[eventID] = fields.canonicalData
            state.acceptedEventIDs = updated
            state.outbox.append(StoredMutation(
                mutationID: mutationID,
                documentID: fields.documentID.uuidString.lowercased(),
                versionID: fields.versionID,
                annotationID: fields.annotationID.uuidString.lowercased(),
                operation: fields.operation,
                data: fields.canonicalData,
                status: .pending,
                failureReason: nil
            ))
        }
        return fields.canonicalData
    }

    public func pendingMutations(limit: Int) throws -> [Data] {
        guard limit > 0 else { return [] }
        return state.outbox.filter { $0.status == .pending }.prefix(limit).map(\.data)
    }

    public func failedMutations() throws -> [Data] {
        state.outbox.filter { $0.status == .failed }.map(\.data)
    }

    public func markMutationFailed(_ mutationID: UUID, reason: String) throws {
        let key = mutationID.uuidString.lowercased()
        guard let index = state.outbox.firstIndex(where: { $0.mutationID == key }) else {
            throw MnemosyneReaderError.mutationNotFound
        }
        try withTransaction {
            state.outbox[index].status = .failed
            state.outbox[index].failureReason = String(reason.prefix(1000))
        }
    }

    public func retryMutation(_ mutationID: UUID) throws {
        let key = mutationID.uuidString.lowercased()
        guard let index = state.outbox.firstIndex(where: { $0.mutationID == key }) else {
            throw MnemosyneReaderError.mutationNotFound
        }
        try withTransaction {
            state.outbox[index].status = .pending
            state.outbox[index].failureReason = nil
        }
    }

    public func commitReceipts(_ receipts: Data) throws {
        let receipt = try Self.object(receipts)
        guard receipt["contract_version"] as? String == "0.1.0",
              let documentID = UUID(uuidString: receipt["document_id"] as? String ?? ""),
              let versionID = receipt["version_id"] as? String,
              Self.isValidVersionID(versionID),
              let results = receipt["results"] as? [[String: Any]] else {
            throw MnemosyneReaderError.malformedContractData
        }
        let canonical = try Self.canonicalJSON(receipt)
        try withTransaction {
            state.receipts.append(canonical)
            if state.receipts.count > 64 { state.receipts.removeFirst(state.receipts.count - 64) }

            for result in results {
                guard let id = UUID(uuidString: result["client_mutation_id"] as? String ?? "") else {
                    throw MnemosyneReaderError.malformedContractData
                }
                guard let index = state.outbox.firstIndex(where: { $0.mutationID == id.uuidString.lowercased() }) else {
                    continue
                }
                guard state.outbox[index].documentID == documentID.uuidString.lowercased(),
                      state.outbox[index].versionID == versionID else {
                    throw MnemosyneReaderError.documentMismatch
                }
                if let current = result["current"] as? [String: Any] {
                    try Self.checkAnnotation(current, documentID: documentID, versionID: versionID)
                    let annotationID = current["annotation_id"] as! String
                    state.remoteAnnotations[Self.key(documentID, versionID), default: [:]][annotationID] =
                        try Self.canonicalJSON(current)
                }
                if result["status"] as? String == "applied" {
                    let completed = state.outbox.remove(at: index)
                    state.completedMutations[completed.mutationID] = completed.data
                    if state.completedMutations.count > 1024,
                       let first = state.completedMutations.keys.sorted().first {
                        state.completedMutations.removeValue(forKey: first)
                    }
                    if result["current"] is NSNull {
                        state.remoteAnnotations[Self.key(documentID, versionID)]?
                            .removeValue(forKey: completed.annotationID)
                    }
                } else {
                    state.outbox[index].status = .failed
                    state.outbox[index].failureReason = result["code"] as? String ?? "server_rejected"
                }
            }
        }
    }

    public func commitChangesAndCursor(_ page: Data) throws {
        let object = try Self.object(page)
        guard object["contract_version"] as? String == "0.1.0",
              let documentID = UUID(uuidString: object["document_id"] as? String ?? ""),
              let versionID = object["version_id"] as? String,
              Self.isValidVersionID(versionID),
              let cursor = object["next_cursor"] as? String, !cursor.isEmpty,
              let changes = object["changes"] as? [[String: Any]] else {
            throw MnemosyneReaderError.malformedContractData
        }
        let key = Self.key(documentID, versionID)
        try withTransaction {
            var remote = state.remoteAnnotations[key] ?? [:]
            let protectedIDs = Set(state.outbox.filter {
                $0.documentID == documentID.uuidString.lowercased() && $0.versionID == versionID
            }.map(\.annotationID))
            for change in changes {
                try Self.checkAnnotation(change, documentID: documentID, versionID: versionID)
                let annotationID = change["annotation_id"] as! String
                guard !protectedIDs.contains(annotationID) else { continue }
                if let existing = remote[annotationID],
                   let existingObject = try? Self.object(existing),
                   let oldRevision = existingObject["server_revision"] as? Int,
                   let newRevision = change["server_revision"] as? Int,
                   newRevision < oldRevision { continue }
                remote[annotationID] = try Self.canonicalJSON(change)
            }
            state.remoteAnnotations[key] = remote
            state.cursors[key] = cursor
        }
    }

    public func clientID() throws -> UUID {
        guard let id = UUID(uuidString: state.clientID) else { throw MnemosyneReaderError.malformedContractData }
        return id
    }

    public func receivedCursor(documentID: UUID, versionID: String) throws -> String? {
        state.cursors[Self.key(documentID, versionID)]
    }

    public func baseRevision(annotationID: UUID, documentID: UUID,
                             versionID: String) throws -> Int {
        guard let data = state.remoteAnnotations[Self.key(documentID, versionID)]?[annotationID.uuidString.lowercased()],
              let object = try? Self.object(data) else { return 0 }
        return object["server_revision"] as? Int ?? 0
    }

    private func persist() throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try encoder.encode(state).write(to: stateURL, options: .atomic)
    }

    private func withTransaction<T>(_ changes: () throws -> T) throws -> T {
        let previous = state
        do {
            let result = try changes()
            try persist()
            return result
        } catch {
            state = previous
            throw error
        }
    }

    private static func key(_ documentID: UUID, _ versionID: String) -> String {
        "\(documentID.uuidString.lowercased())|\(versionID)"
    }

    fileprivate static func isValidVersionID(_ value: String) -> Bool {
        guard value.hasPrefix("sha256:"), value.count == 71 else { return false }
        return value.dropFirst(7).allSatisfy { $0.isHexDigit && !$0.isUppercase }
    }

    private static func isValidEventID(_ value: String) -> Bool {
        let parts = value.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, !parts[0].isEmpty, parts[0].count <= 256,
              parts[0].allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_" || $0 == "-") }),
              let sequence = Int(parts[1]), sequence > 0,
              String(sequence) == String(parts[1]) else { return false }
        return true
    }

    private static func sameApprovedMutation(_ lhs: MutationFields,
                                             _ rhs: MutationFields) -> Bool {
        lhs.mutationID == rhs.mutationID && lhs.documentID == rhs.documentID &&
            lhs.versionID == rhs.versionID && lhs.annotationID == rhs.annotationID &&
            lhs.operation == "upsert" && rhs.operation == "upsert" &&
            lhs.annotation == rhs.annotation
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

    fileprivate static func object(_ data: Data) throws -> [String: Any] {
        guard let result = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw MnemosyneReaderError.malformedContractData
        }
        return result
    }

    fileprivate static func canonicalJSON(_ object: Any) throws -> Data {
        try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .fragmentsAllowed])
    }

    fileprivate static func parseMutation(_ data: Data) throws -> MutationFields {
        let object = try Self.object(data)
        guard let mutationID = UUID(uuidString: object["client_mutation_id"] as? String ?? ""),
              let clientID = UUID(uuidString: object["client_id"] as? String ?? ""),
              let documentID = UUID(uuidString: object["document_id"] as? String ?? ""),
              let versionID = object["version_id"] as? String, isValidVersionID(versionID),
              let annotationID = UUID(uuidString: object["annotation_id"] as? String ?? ""),
              let operation = object["operation"] as? String, ["upsert", "delete"].contains(operation),
              let baseRevision = object["base_revision"] as? Int, baseRevision >= 0,
              object["created_at"] is String else {
            throw MnemosyneReaderError.malformedContractData
        }
        _ = clientID
        var annotationData: Data?
        if operation == "upsert" {
            guard let annotation = object["annotation"] as? [String: Any] else {
                throw MnemosyneReaderError.malformedContractData
            }
            try checkDraft(annotation, documentID: documentID, versionID: versionID,
                           annotationID: annotationID)
            annotationData = try canonicalJSON(annotation)
        }
        return MutationFields(mutationID: mutationID, documentID: documentID,
                              versionID: versionID, annotationID: annotationID,
                              operation: operation, baseRevision: baseRevision,
                              annotation: annotationData,
                              canonicalData: try canonicalJSON(object))
    }

    fileprivate static func checkDraft(_ object: [String: Any], documentID: UUID,
                                   versionID: String, annotationID: UUID) throws {
        guard object["annotation_id"] as? String == annotationID.uuidString.lowercased(),
              object["document_id"] as? String == documentID.uuidString.lowercased(),
              object["version_id"] as? String == versionID,
              let pageIndex = object["page_index"] as? Int, pageIndex >= 0,
              let kind = object["kind"] as? String,
              ["highlight", "note", "bookmark", "ink"].contains(kind),
              Self.hasExactlyKeys(object, ["annotation_id", "document_id", "version_id", "page_index", "kind", "payload"]),
              let payload = object["payload"] as? [String: Any] else {
            throw MnemosyneReaderError.documentMismatch
        }
        switch kind {
        case "highlight":
            guard Self.hasExactlyKeys(payload, ["anchor", "color"]),
                  Self.validColor(payload["color"] as? String),
                  let anchor = payload["anchor"] as? [String: Any] else {
                throw MnemosyneReaderError.malformedContractData
            }
            try Self.checkTextAnchor(anchor, documentID: documentID, versionID: versionID,
                                     pageIndex: pageIndex)
        case "note":
            guard Self.hasExactlyKeys(payload, ["position", "body", "anchor"]),
                  let position = payload["position"] as? [NSNumber], position.count == 2,
                  position.allSatisfy({ $0.doubleValue.isFinite }),
                  let body = payload["body"] as? String, !body.isEmpty, body.count <= 20_000 else {
                throw MnemosyneReaderError.malformedContractData
            }
            if let anchor = payload["anchor"] as? [String: Any] {
                try Self.checkTextAnchor(anchor, documentID: documentID, versionID: versionID,
                                         pageIndex: pageIndex)
            } else if !(payload["anchor"] is NSNull) {
                throw MnemosyneReaderError.malformedContractData
            }
        case "bookmark":
            guard Self.hasExactlyKeys(payload, ["label"]),
                  let label = payload["label"] as? String, label.count <= 240 else {
                throw MnemosyneReaderError.malformedContractData
            }
        case "ink":
            try Self.checkInkPayload(payload)
        default:
            throw MnemosyneReaderError.malformedContractData
        }
    }

    fileprivate static func checkAnnotation(_ object: [String: Any], documentID: UUID,
                                        versionID: String) throws {
        guard let annotationID = UUID(uuidString: object["annotation_id"] as? String ?? ""),
              object["document_id"] as? String == documentID.uuidString.lowercased(),
              object["version_id"] as? String == versionID,
              let pageIndex = object["page_index"] as? Int, pageIndex >= 0,
              let kind = object["kind"] as? String,
              let revision = object["server_revision"] as? Int, revision > 0,
              let updatedAt = object["updated_at"] as? String,
              ISO8601DateFormatter().date(from: updatedAt) != nil,
              let deleted = object["deleted"] as? Bool,
              Self.hasExactlyKeys(object, ["annotation_id", "document_id", "version_id", "page_index",
                                           "kind", "server_revision", "updated_at", "deleted",
                                           "deleted_at", "payload"]) else {
            throw MnemosyneReaderError.documentMismatch
        }
        if deleted {
            guard let deletedAt = object["deleted_at"] as? String,
                  ISO8601DateFormatter().date(from: deletedAt) != nil,
                  object["payload"] is NSNull else {
                throw MnemosyneReaderError.malformedContractData
            }
            return
        }
        guard object["deleted_at"] is NSNull,
              let payload = object["payload"] as? [String: Any] else {
            throw MnemosyneReaderError.malformedContractData
        }
        let draft = [
            "annotation_id": annotationID.uuidString.lowercased(),
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "page_index": pageIndex,
            "kind": kind,
            "payload": payload
        ] as [String: Any]
        try checkDraft(draft, documentID: documentID, versionID: versionID,
                       annotationID: annotationID)
    }

    static func checkTextAnchor(_ anchor: [String: Any], documentID: UUID,
                                        versionID: String, pageIndex: Int) throws {
        guard Self.hasExactlyKeys(anchor, ["document_id", "version_id", "page_index", "parse_revision",
                                           "text_sha256", "start_scalar", "end_scalar", "quote", "rects"]),
              anchor["document_id"] as? String == documentID.uuidString.lowercased(),
              anchor["version_id"] as? String == versionID,
              anchor["page_index"] as? Int == pageIndex,
              let parseRevision = anchor["parse_revision"] as? String, !parseRevision.isEmpty,
              let textHash = anchor["text_sha256"] as? String, textHash.count == 64,
              textHash.allSatisfy({ $0.isHexDigit && !$0.isUppercase }),
              let start = anchor["start_scalar"] as? Int, start >= 0, start <= 9_007_199_254_740_991,
              let end = anchor["end_scalar"] as? Int, end > start, end <= 9_007_199_254_740_991,
              let quote = anchor["quote"] as? String, !quote.isEmpty,
              let rects = anchor["rects"] as? [[NSNumber]], !rects.isEmpty,
              rects.allSatisfy({ values in
                  values.count == 4 && values.allSatisfy({ $0.doubleValue.isFinite }) &&
                      values[2].doubleValue > 0 && values[3].doubleValue > 0
              }) else {
            throw MnemosyneReaderError.malformedContractData
        }
    }

    private static func checkInkPayload(_ payload: [String: Any]) throws {
        guard Self.hasExactlyKeys(payload, ["strokes"]),
              let strokes = payload["strokes"] as? [[String: Any]], !strokes.isEmpty else {
            throw MnemosyneReaderError.malformedContractData
        }
        for stroke in strokes {
            guard Self.hasExactlyKeys(stroke, ["stroke_id", "tool", "color", "width_pt", "points"]),
                  UUID(uuidString: stroke["stroke_id"] as? String ?? "") != nil,
                  let tool = stroke["tool"] as? String, ["pen", "highlighter"].contains(tool),
                  Self.validColor(stroke["color"] as? String),
                  let width = (stroke["width_pt"] as? NSNumber)?.doubleValue,
                  width.isFinite, width > 0, width <= 100,
                  let points = stroke["points"] as? [[String: Any]], !points.isEmpty else {
                throw MnemosyneReaderError.malformedContractData
            }
            for point in points {
                guard Self.hasExactlyKeys(point, ["x", "y", "pressure", "t_ms"]),
                      let x = (point["x"] as? NSNumber)?.doubleValue, x.isFinite,
                      let y = (point["y"] as? NSNumber)?.doubleValue, y.isFinite,
                      let pressure = (point["pressure"] as? NSNumber)?.doubleValue,
                      pressure.isFinite, (0...1).contains(pressure),
                      let time = point["t_ms"] as? Int, time >= 0,
                      time <= 9_007_199_254_740_991 else {
                    throw MnemosyneReaderError.malformedContractData
                }
            }
        }
    }

    private static func validColor(_ value: String?) -> Bool {
        guard let value, value.hasPrefix("#"), value.count == 9 else { return false }
        return value.dropFirst().allSatisfy(\.isHexDigit)
    }

    private static func hasExactlyKeys(_ object: [String: Any], _ keys: Set<String>) -> Bool {
        Set(object.keys) == keys
    }
}

/// Facade shared by UNIT-04's app shell and the injected PDFKit engine.
/// Annotation edits are durable before this facade reports success; network
/// work remains outside this type.
@MainActor public final class PersistentMnemosyneReaderFacade: MnemosyneReaderFacade {
    private let localStore: any MnemosyneLocalStore
    private let engine: any MnemosyneReaderEngine
    private var activeDocument: (id: UUID, versionID: String)?
    private var verifiedSelectionAnchor: Data?

    public init(localStore: any MnemosyneLocalStore, engine: any MnemosyneReaderEngine) {
        self.localStore = localStore
        self.engine = engine
        engine.setLocalEditHandler { [weak self] edit in
            try self?.commit(edit)
        }
        engine.setSelectionChangeHandler { [weak self] in
            self?.verifiedSelectionAnchor = nil
        }
    }

    public func openCached(documentID: UUID, versionID: String) async throws {
        guard let url = try localStore.cachedOriginalURL(documentID: documentID, versionID: versionID) else {
            throw MnemosyneReaderError.cacheMissing
        }
        let context = try localStore.readerContext(documentID: documentID, versionID: versionID)
        let restoredAnchor = try Self.selectionAnchor(in: context, documentID: documentID,
                                                      versionID: versionID)
        let annotations = try localStore.annotations(documentID: documentID, versionID: versionID)
        try await engine.openDocument(at: url, documentID: documentID, versionID: versionID,
                                      restoring: context, annotations: annotations)
        activeDocument = (documentID, versionID)
        verifiedSelectionAnchor = restoredAnchor
    }

    public func installDownloadedOriginal(from temporaryURL: URL, documentID: UUID,
                                          versionID: String) async throws {
        _ = try localStore.installOriginal(from: temporaryURL, documentID: documentID,
                                           versionID: versionID)
    }

    public func downloadState(documentID: UUID, versionID: String) throws -> MnemosyneDownloadState {
        do {
            return try localStore.cachedOriginalURL(documentID: documentID, versionID: versionID) == nil
                ? .missing : .cached
        } catch {
            return .invalid
        }
    }

    public func readerContext() throws -> Data {
        guard let activeDocument else { throw MnemosyneReaderError.cacheMissing }
        var context = try FileMnemosyneLocalStore.object(engine.currentReaderContext())
        guard context["document_id"] as? String == activeDocument.id.uuidString.lowercased(),
              context["version_id"] as? String == activeDocument.versionID,
              let pageIndex = context["page_index"] as? Int, pageIndex >= 0 else {
            throw MnemosyneReaderError.documentMismatch
        }
        if let anchorData = verifiedSelectionAnchor {
            let anchor = try FileMnemosyneLocalStore.object(anchorData)
            if anchor["page_index"] as? Int == pageIndex {
                try FileMnemosyneLocalStore.checkTextAnchor(
                    anchor, documentID: activeDocument.id,
                    versionID: activeDocument.versionID, pageIndex: pageIndex
                )
                context["selection"] = anchor
            } else {
                verifiedSelectionAnchor = nil
                context["selection"] = NSNull()
            }
        } else {
            context["selection"] = NSNull()
        }
        let encoded = try FileMnemosyneLocalStore.canonicalJSON(context)
        try localStore.saveReaderContext(encoded, documentID: activeDocument.id,
                                         versionID: activeDocument.versionID)
        return encoded
    }

    /// Returns the current raw PDF selection and clears any prior verified anchor.
    /// The caller must ask the server to verify a new anchor before setting it again.
    public func selectedText() throws -> String? {
        guard activeDocument != nil else { throw MnemosyneReaderError.cacheMissing }
        defer { verifiedSelectionAnchor = nil }
        return try engine.selectedText()
    }

    public func setVerifiedSelectionAnchor(_ anchorData: Data?) throws {
        guard let activeDocument else { throw MnemosyneReaderError.cacheMissing }
        guard let anchorData else {
            verifiedSelectionAnchor = nil
            return
        }
        let context = try FileMnemosyneLocalStore.object(engine.currentReaderContext())
        guard context["document_id"] as? String == activeDocument.id.uuidString.lowercased(),
              context["version_id"] as? String == activeDocument.versionID,
              let pageIndex = context["page_index"] as? Int, pageIndex >= 0 else {
            throw MnemosyneReaderError.documentMismatch
        }
        let anchor = try FileMnemosyneLocalStore.object(anchorData)
        try FileMnemosyneLocalStore.checkTextAnchor(
            anchor, documentID: activeDocument.id,
            versionID: activeDocument.versionID, pageIndex: pageIndex
        )
        verifiedSelectionAnchor = try FileMnemosyneLocalStore.canonicalJSON(anchor)
    }

    private static func selectionAnchor(in contextData: Data?, documentID: UUID,
                                        versionID: String) throws -> Data? {
        guard let contextData else { return nil }
        let context = try FileMnemosyneLocalStore.object(contextData)
        guard context["document_id"] as? String == documentID.uuidString.lowercased(),
              context["version_id"] as? String == versionID,
              let pageIndex = context["page_index"] as? Int, pageIndex >= 0,
              let selection = context["selection"] else {
            throw MnemosyneReaderError.documentMismatch
        }
        guard !(selection is NSNull) else { return nil }
        guard let anchor = selection as? [String: Any] else {
            throw MnemosyneReaderError.malformedContractData
        }
        try FileMnemosyneLocalStore.checkTextAnchor(
            anchor, documentID: documentID, versionID: versionID, pageIndex: pageIndex
        )
        return try FileMnemosyneLocalStore.canonicalJSON(anchor)
    }

    public func search(_ text: String) throws -> [Data] {
        guard activeDocument != nil, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return []
        }
        return try engine.search(text: text)
    }

    public func tableOfContents() throws -> Data {
        guard activeDocument != nil else { throw MnemosyneReaderError.cacheMissing }
        return try engine.tableOfContents()
    }

    public func goToPage(_ index: Int) throws {
        guard activeDocument != nil, index >= 0 else { throw MnemosyneReaderError.malformedContractData }
        try engine.goToPage(index: index)
    }

    public func applyReaderEvent(_ event: Data) throws {
        guard let activeDocument else { throw MnemosyneReaderError.cacheMissing }
        let object = try FileMnemosyneLocalStore.object(event)
        guard object["contract_version"] as? String == "0.1.0",
              let type = object["type"] as? String,
              ["reader.goto", "reader.flash", "reader.highlight", "reader.annotate"].contains(type),
              let payload = object["payload"] as? [String: Any] else {
            throw MnemosyneReaderError.malformedContractData
        }
        if type == "reader.annotate" {
            guard payload["requires_confirmation"] as? Bool == true,
                  UUID(uuidString: payload["citation_id"] as? String ?? "") != nil,
                  UUID(uuidString: payload["suggested_mutation_id"] as? String ?? "") != nil,
                  let annotation = payload["annotation"] as? [String: Any],
                  annotation["document_id"] as? String == activeDocument.id.uuidString.lowercased(),
                  annotation["version_id"] as? String == activeDocument.versionID else {
                throw MnemosyneReaderError.documentMismatch
            }
        } else {
            guard let target = payload["target"] as? [String: Any],
                  target["document_id"] as? String == activeDocument.id.uuidString.lowercased(),
                  target["version_id"] as? String == activeDocument.versionID,
                  let pageIndex = target["page_index"] as? Int, pageIndex >= 0 else {
                throw MnemosyneReaderError.documentMismatch
            }
        }
        try engine.applyReaderEvent(event)
    }

    public func approveAnnotationSuggestion(_ event: Data) throws -> Data {
        guard let activeDocument else { throw MnemosyneReaderError.cacheMissing }
        let object = try FileMnemosyneLocalStore.object(event)
        guard object["contract_version"] as? String == "0.1.0",
              object["type"] as? String == "reader.annotate",
              let eventID = object["event_id"] as? String,
              let turnID = object["turn_id"] as? String,
              let sequence = object["seq"] as? Int, sequence > 0,
              eventID == "\(turnID):\(sequence)",
              let payload = object["payload"] as? [String: Any],
              payload["requires_confirmation"] as? Bool == true,
              UUID(uuidString: payload["citation_id"] as? String ?? "") != nil,
              let mutationID = UUID(uuidString: payload["suggested_mutation_id"] as? String ?? ""),
              let annotation = payload["annotation"] as? [String: Any],
              let annotationID = UUID(uuidString: annotation["annotation_id"] as? String ?? "") else {
            throw MnemosyneReaderError.malformedContractData
        }
        try FileMnemosyneLocalStore.checkDraft(annotation, documentID: activeDocument.id,
                                               versionID: activeDocument.versionID,
                                               annotationID: annotationID)
        let mutation = try makeMutation(documentID: activeDocument.id,
                                        versionID: activeDocument.versionID,
                                        annotationID: annotationID,
                                        operation: "upsert", draft: annotation,
                                        mutationID: mutationID)
        let accepted = try localStore.commitApprovedEvent(eventID, mutation: mutation)
        try engine.replaceAnnotations(localStore.annotations(documentID: activeDocument.id,
                                                              versionID: activeDocument.versionID))
        return accepted
    }

    public func commitLocalEdit(_ mutation: Data) throws {
        let fields = try FileMnemosyneLocalStore.parseMutation(mutation)
        try localStore.commitEditAndOutbox(mutation)
        if let activeDocument, activeDocument.id == fields.documentID,
           activeDocument.versionID == fields.versionID {
            try engine.replaceAnnotations(localStore.annotations(documentID: fields.documentID,
                                                                  versionID: fields.versionID))
        }
    }

    public func addPermanentAnnotation(_ draft: Data, mutationID: UUID = UUID()) throws -> Data {
        guard let activeDocument else { throw MnemosyneReaderError.cacheMissing }
        return try addPermanentAnnotation(draft, documentID: activeDocument.id,
                                          versionID: activeDocument.versionID,
                                          mutationID: mutationID)
    }

    public func deleteAnnotation(documentID: UUID, versionID: String, annotationID: UUID,
                                 pageIndex: Int, kind: String,
                                 mutationID: UUID = UUID()) throws -> Data {
        guard pageIndex >= 0, ["highlight", "note", "bookmark", "ink"].contains(kind) else {
            throw MnemosyneReaderError.malformedContractData
        }
        let mutation = try makeMutation(documentID: documentID, versionID: versionID,
                                        annotationID: annotationID, operation: "delete",
                                        draft: nil, mutationID: mutationID)
        try commitLocalEdit(mutation)
        return mutation
    }

    private func addPermanentAnnotation(_ draft: Data, documentID: UUID,
                                        versionID: String, mutationID: UUID) throws -> Data {
        let annotation = try FileMnemosyneLocalStore.object(draft)
        guard let annotationID = UUID(uuidString: annotation["annotation_id"] as? String ?? "") else {
            throw MnemosyneReaderError.malformedContractData
        }
        try FileMnemosyneLocalStore.checkDraft(annotation, documentID: documentID,
                                               versionID: versionID,
                                               annotationID: annotationID)
        let mutation = try makeMutation(documentID: documentID, versionID: versionID,
                                        annotationID: annotationID, operation: "upsert",
                                        draft: annotation, mutationID: mutationID)
        try commitLocalEdit(mutation)
        return mutation
    }

    private func makeMutation(documentID: UUID, versionID: String, annotationID: UUID,
                              operation: String, draft: [String: Any]?, mutationID: UUID) throws -> Data {
        var mutation: [String: Any] = [
            "client_mutation_id": mutationID.uuidString.lowercased(),
            "client_id": try localStore.clientID().uuidString.lowercased(),
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "annotation_id": annotationID.uuidString.lowercased(),
            "base_revision": try localStore.baseRevision(annotationID: annotationID,
                                                            documentID: documentID,
                                                            versionID: versionID),
            "created_at": ISO8601DateFormatter().string(from: Date()),
            "operation": operation
        ]
        if let draft { mutation["annotation"] = draft }
        return try FileMnemosyneLocalStore.canonicalJSON(mutation)
    }

    private func commit(_ edit: MnemosyneLocalAnnotationEdit) throws {
        guard FileMnemosyneLocalStore.isValidVersionID(edit.versionID), edit.pageIndex >= 0,
              ["highlight", "note", "bookmark", "ink"].contains(edit.kind) else {
            throw MnemosyneReaderError.malformedContractData
        }
        switch edit.operation {
        case .upsert:
            guard let draft = edit.draft else { throw MnemosyneReaderError.malformedContractData }
            let object = try FileMnemosyneLocalStore.object(draft)
            guard object["annotation_id"] as? String == edit.annotationID.uuidString.lowercased(),
                  object["page_index"] as? Int == edit.pageIndex,
                  object["kind"] as? String == edit.kind else {
                throw MnemosyneReaderError.documentMismatch
            }
            _ = try addPermanentAnnotation(draft, documentID: edit.documentID,
                                           versionID: edit.versionID, mutationID: edit.mutationID)
        case .delete:
            _ = try deleteAnnotation(documentID: edit.documentID, versionID: edit.versionID,
                                     annotationID: edit.annotationID, pageIndex: edit.pageIndex,
                                     kind: edit.kind, mutationID: edit.mutationID)
        }
    }

    public func annotations(documentID: UUID, versionID: String) throws -> [Data] {
        try localStore.annotations(documentID: documentID, versionID: versionID)
    }

    public func originalVersionID(documentID: UUID) throws -> String? {
        try localStore.cachedVersionID(documentID: documentID)
    }

    public func receivedCursor(documentID: UUID, versionID: String) throws -> String? {
        try localStore.receivedCursor(documentID: documentID, versionID: versionID)
    }

    public func goTo(_ event: Data) throws {
        let object = try FileMnemosyneLocalStore.object(event)
        guard object["type"] as? String == "reader.goto" else {
            throw MnemosyneReaderError.malformedContractData
        }
        try applyReaderEvent(event)
    }

    public func flash(_ event: Data) throws {
        let object = try FileMnemosyneLocalStore.object(event)
        guard object["type"] as? String == "reader.flash" else {
            throw MnemosyneReaderError.malformedContractData
        }
        try applyReaderEvent(event)
    }

    public func undo() throws { try engine.undo() }
    public func redo() throws { try engine.redo() }

    public func pendingMutations(limit: Int) throws -> [Data] {
        try localStore.pendingMutations(limit: limit)
    }

    public func failedMutations() throws -> [Data] { try localStore.failedMutations() }

    public func markMutationFailed(_ mutationID: UUID, reason: String) throws {
        try localStore.markMutationFailed(mutationID, reason: reason)
        if let activeDocument {
            try engine.replaceAnnotations(localStore.annotations(documentID: activeDocument.id,
                                                                  versionID: activeDocument.versionID))
        }
    }

    public func retryMutation(_ mutationID: UUID) throws {
        try localStore.retryMutation(mutationID)
    }

    public func applySyncReceipts(_ receipts: Data) throws {
        try localStore.commitReceipts(receipts)
        if let activeDocument {
            try engine.replaceAnnotations(localStore.annotations(documentID: activeDocument.id,
                                                                  versionID: activeDocument.versionID))
        }
    }

    public func applyRemotePage(_ changesAndCursor: Data) throws {
        try localStore.commitChangesAndCursor(changesAndCursor)
        if let activeDocument {
            try engine.replaceAnnotations(localStore.annotations(documentID: activeDocument.id,
                                                                  versionID: activeDocument.versionID))
        }
    }

    public func exportAnnotatedCopy(to destination: URL) async throws {
        guard let activeDocument,
              let originalURL = try localStore.cachedOriginalURL(documentID: activeDocument.id,
                                                                  versionID: activeDocument.versionID) else {
            throw MnemosyneReaderError.cacheMissing
        }
        guard originalURL.standardizedFileURL != destination.standardizedFileURL else {
            throw MnemosyneReaderError.exportWouldReplaceOriginal
        }
        let annotations = try localStore.annotations(documentID: activeDocument.id,
                                                       versionID: activeDocument.versionID)
        try await engine.exportAnnotatedCopy(originalURL: originalURL, annotations: annotations,
                                              to: destination)
    }
}

/// Registration requires a real local store and platform engine. There is no
/// silent no-op facade.
@MainActor public func makeReaderFacade(
    factory: (any MnemosyneLocalStore) throws -> any MnemosyneReaderFacade,
    localStore: any MnemosyneLocalStore
) throws -> any MnemosyneReaderFacade {
    try factory(localStore)
}
