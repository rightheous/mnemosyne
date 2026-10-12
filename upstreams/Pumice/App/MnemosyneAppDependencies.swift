import Combine
import CryptoKit
import Foundation
import PumiceCore

/// UNIT-04 owns network and screens; it calls Reader facade instead of its DB.
@MainActor protocol MnemosyneSyncWorker: AnyObject {
    func synchronize() async throws
}

/// UNIT-03 localStore owns these durable sync facts. The worker never opens or edits its DB.
@MainActor protocol MnemosyneSyncStateStore: AnyObject {
    func syncCursor(documentID: UUID, versionID: String) throws -> String?
    func applyRemoteSnapshot(_ snapshot: Data) throws
}

/// Native seq includes frames without metadata.mnemosyne and must survive process restarts.
@MainActor protocol MnemosyneTutorCheckpointStore: AnyObject {
    func lastTutorSequence(turnID: String) throws -> Int
    func commitTutorFrame(turnID: String, sequence: Int) throws
}

private struct PendingMnemosyneProgress: Codable {
    let documentId: UUID
    var mutation: MnemosyneProgressMutation
}

@MainActor struct MnemosyneAppDependencies {
    let localStore: any MnemosyneLocalStore
    let reader: any MnemosyneReaderFacade
    let readerEngine: PumiceReaderEngine
    let readerController: PDFReaderController
    let syncStateStore: any MnemosyneSyncStateStore
    let tutorCheckpointStore: any MnemosyneTutorCheckpointStore
}

private enum MnemosyneTutorInputError: LocalizedError {
    case readerContextUnavailable
    case selectionNotVerified

    var errorDescription: String? {
        switch self {
        case .readerContextUnavailable:
            "열린 PDF의 페이지 문맥을 읽을 수 없습니다. 문서를 다시 열어 주세요."
        case .selectionNotVerified:
            "선택한 문장을 서버 원문과 대조하지 못했습니다. 문장 선택을 확인한 뒤 다시 시도해 주세요."
        }
    }
}

/// Build the durable Reader and Pencil path at the app boundary.
@MainActor func makeIPadApp() throws -> MnemosyneAppDependencies {
    let localStore = try FileMnemosyneLocalStore.applicationSupportStore()
    let readerEngine = PumiceReaderEngine()
    let reader = try makeReaderFacade(
        factory: { store in PersistentMnemosyneReaderFacade(localStore: store, engine: readerEngine) },
        localStore: localStore
    )
    return MnemosyneAppDependencies(
        localStore: localStore,
        reader: reader,
        readerEngine: readerEngine,
        readerController: PDFReaderController(),
        syncStateStore: MnemosyneReaderSyncStateStore(reader: reader),
        tutorCheckpointStore: MnemosyneNativeTurnCheckpointStore()
    )
}

/// Adapts the owned Reader facade to UNIT-04's sync worker boundary. Snapshot
/// replacement is translated to an authoritative page with missing records
/// represented as tombstones, while the facade preserves pending local edits.
@MainActor private final class MnemosyneReaderSyncStateStore: MnemosyneSyncStateStore {
    private let reader: any MnemosyneReaderFacade

    init(reader: any MnemosyneReaderFacade) { self.reader = reader }

    func syncCursor(documentID: UUID, versionID: String) throws -> String? {
        try reader.receivedCursor(documentID: documentID, versionID: versionID)
    }

    func applyRemoteSnapshot(_ snapshot: Data) throws {
        guard let object = try JSONSerialization.jsonObject(with: snapshot) as? [String: Any],
              object["contract_version"] as? String == MnemosyneContract.version,
              let documentID = (object["document_id"] as? String).flatMap(UUID.init(uuidString:)),
              let versionID = object["version_id"] as? String,
              let revision = object["snapshot_revision"] as? Int, revision >= 0,
              let cursor = object["next_cursor"] as? String, !cursor.isEmpty,
              let annotations = object["annotations"] as? [[String: Any]] else {
            throw MnemosyneAPIError.invalidResponse
        }

        let snapshotIDs = Set(annotations.compactMap { $0["annotation_id"] as? String })
        var changes = annotations
        if revision > 0 {
            let now = ISO8601DateFormatter().string(from: Date())
            for data in try reader.annotations(documentID: documentID, versionID: versionID) {
                guard let previous = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      let annotationID = previous["annotation_id"] as? String,
                      !snapshotIDs.contains(annotationID),
                      let previousRevision = previous["server_revision"] as? Int,
                      let pageIndex = previous["page_index"] as? Int,
                      let kind = previous["kind"] as? String else { continue }
                changes.append([
                    "annotation_id": annotationID,
                    "document_id": documentID.uuidString.lowercased(),
                    "version_id": versionID,
                    "page_index": pageIndex,
                    "kind": kind,
                    "server_revision": max(revision, previousRevision),
                    "updated_at": now,
                    "deleted": true,
                    "deleted_at": now,
                    "payload": NSNull()
                ])
            }
        }

        let page: [String: Any] = [
            "contract_version": MnemosyneContract.version,
            "document_id": documentID.uuidString.lowercased(),
            "version_id": versionID,
            "next_cursor": cursor,
            "changes": changes
        ]
        try reader.applyRemotePage(JSONSerialization.data(withJSONObject: page, options: [.sortedKeys]))
    }
}

/// Persist only turn identity and sequence. Tutor text and raw frames remain
/// in memory, while native frames without semantic metadata still advance the
/// reconnect cursor across app restarts.
@MainActor private final class MnemosyneNativeTurnCheckpointStore: MnemosyneTutorCheckpointStore {
    private let defaults: UserDefaults
    private let keyPrefix = "mnemosyne.native-turn-sequence."

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    func lastTutorSequence(turnID: String) throws -> Int {
        defaults.integer(forKey: try key(turnID: turnID))
    }

    func commitTutorFrame(turnID: String, sequence: Int) throws {
        let storageKey = try key(turnID: turnID)
        guard sequence > 0 else { throw MnemosyneWireError.incompatibleFrame }
        let previous = defaults.integer(forKey: storageKey)
        if sequence <= previous { return }
        guard sequence == previous + 1 else {
            throw MnemosyneWireError.sequenceGap(expected: previous + 1, received: sequence)
        }
        defaults.set(sequence, forKey: storageKey)
    }

    private func key(turnID: String) throws -> String {
        guard turnID.range(of: #"^[A-Za-z0-9_-]{1,256}$"#, options: .regularExpression) != nil else {
            throw MnemosyneTutorTransportError.missingTurnIdentity
        }
        return keyPrefix + turnID
    }
}

enum MnemosyneSection: String, CaseIterable, Identifiable {
    case library, study, settings
    var id: String { rawValue }
    var title: String {
        switch self {
        case .library: "라이브러리"
        case .study: "학습 기록"
        case .settings: "서버 설정"
        }
    }
}

@MainActor
final class MnemosyneAppModel: ObservableObject {
    enum ConnectionState: Equatable {
        case notConfigured, checking, online, offline(String)
    }

    @Published var serverURLText = UserDefaults.standard.string(forKey: "mnemosyne.serverURL") ?? ""
    @Published var pairingCode = ""
    @Published var deviceName = "iPad"
    @Published var selectedSection: MnemosyneSection = .library
    @Published var selectedSubjectId: UUID?
    @Published var selectedDocumentId: UUID?
    @Published private(set) var connectionState: ConnectionState = .notConfigured
    @Published private(set) var isPaired = false
    @Published private(set) var serverReadyState: Bool?
    @Published private(set) var readiness: MnemosyneReadiness?
    @Published private(set) var publicSettings: MnemosynePublicSettings?
    @Published private(set) var subjects: [MnemosyneSubject] = []
    @Published private(set) var documents: [MnemosyneDocument] = []
    @Published private(set) var learningState: MnemosyneLearningState?
    @Published private(set) var activeQuiz: MnemosyneQuiz?
    @Published private(set) var lastAssessment: MnemosyneAssessment?
    @Published private(set) var busyMessage: String?
    @Published private(set) var alertMessage: String?
    @Published private(set) var tutorText = ""
    @Published private(set) var tutorCitations: [MnemosyneVerifiedCitation] = []
    @Published private(set) var tutorStatus = "튜터 연결을 확인하세요."
    @Published private(set) var pendingAnnotationEvent: Data?
    @Published private(set) var downloadStates: [UUID: String] = [:]
    @Published private(set) var syncSummary = "동기화 연결 대기"
    @Published private(set) var syncConflictedMutationIds: [UUID] = []
    @Published private(set) var readerSetupMessage: String?
    @Published private(set) var activeReaderURL: URL?
    @Published private(set) var activeReaderDocumentID: UUID?
    @Published private(set) var activeReaderVersionID: String?
    @Published private(set) var activeReaderPageIndex = 0

    private(set) var reader: (any MnemosyneReaderFacade)?
    private(set) var syncWorker: (any MnemosyneSyncWorker)?
    private(set) var readerEngine: PumiceReaderEngine?
    private(set) var readerController: PDFReaderController?
    private var localStore: (any MnemosyneLocalStore)?
    private var syncStateStore: (any MnemosyneSyncStateStore)?
    private var tutorCheckpointStore: (any MnemosyneTutorCheckpointStore)?
    private var api: MnemosyneAPIClient?
    private var tutorTransport: MnemosyneTutorTransport?
    private var verifiedCitations: [UUID: MnemosyneVerifiedCitation] = [:]
    private var tutorTask: Task<Void, Never>?
    private var currentTurnId = UserDefaults.standard.string(forKey: "mnemosyne.lastTurnId")
    private var currentTurnDocumentId = UserDefaults.standard.string(forKey: "mnemosyne.lastTurnDocumentId")
        .flatMap(UUID.init(uuidString:))
    private let pendingTutorSubmissionKey = "mnemosyne.pendingTutorSubmissionId"
    private let pendingTutorDigestKey = "mnemosyne.pendingTutorRequestDigest"
    private let pendingProgressKey = "mnemosyne.pendingReadingProgress.v2"
    private let legacyPendingProgressKey = "mnemosyne.pendingReadingProgress"
    private let pendingQuizAttemptsKey = "mnemosyne.pendingQuizAttempts"
    private let pendingMemoryReviewsKey = "mnemosyne.pendingMemoryReviews"
    private let pendingQuizGenerationsKey = "mnemosyne.pendingQuizGenerations"
    private var cancelCommandId: UUID?
    private var pendingQuizAttempts: [String: MnemosyneAttempt] = [:]
    private var pendingMemoryReviews: [String: MnemosyneMemoryReview] = [:]
    private var pendingQuizGenerations: [String: UUID] = [:]
    private var pendingProgressMutations: [PendingMnemosyneProgress] = []
    private var legacyPendingProgressMutations: [MnemosyneProgressMutation] = []
    private var progressFlushInFlight = false
    private var openedReaderKey: String?

    init() {
        if let data = UserDefaults.standard.data(forKey: pendingProgressKey),
           let pending = try? JSONDecoder.mnemosyne.decode([PendingMnemosyneProgress].self, from: data) {
            pendingProgressMutations = pending
        }
        if let data = UserDefaults.standard.data(forKey: legacyPendingProgressKey),
           let pending = try? JSONDecoder.mnemosyne.decode([MnemosyneProgressMutation].self, from: data) {
            legacyPendingProgressMutations = pending
        }
        if let data = UserDefaults.standard.data(forKey: pendingQuizAttemptsKey),
           let pending = try? JSONDecoder.mnemosyne.decode([String: MnemosyneAttempt].self, from: data) {
            pendingQuizAttempts = pending
        }
        if let data = UserDefaults.standard.data(forKey: pendingMemoryReviewsKey),
           let pending = try? JSONDecoder.mnemosyne.decode([String: MnemosyneMemoryReview].self, from: data) {
            pendingMemoryReviews = pending
        }
        if let data = UserDefaults.standard.data(forKey: pendingQuizGenerationsKey),
           let pending = try? JSONDecoder.mnemosyne.decode([String: UUID].self, from: data) {
            pendingQuizGenerations = pending
        }
        do {
            let dependencies = try makeIPadApp()
            localStore = dependencies.localStore
            reader = dependencies.reader
            readerEngine = dependencies.readerEngine
            readerController = dependencies.readerController
            syncStateStore = dependencies.syncStateStore
            tutorCheckpointStore = dependencies.tutorCheckpointStore
            dependencies.readerEngine.onAnnotationSuggestion = { [weak self] event in
                self?.pendingAnnotationEvent = event
            }
        } catch {
            readerSetupMessage = error.localizedDescription
        }
    }

    var selectedDocument: MnemosyneDocument? {
        guard let selectedDocumentId else { return nil }
        return documents.first { $0.documentId == selectedDocumentId }
    }

    var hasReaderFacade: Bool { reader != nil }
    var isTutorRunning: Bool { tutorTask != nil }
    var hasUnfinishedTutorTurn: Bool { currentTurnId != nil }

    func canResumeTutor(for document: MnemosyneDocument) -> Bool {
        currentTurnId != nil && currentTurnDocumentId == document.documentId && !isTutorRunning
    }

    func dismissAlert() { alertMessage = nil }
    func presentError(_ message: String) { alertMessage = message }

    var connectionSummary: String {
        switch connectionState {
        case .notConfigured: "서버 주소를 설정해 주세요"
        case .checking: "서버 연결 확인 중"
        case .online: isPaired ? "서버 연결됨 · 기기 연결됨" : "서버 연결됨 · 기기 연결 필요"
        case let .offline(message): message
        }
    }

    func connectSavedServer() async {
        guard !serverURLText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        await connectAndRefresh()
    }

    func connectAndRefresh() async {
        connectionState = .checking
        busyMessage = "서버 연결을 확인하고 있습니다"
        defer { busyMessage = nil }
        let client: MnemosyneAPIClient
        do {
            let url = try MnemosyneAPIClient.validatedURL(serverURLText)
            client = try MnemosyneAPIClient(baseURL: url)
            api = client
            try await client.health()
            serverURLText = url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            UserDefaults.standard.set(serverURLText, forKey: "mnemosyne.serverURL")
            connectionState = .online
            isPaired = await client.isPaired()
            serverReadyState = try await client.serverReady()
        } catch {
            connectionState = .offline(error.localizedDescription)
            alertMessage = error.localizedDescription
            return
        }
        guard isPaired else {
            (syncWorker as? MnemosyneAnnotationSyncWorker)?.stopForegroundWorker()
            syncWorker = nil
            readiness = nil
            publicSettings = nil
            subjects = []
            documents = []
            return
        }
        configureSyncWorker(using: client)
        do {
                readiness = try await client.readiness()
                publicSettings = try await client.settings()
                try await refreshLibrary()
                if currentTurnId != nil, tutorCheckpointStore != nil {
                    tutorStatus = "이전 튜터 응답을 이어 받을 수 있습니다."
                }
        } catch {
            // Health can be available while the paired Mnemosyne API is unavailable.
            alertMessage = "서버는 응답하지만 Mnemosyne API를 사용할 수 없습니다. \(error.localizedDescription)"
        }
    }

    func pairDevice() async {
        guard let api else { alertMessage = "먼저 서버 주소를 확인해 주세요."; return }
        guard pairingCode.count >= 8 else { alertMessage = "서버에서 받은 일회용 코드를 입력해 주세요."; return }
        busyMessage = "기기를 연결하고 있습니다"
        defer { busyMessage = nil; pairingCode = "" }
        do {
            _ = try await api.pair(oneTimeCode: pairingCode, deviceName: deviceName)
            isPaired = true
            configureSyncWorker(using: api)
            readiness = try await api.readiness()
            publicSettings = try await api.settings()
            try await refreshLibrary()
        } catch { alertMessage = error.localizedDescription }
    }

    func unpairDevice() async {
        guard let api else { return }
        busyMessage = "기기 연결을 해제하고 있습니다"
        defer { busyMessage = nil }
        do {
            try await api.unpair()
            (syncWorker as? MnemosyneAnnotationSyncWorker)?.stopForegroundWorker()
            syncWorker = nil
            isPaired = false
            readiness = nil
            publicSettings = nil
            subjects = []
            documents = []
            // Local drafts and their outbox remain in the Reader facade for a later pairing.
        } catch { alertMessage = error.localizedDescription }
    }

    func refreshLibrary() async throws {
        guard let api, isPaired else { throw MnemosyneAPIError.pairingRequired }
        async let fetchedSubjects = api.subjects()
        async let fetchedDocuments = api.documents(subjectId: selectedSubjectId)
        subjects = try await fetchedSubjects
        documents = try await fetchedDocuments
        await migrateLegacyProgressMutations()
        if let reader {
            for document in documents {
                guard let state = try? reader.downloadState(documentID: document.documentId,
                                                           versionID: document.versionId) else { continue }
                switch state {
                case .cached: downloadStates[document.documentId] = "기기에 저장됨"
                case .downloading: downloadStates[document.documentId] = "다운로드 중"
                case .invalid: downloadStates[document.documentId] = "다시 다운로드 필요"
                case .missing: downloadStates.removeValue(forKey: document.documentId)
                }
            }
        }
        if let selectedDocumentId, !documents.contains(where: { $0.documentId == selectedDocumentId }) {
            self.selectedDocumentId = nil
        }
    }

    func refreshLibraryFromUI() async {
        busyMessage = "라이브러리를 새로 고치고 있습니다"
        defer { busyMessage = nil }
        do { try await refreshLibrary() } catch { alertMessage = error.localizedDescription }
    }

    private func configureSyncWorker(using api: MnemosyneAPIClient) {
        guard let reader, let syncStateStore else { return }
        (syncWorker as? MnemosyneAnnotationSyncWorker)?.stopForegroundWorker()
        let worker = MnemosyneAnnotationSyncWorker(api: api, reader: reader, syncState: syncStateStore)
        syncWorker = worker
        worker.startForegroundWorker()
    }

    func selectSubject(_ subjectId: UUID?) async {
        selectedSubjectId = subjectId
        selectedDocumentId = nil
        await refreshLibraryFromUI()
    }

    func createSubject(name: String) async {
        guard let api, isPaired else { alertMessage = "기기를 서버에 연결해 주세요."; return }
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        do {
            let subject = try await api.createSubject(name: trimmed)
            subjects.append(subject)
            selectedSubjectId = subject.subjectId
        } catch { alertMessage = error.localizedDescription }
    }

    func deleteSubject(_ subject: MnemosyneSubject) async {
        guard let api, isPaired else { alertMessage = "기기를 서버에 연결해 주세요."; return }
        do {
            try await api.deleteSubject(subject)
            if selectedSubjectId == subject.subjectId { selectedSubjectId = nil }
            try await refreshLibrary()
        } catch { alertMessage = error.localizedDescription }
    }

    func uploadPDF(from url: URL) async {
        guard let api, isPaired else { alertMessage = "기기를 서버에 연결해 주세요."; return }
        let hasAccess = url.startAccessingSecurityScopedResource()
        defer { if hasAccess { url.stopAccessingSecurityScopedResource() } }
        busyMessage = "PDF를 서버에 올리고 있습니다"
        defer { busyMessage = nil }
        do {
            let document = try await api.uploadDocument(fileURL: url,
                title: url.deletingPathExtension().lastPathComponent, subjectId: selectedSubjectId)
            selectedDocumentId = document.documentId
            try await refreshLibrary()
        } catch { alertMessage = error.localizedDescription }
    }

    func deleteDocument(_ document: MnemosyneDocument) async {
        guard let api else { alertMessage = "서버 연결을 확인해 주세요."; return }
        busyMessage = "문서를 삭제하고 있습니다"
        defer { busyMessage = nil }
        do {
            try await api.deleteDocument(document)
            if selectedDocumentId == document.documentId { selectedDocumentId = nil }
            try await refreshLibrary()
        } catch { alertMessage = error.localizedDescription }
    }

    func openDocument(_ document: MnemosyneDocument) async {
        selectedDocumentId = document.documentId
        guard let reader, let localStore, readerEngine != nil, readerController != nil else {
            alertMessage = readerSetupMessage ?? "PDF Reader와 로컬 원본 저장소를 준비하지 못했습니다."
            return
        }
        busyMessage = "원본 PDF 상태를 확인하고 있습니다"
        downloadStates[document.documentId] = "확인 중"
        defer { busyMessage = nil }
        do {
            let localState = try reader.downloadState(documentID: document.documentId, versionID: document.versionId)
            switch localState {
            case .cached:
                busyMessage = "기기에 저장된 원본을 열고 있습니다"
            case .missing, .invalid:
                guard document.originalAvailable, let api else {
                    throw api == nil ? MnemosyneAPIError.pairingRequired : MnemosyneAPIError.invalidPDF
                }
                busyMessage = "원본 PDF를 다운로드하고 있습니다"
                downloadStates[document.documentId] = "다운로드 중"
                let temporaryURL = try await api.downloadOriginal(document)
                defer { try? FileManager.default.removeItem(at: temporaryURL) }
                try await reader.installDownloadedOriginal(from: temporaryURL, documentID: document.documentId,
                                                             versionID: document.versionId)
            case .downloading:
                downloadStates[document.documentId] = "다운로드 중"
                return
            }
            guard let cachedURL = try localStore.cachedOriginalURL(documentID: document.documentId,
                                                                   versionID: document.versionId) else {
                throw MnemosyneAPIError.invalidPDF
            }
            activeReaderDocumentID = document.documentId
            activeReaderVersionID = document.versionId
            activeReaderURL = cachedURL
            openedReaderKey = nil
            downloadStates[document.documentId] = "기기에 저장됨"
        } catch {
            downloadStates[document.documentId] = "오류 · 다시 시도"
            alertMessage = error.localizedDescription
        }
    }

    func readerViewDidAppear(for document: MnemosyneDocument) async {
        guard activeReaderDocumentID == document.documentId,
              activeReaderVersionID == document.versionId,
              let reader else { return }
        let key = "\(document.documentId.uuidString.lowercased())|\(document.versionId)"
        guard openedReaderKey != key else { return }
        do {
            try await reader.openCached(documentID: document.documentId, versionID: document.versionId)
            openedReaderKey = key
            saveReaderContext()
            if let context = try? reader.readerContext(),
               let value = try? JSONSerialization.jsonObject(with: context) as? [String: Any],
               let pageIndex = value["page_index"] as? Int {
                activeReaderPageIndex = pageIndex
                enqueueReadPage(pageIndex)
            }
        } catch {
            activeReaderURL = nil
            activeReaderDocumentID = nil
            activeReaderVersionID = nil
            alertMessage = error.localizedDescription
        }
    }

    func readerViewDidDisappear() {
        readerController?.saveIfNeeded()
        saveReaderContext()
        openedReaderKey = nil
    }

    func closeReader() {
        readerViewDidDisappear()
        activeReaderURL = nil
        activeReaderDocumentID = nil
        activeReaderVersionID = nil
    }

    func saveReaderContext() {
        guard let context = try? reader?.readerContext(),
              let value = try? JSONSerialization.jsonObject(with: context) as? [String: Any],
              let pageIndex = value["page_index"] as? Int else { return }
        activeReaderPageIndex = pageIndex
    }
    func readerPageChanged(_ pageIndex: Int) {
        activeReaderPageIndex = pageIndex
        saveReaderContext()
        enqueueReadPage(pageIndex)
    }

    func generateQuiz(prompt: String) async {
        guard let api, isPaired, let document = selectedDocument,
              activeReaderDocumentID == document.documentId,
              activeReaderVersionID == document.versionId,
              document.parseState == .ready,
              (0..<document.pageCount).contains(activeReaderPageIndex) else {
            alertMessage = "분석된 PDF를 Reader에서 연 뒤 현재 페이지 퀴즈를 만들 수 있습니다."
            return
        }
        let normalizedPrompt = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedPrompt.isEmpty else { alertMessage = "퀴즈 생성 요청을 입력해 주세요."; return }
        let identity = [document.documentId.uuidString.lowercased(), document.versionId,
                        String(activeReaderPageIndex), normalizedPrompt, "ko"].joined(separator: "\u{0}")
        let key = SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
        let mutationID = pendingQuizGenerations[key] ?? UUID()
        pendingQuizGenerations[key] = mutationID
        persistPendingLearningMutations()
        busyMessage = "문서 근거 퀴즈를 만들고 있습니다"
        defer { busyMessage = nil }
        do {
            let quiz = try await api.createQuiz(documentId: document.documentId, request: MnemosyneQuizGenerationRequest(
                clientMutationId: mutationID, versionId: document.versionId, pageIndex: activeReaderPageIndex,
                prompt: normalizedPrompt, responseLanguage: "ko"
            ))
            guard quiz.documentId == document.documentId, quiz.versionId == document.versionId else {
                throw MnemosyneAPIError.invalidResponse
            }
            pendingQuizGenerations.removeValue(forKey: key)
            persistPendingLearningMutations()
            activeQuiz = quiz
            lastAssessment = nil
        } catch { alertMessage = error.localizedDescription }
    }

    private func enqueueReadPage(_ pageIndex: Int) {
        guard let document = selectedDocument,
              activeReaderDocumentID == document.documentId,
              activeReaderVersionID == document.versionId,
              (0..<document.pageCount).contains(pageIndex) else { return }
        if learningState?.progress.pagesRead.contains(pageIndex) == true,
           !pendingProgressMutations.contains(where: {
               $0.documentId == document.documentId && $0.mutation.pageIndex == pageIndex
                   && $0.mutation.versionId == document.versionId
           }) {
            return
        }
        if pendingProgressMutations.last?.documentId == document.documentId,
           pendingProgressMutations.last?.mutation.pageIndex == pageIndex,
           pendingProgressMutations.last?.mutation.versionId == document.versionId {
            return
        }
        pendingProgressMutations.append(PendingMnemosyneProgress(
            documentId: document.documentId,
            mutation: MnemosyneProgressMutation(
                clientMutationId: UUID(),
                versionId: document.versionId,
                baseLearningRevision: learningState?.learningRevision ?? 1,
                pageIndex: pageIndex,
                readingSeconds: 0
            )
        ))
        persistPendingProgress()
        Task { await flushPendingProgress() }
    }

    private func persistPendingProgress() {
        if let data = try? JSONEncoder.mnemosyne.encode(pendingProgressMutations) {
            UserDefaults.standard.set(data, forKey: pendingProgressKey)
        }
    }

    private func migrateLegacyProgressMutations() async {
        guard !legacyPendingProgressMutations.isEmpty, let api else { return }
        do {
            let allDocuments = try await api.documents(subjectId: nil)
            var unresolved: [MnemosyneProgressMutation] = []
            for mutation in legacyPendingProgressMutations {
                let matches = allDocuments.filter { $0.versionId == mutation.versionId }
                guard matches.count == 1,
                      let document = matches.first,
                      (0..<document.pageCount).contains(mutation.pageIndex) else {
                    unresolved.append(mutation)
                    continue
                }
                if !pendingProgressMutations.contains(where: {
                    $0.documentId == document.documentId
                        && $0.mutation.clientMutationId == mutation.clientMutationId
                }) {
                    pendingProgressMutations.append(PendingMnemosyneProgress(
                        documentId: document.documentId, mutation: mutation
                    ))
                }
            }
            legacyPendingProgressMutations = unresolved
            persistPendingProgress()
            if unresolved.isEmpty {
                UserDefaults.standard.removeObject(forKey: legacyPendingProgressKey)
            } else {
                if let data = try? JSONEncoder.mnemosyne.encode(unresolved) {
                    UserDefaults.standard.set(data, forKey: legacyPendingProgressKey)
                }
                syncSummary = "이전 읽기 진도 중 같은 원본 문서가 여러 개라 안전하게 연결하지 못한 기록이 있습니다. 해당 문서를 확인한 뒤 동기화해 주세요."
            }
        } catch {
            syncSummary = "이전 읽기 진도 기록의 문서를 확인하지 못했습니다. 연결이 복구되면 다시 확인합니다."
        }
    }

    private func persistPendingLearningMutations() {
        if let data = try? JSONEncoder.mnemosyne.encode(pendingQuizAttempts) {
            UserDefaults.standard.set(data, forKey: pendingQuizAttemptsKey)
        }
        if let data = try? JSONEncoder.mnemosyne.encode(pendingMemoryReviews) {
            UserDefaults.standard.set(data, forKey: pendingMemoryReviewsKey)
        }
        if let data = try? JSONEncoder.mnemosyne.encode(pendingQuizGenerations) {
            UserDefaults.standard.set(data, forKey: pendingQuizGenerationsKey)
        }
    }

    private func flushPendingProgress() async {
        guard !progressFlushInFlight,
              let api, isPaired, let document = selectedDocument else { return }
        progressFlushInFlight = true
        defer { progressFlushInFlight = false }
        while let index = pendingProgressMutations.firstIndex(where: {
            $0.documentId == document.documentId && $0.mutation.versionId == document.versionId
        }) {
            var mutation = pendingProgressMutations[index].mutation
            mutation.baseLearningRevision = learningState?.learningRevision
                ?? (try? await api.learning(documentId: document.documentId, versionId: document.versionId).learningRevision)
                ?? mutation.baseLearningRevision
            pendingProgressMutations[index].mutation = mutation
            persistPendingProgress()
            do {
                learningState = try await api.recordProgress(documentId: document.documentId, mutation: mutation)
                pendingProgressMutations.remove(at: index)
                persistPendingProgress()
                syncSummary = "읽기 진도 저장 완료"
            } catch let MnemosyneAPIError.server(status: 409, code: "conflict", _, _, _, _) {
                do {
                    learningState = try await api.learning(documentId: document.documentId, versionId: document.versionId)
                    mutation.baseLearningRevision = learningState?.learningRevision ?? mutation.baseLearningRevision
                    pendingProgressMutations[index].mutation = mutation
                    persistPendingProgress()
                    do {
                        learningState = try await api.recordProgress(documentId: document.documentId, mutation: mutation)
                        pendingProgressMutations.remove(at: index)
                        persistPendingProgress()
                        syncSummary = "읽기 진도 저장 완료"
                    } catch {
                        syncSummary = "읽기 진도 저장 대기 · 네트워크 복구 후 재전송"
                        return
                    }
                } catch {
                    syncSummary = "읽기 진도 저장 대기 · 학습 상태를 다시 불러와 주세요"
                    return
                }
            } catch {
                syncSummary = "읽기 진도 저장 대기 · 네트워크 복구 후 재전송"
                return
            }
        }
    }

    func undoReader() { try? reader?.undo() }
    func redoReader() { try? reader?.redo() }

    func synchronizeNow() async {
        guard let syncWorker else {
            syncSummary = "오프라인 주석을 동기화할 수 없습니다."
            alertMessage = "이 기기에서 문서 동기화를 사용할 수 없습니다. 다시 실행해 주세요."
            return
        }
        busyMessage = "필기와 주석을 동기화하고 있습니다"
        defer { busyMessage = nil }
        syncConflictedMutationIds = []
        do {
            try await syncWorker.synchronize()
            if let worker = syncWorker as? MnemosyneAnnotationSyncWorker {
                syncConflictedMutationIds = worker.conflictedMutationIds
            }
            syncSummary = syncConflictedMutationIds.isEmpty
                ? "동기화 완료"
                : "서버 충돌 검토 필요 · \(syncConflictedMutationIds.count)건"
        } catch {
            syncSummary = "재시도 필요 · \(error.localizedDescription)"
            alertMessage = error.localizedDescription
        }
    }

    func refreshLearning() async {
        guard let api, let document = selectedDocument, isPaired else { return }
        do {
            learningState = try await api.learning(documentId: document.documentId, versionId: document.versionId)
            await flushPendingProgress()
        }
        catch { alertMessage = error.localizedDescription }
    }

    func loadQuiz(quizId: UUID, for expectedDocument: MnemosyneDocument? = nil) async {
        guard let api, isPaired else { alertMessage = "기기를 서버에 연결해 주세요."; return }
        guard let document = expectedDocument ?? selectedDocument else {
            alertMessage = "먼저 문서를 선택해 주세요."
            return
        }
        do {
            let quiz = try await api.quiz(quizId: quizId)
            guard quiz.documentId == document.documentId, quiz.versionId == document.versionId else {
                throw MnemosyneAPIError.invalidResponse
            }
            lastAssessment = nil
            activeQuiz = quiz
        }
        catch { alertMessage = error.localizedDescription }
    }

    func submitQuizAnswers(_ answers: [UUID: String]) async {
        guard let api, let quiz = activeQuiz, let document = selectedDocument,
              let learningState, quiz.documentId == document.documentId,
              quiz.versionId == document.versionId else { return }
        let nonempty = answers.filter { !$0.value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        guard !nonempty.isEmpty else { alertMessage = "답을 입력해 주세요."; return }
        let knownQuestions = Set(quiz.questions.map(\.questionId))
        guard Set(nonempty.keys).isSubset(of: knownQuestions) else {
            alertMessage = "현재 퀴즈에 없는 문항의 답은 제출하지 않았습니다."
            return
        }
        let orderedAnswers = nonempty.sorted { $0.key.uuidString < $1.key.uuidString }
        let answerRows: [[String: String]] = orderedAnswers.map {
            ["question_id": $0.key.uuidString.lowercased(), "answer": $0.value]
        }
        guard let answerData = try? JSONSerialization.data(withJSONObject: answerRows, options: [.sortedKeys]) else {
            alertMessage = "답안을 안전하게 정리하지 못했습니다."
            return
        }
        var attemptFingerprintData = Data([
            quiz.quizId.uuidString.lowercased(), document.documentId.uuidString.lowercased(),
            document.versionId
        ].joined(separator: "|").utf8)
        attemptFingerprintData.append(answerData)
        let attemptKey = SHA256.hash(data: attemptFingerprintData)
            .map { String(format: "%02x", $0) }.joined()
        let attempt: MnemosyneAttempt
        if let pending = pendingQuizAttempts[attemptKey] {
            attempt = pending
        } else {
            attempt = MnemosyneAttempt(attemptId: UUID(), clientMutationId: UUID(), quizId: quiz.quizId,
                documentId: document.documentId, versionId: document.versionId,
                baseLearningRevision: learningState.learningRevision,
                submittedAt: ISO8601DateFormatter().string(from: Date()),
                answers: orderedAnswers.map { .init(questionId: $0.key, answer: $0.value) })
            pendingQuizAttempts[attemptKey] = attempt
            persistPendingLearningMutations()
        }
        busyMessage = "서버에서 답을 평가하고 있습니다"
        defer { busyMessage = nil }
        do {
            // Score and feedback always come from DeepTutor's assessment response.
            let assessment = try await api.submitAttempt(attempt)
            guard assessment.attemptId == attempt.attemptId else { throw MnemosyneAPIError.invalidResponse }
            lastAssessment = assessment
            pendingQuizAttempts.removeValue(forKey: attemptKey)
            persistPendingLearningMutations()
            await refreshLearning()
        } catch let MnemosyneAPIError.server(status: 409, code: "conflict", _, _, retryable: true, _) {
            alertMessage = "서버에서 같은 퀴즈 응시를 처리 중입니다. 잠시 후 같은 답안을 다시 제출해 주세요."
        } catch let MnemosyneAPIError.server(status: 409, code: "conflict", _, _, retryable: false, _) {
            do {
                self.learningState = try await api.learning(documentId: document.documentId, versionId: document.versionId)
                pendingQuizAttempts[attemptKey] = MnemosyneAttempt(
                    attemptId: UUID(), clientMutationId: UUID(), quizId: quiz.quizId,
                    documentId: document.documentId, versionId: document.versionId,
                    baseLearningRevision: self.learningState?.learningRevision ?? attempt.baseLearningRevision,
                    submittedAt: ISO8601DateFormatter().string(from: Date()), answers: attempt.answers
                )
                persistPendingLearningMutations()
                alertMessage = "최신 학습 상태를 불러왔습니다. 같은 답안을 다시 제출해 주세요."
            } catch { alertMessage = error.localizedDescription }
        } catch { alertMessage = error.localizedDescription }
    }

    func reviewMemory(_ memory: MnemosyneLearningState.Memory, grade: Int) async {
        guard let api, let learningState, let document = selectedDocument, (0...3).contains(grade) else { return }
        let reviewKey = "\(memory.memoryId.uuidString.lowercased())|\(grade)"
        let review: MnemosyneMemoryReview
        if let pending = pendingMemoryReviews[reviewKey] {
            review = pending
        } else {
            review = MnemosyneMemoryReview(clientMutationId: UUID(), memoryId: memory.memoryId,
                baseLearningRevision: learningState.learningRevision, grade: grade,
                reviewedAt: ISO8601DateFormatter().string(from: Date()))
            pendingMemoryReviews[reviewKey] = review
            persistPendingLearningMutations()
        }
        do {
            self.learningState = try await api.reviewMemory(review)
            pendingMemoryReviews.removeValue(forKey: reviewKey)
            persistPendingLearningMutations()
        }
        catch let MnemosyneAPIError.server(status: 409, code: "conflict", _, _, retryable: true, _) {
            alertMessage = "서버에서 이 복습을 처리 중입니다. 잠시 후 같은 평가를 다시 눌러 주세요."
        } catch let MnemosyneAPIError.server(status: 409, code: "conflict", _, _, retryable: false, _) {
            do {
                self.learningState = try await api.learning(documentId: document.documentId, versionId: document.versionId)
                pendingMemoryReviews[reviewKey] = MnemosyneMemoryReview(
                    clientMutationId: UUID(), memoryId: memory.memoryId,
                    baseLearningRevision: self.learningState?.learningRevision ?? review.baseLearningRevision,
                    grade: grade, reviewedAt: ISO8601DateFormatter().string(from: Date())
                )
                persistPendingLearningMutations()
                alertMessage = "최신 학습 상태를 불러왔습니다. 같은 카드를 다시 복습해 주세요."
            } catch { alertMessage = error.localizedDescription }
        } catch { alertMessage = error.localizedDescription }
    }

    /// Build the native protocol command and the versioned Mnemosyne envelope
    /// from the open Reader. Any selected text is attached only after the
    /// server verifies its source anchor for this exact document version/page.
    func askTutor(message: String) async {
        let prompt = message.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty else { return }
        guard currentTurnId == nil else {
            tutorStatus = "이전 튜터 응답을 먼저 이어받아 주세요."
            alertMessage = currentTurnDocumentId == selectedDocument?.documentId
                ? "이전 튜터 응답을 이어받은 뒤 새 질문을 보낼 수 있습니다."
                : "이전 문서의 튜터 응답을 먼저 이어받아 완료해 주세요."
            return
        }
        guard let api, let reader, let document = selectedDocument,
              activeReaderDocumentID == document.documentId,
              activeReaderVersionID == document.versionId,
              document.isTutorReady else {
            alertMessage = "문서를 열고 분석이 완료된 뒤 튜터를 사용할 수 있습니다."
            return
        }

        do {
            // selectedText() invalidates any previous verified anchor. The
            // Reader therefore never forwards a stale selection as evidence.
            let selectedText = try reader.selectedText()?.trimmingCharacters(in: .whitespacesAndNewlines)
            if let selectedText, !selectedText.isEmpty {
                guard let contextData = try? reader.readerContext(),
                      let context = try JSONSerialization.jsonObject(with: contextData) as? [String: Any],
                      let pageIndex = context["page_index"] as? Int else {
                    throw MnemosyneTutorInputError.readerContextUnavailable
                }
                let candidates = try await api.search(documentId: document.documentId,
                    versionId: document.versionId, query: selectedText, limit: 50)
                let normalizedSelection = Self.normalizedSelection(selectedText)
                guard let candidate = candidates.first(where: {
                    $0.documentId == document.documentId && $0.versionId == document.versionId &&
                    $0.pageIndex == pageIndex &&
                    Self.normalizedSelection($0.quote).contains(normalizedSelection)
                }) else {
                    throw MnemosyneTutorInputError.selectionNotVerified
                }
                let verified = try await api.verifyCitation(candidate)
                guard verified.verified, verified.anchor == candidate,
                      verified.anchor.documentId == document.documentId,
                      verified.anchor.versionId == document.versionId,
                      verified.anchor.pageIndex == pageIndex else {
                    throw MnemosyneTutorInputError.selectionNotVerified
                }
                try reader.setVerifiedSelectionAnchor(Self.anchorData(verified.anchor))
            } else {
                try reader.setVerifiedSelectionAnchor(nil)
            }

            guard let contextData = try? reader.readerContext(),
                  var readerContext = try JSONSerialization.jsonObject(with: contextData) as? [String: Any],
                  readerContext["document_id"] as? String == document.documentId.uuidString.lowercased(),
                  readerContext["version_id"] as? String == document.versionId,
                  let contentLanguage = readerContext["content_language"] as? String,
                  readerContext["page_index"] as? Int != nil,
                  let viewport = readerContext["viewport_rect"] as? [NSNumber], viewport.count == 4,
                  readerContext["selection"] != nil else {
                throw MnemosyneTutorInputError.readerContextUnavailable
            }
            readerContext["response_language"] = "ko"
            let digestInput: [String: Any] = [
                "capability": "chat",
                "message": prompt,
                "reader_context": readerContext,
                "response_language": "ko"
            ]
            let digestData = try JSONSerialization.data(withJSONObject: digestInput, options: [.sortedKeys])
            let digest = SHA256.hash(data: digestData).map { String(format: "%02x", $0) }.joined()
            let defaults = UserDefaults.standard
            let submissionId: String
            if let pendingId = defaults.string(forKey: pendingTutorSubmissionKey),
               let pendingDigest = defaults.string(forKey: pendingTutorDigestKey) {
                guard pendingDigest == digest else {
                    alertMessage = "이전 질문의 서버 접수 여부를 확인할 수 없습니다. 같은 질문과 문서 위치로 다시 시도해 주세요."
                    return
                }
                guard UUID(uuidString: pendingId) != nil else {
                    alertMessage = "이전 튜터 요청의 재전송 식별자를 읽을 수 없습니다. 앱을 다시 연결한 뒤 재시도해 주세요."
                    return
                }
                submissionId = pendingId
            } else {
                submissionId = UUID().uuidString.lowercased()
                defaults.set(digest, forKey: pendingTutorDigestKey)
                defaults.set(submissionId, forKey: pendingTutorSubmissionKey)
            }

            let envelopeRequest: [String: Any] = [
                "client_mutation_id": submissionId,
                "capability": "chat",
                "message": prompt,
                "reader_context": readerContext,
                "response_language": "ko"
            ]
            let command: [String: Any] = [
                "type": "start_turn",
                "protocol_version": MnemosyneContract.nativeProtocolVersion,
                "client_submission_id": submissionId,
                "content": prompt,
                "capability": "chat",
                "language": contentLanguage,
                "reply_language_override": "ko",
                "auto_route": false,
                "config": ["mnemosyne": [
                    "contract_version": MnemosyneContract.version,
                    "turn_request": envelopeRequest
                ]]
            ]
            let startCommand = try JSONSerialization.data(withJSONObject: command, options: [.sortedKeys])
            startTutor(startCommand: startCommand)
        } catch {
            tutorStatus = "튜터 요청을 준비하지 못했습니다."
            alertMessage = error.localizedDescription
        }
    }

    private static func normalizedSelection(_ value: String) -> String {
        String(value.filter { !$0.isWhitespace })
    }

    private static func anchorData(_ anchor: MnemosyneTextAnchor) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "document_id": anchor.documentId.uuidString.lowercased(),
            "version_id": anchor.versionId,
            "page_index": anchor.pageIndex,
            "parse_revision": anchor.parseRevision,
            "text_sha256": anchor.textSha256,
            "start_scalar": anchor.startScalar,
            "end_scalar": anchor.endScalar,
            "quote": anchor.quote,
            "rects": anchor.rects
        ], options: [.sortedKeys])
    }

    func resumeTutor(for document: MnemosyneDocument) {
        guard canResumeTutor(for: document) else { return }
        startTutor(startCommand: Data())
    }

    func startTutor(startCommand: Data) {
        guard let api, let reader, let document = selectedDocument,
              let checkpointStore = tutorCheckpointStore,
              let url = try? MnemosyneAPIClient.validatedURL(serverURLText) else {
            tutorStatus = "튜터 스트림 또는 Reader checkpoint 연결을 기다리는 중입니다."
            return
        }
        guard tutorTask == nil else { return }
        tutorText = ""
        tutorCitations = []
        verifiedCitations = [:]
        cancelCommandId = nil
        let transport = MnemosyneTutorTransport(baseURL: url)
        tutorTransport = transport
        tutorStatus = "튜터에 연결하고 있습니다"
        let resumeId = currentTurnDocumentId == document.documentId ? currentTurnId : nil
        currentTurnDocumentId = document.documentId
        let resumeSequence = resumeId.flatMap { try? checkpointStore.lastTutorSequence(turnId: $0) } ?? 0
        tutorTask = Task { [weak self] in
            guard let self else { return }
            defer { tutorTask = nil; cancelCommandId = nil }
            do {
                try await transport.run(startCommand: resumeId == nil ? startCommand : nil,
                    resumeTurnId: resumeId, afterSequence: resumeSequence,
                    checkpoint: { turnId, sequence, _ in
                        try checkpointStore.commitTutorFrame(turnID: turnId, sequence: sequence)
                        currentTurnId = turnId
                        // Once a turn identity is durably checkpointed, future
                        // reconnects resume it instead of submitting it again.
                        UserDefaults.standard.removeObject(forKey: pendingTutorSubmissionKey)
                        UserDefaults.standard.removeObject(forKey: pendingTutorDigestKey)
                        UserDefaults.standard.set(turnId, forKey: "mnemosyne.lastTurnId")
                        UserDefaults.standard.set(document.documentId.uuidString, forKey: "mnemosyne.lastTurnDocumentId")
                    },
                    onEvent: { event in try await handleTutorEvent(event, document: document, reader: reader, api: api) })
                tutorStatus = "응답 완료"
                currentTurnId = nil
                currentTurnDocumentId = nil
                UserDefaults.standard.removeObject(forKey: "mnemosyne.lastTurnId")
                UserDefaults.standard.removeObject(forKey: "mnemosyne.lastTurnDocumentId")
            } catch is CancellationError {
                tutorStatus = "응답을 취소했습니다"
            } catch {
                tutorStatus = "연결 오류 · 재시도할 수 있습니다"
                alertMessage = error.localizedDescription
            }
        }
    }

    func cancelTutor() async {
        guard let tutorTransport else { return }
        let id = cancelCommandId ?? UUID()
        cancelCommandId = id
        tutorStatus = "취소 요청 중"
        do { try await tutorTransport.cancel(commandId: id) }
        catch { alertMessage = error.localizedDescription }
    }

    func approvePendingAnnotation() {
        guard let pendingAnnotationEvent, let reader else { return }
        do {
            // Approval is the only path that turns a Tutor suggestion into an outbox mutation.
            _ = try reader.approveAnnotationSuggestion(pendingAnnotationEvent)
            self.pendingAnnotationEvent = nil
        } catch { alertMessage = error.localizedDescription }
    }

    func rejectPendingAnnotation() { pendingAnnotationEvent = nil }

    func dismissQuiz() { activeQuiz = nil }

    private func handleTutorEvent(_ eventData: Data, document: MnemosyneDocument,
                                  reader: any MnemosyneReaderFacade, api: MnemosyneAPIClient) async throws {
        guard let eventObject = try JSONSerialization.jsonObject(with: eventData) as? [String: Any],
              let type = eventObject["type"] as? String,
              let payload = eventObject["payload"] as? [String: Any] else { throw MnemosyneTutorTransportError.unsupportedFrame }
        if type == "citation.verified" {
            guard let citation = try MnemosyneReaderEventValidator.verifiedCitation(from: eventData) else {
                throw MnemosyneReaderEventError.malformed
            }
            try await verifyCitationAgainstPage(citation, document: document, api: api)
            if let existing = verifiedCitations[citation.citationId], existing != citation {
                throw MnemosyneReaderEventError.unverifiedCitation
            }
            verifiedCitations[citation.citationId] = citation
            if !tutorCitations.contains(where: { $0.citationId == citation.citationId }) {
                tutorCitations.append(citation)
            }
            tutorStatus = "문서 근거 확인됨"
            return
        }
        let disposition = try MnemosyneReaderEventValidator.validate(eventData, documentId: document.documentId,
            versionId: document.versionId, pageCount: document.pageCount, verifiedCitations: verifiedCitations)
        switch type {
        case "assistant.delta":
            tutorText += payload["text"] as? String ?? ""
            tutorStatus = "응답 중"
        case "reader.goto", "reader.highlight", "reader.flash":
            guard disposition == .apply else { throw MnemosyneReaderEventError.malformed }
            try reader.applyReaderEvent(eventData)
        case "reader.annotate":
            guard disposition == .requiresUserConfirmation else { throw MnemosyneReaderEventError.malformed }
            pendingAnnotationEvent = eventData
        case "quiz.show":
            guard let quizId = (payload["quiz_id"] as? String).flatMap(UUID.init(uuidString:)) else {
                throw MnemosyneReaderEventError.malformed
            }
            await loadQuiz(quizId: quizId, for: document)
        case "learning.updated":
            await refreshLearning()
        case "turn.started": tutorStatus = "튜터가 문서를 읽고 있습니다"
        case "turn.done": tutorStatus = payload["summary_ko"] as? String ?? "응답 완료"
        case "turn.error":
            tutorStatus = "튜터 응답 오류"
            if let errorObject = payload["error"] as? [String: Any],
               let message = errorObject["message_ko"] as? String { alertMessage = message }
        case "turn.cancelled": tutorStatus = "응답을 취소했습니다"
        case "question.show": break
        default: throw MnemosyneTutorTransportError.unsupportedFrame
        }
    }

    private func verifyCitationAgainstPage(_ citation: MnemosyneVerifiedCitation,
                                          document: MnemosyneDocument, api: MnemosyneAPIClient) async throws {
        let anchor = citation.anchor
        guard citation.verified, anchor.documentId == document.documentId,
              anchor.versionId == document.versionId, (0..<document.pageCount).contains(anchor.pageIndex) else {
            throw MnemosyneReaderEventError.documentMismatch
        }
        let page = try await api.page(documentId: document.documentId, versionId: document.versionId,
                                      pageIndex: anchor.pageIndex, parseRevision: anchor.parseRevision)
        guard page.documentId == document.documentId, page.versionId == document.versionId,
              page.pageIndex == anchor.pageIndex, page.parseRevision == anchor.parseRevision,
              page.textSha256 == anchor.textSha256,
              SHA256.hash(data: Data(page.text.utf8)).map({ String(format: "%02x", $0) }).joined() == anchor.textSha256 else {
            throw MnemosyneReaderEventError.geometryMismatch
        }
        let scalars = Array(page.text.unicodeScalars)
        guard anchor.startScalar >= 0, anchor.endScalar > anchor.startScalar,
              anchor.endScalar <= scalars.count,
              String(String.UnicodeScalarView(scalars[anchor.startScalar..<anchor.endScalar])) == anchor.quote,
              anchor.rects.allSatisfy({ rectIsInsideCropBox($0, page.geometry.cropBox) }) else {
            throw MnemosyneReaderEventError.geometryMismatch
        }
        let verification = try await api.verifyCitation(anchor)
        guard verification.verified, verification.anchor == anchor else {
            throw MnemosyneReaderEventError.unverifiedCitation
        }
    }

    private func rectIsInsideCropBox(_ rect: [Double], _ cropBox: [Double]) -> Bool {
        guard rect.count == 4, cropBox.count == 4,
              rect.allSatisfy(\.isFinite), cropBox.allSatisfy(\.isFinite), rect[2] > 0, rect[3] > 0 else { return false }
        let tolerance = 0.01
        return rect[0] >= cropBox[0] - tolerance && rect[1] >= cropBox[1] - tolerance &&
            rect[0] + rect[2] <= cropBox[2] + tolerance && rect[1] + rect[3] <= cropBox[3] + tolerance
    }
}
