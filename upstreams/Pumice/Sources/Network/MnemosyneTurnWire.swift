import Combine
import CryptoKit
import Foundation
import PumiceCore
import Security

/// UNIT-04's native /ws boundary. Checkpoint every persisted frame, including
/// frames with no Reader extension. JSON schema validation remains mandatory.
struct MnemosyneTurnFrame {
    let nativeType: String
    let turnID: String?
    let sequence: Int?
    let semanticEvent: Data?
}

enum MnemosyneWireError: Error, Equatable {
    case incompatibleFrame, identityMismatch, terminalMismatch
    case sequenceGap(expected: Int, received: Int)
}

struct MnemosyneSequenceCheckpoint: Sendable {
    private(set) var lastSequence: Int

    init(lastSequence: Int = 0) {
        precondition(lastSequence >= 0)
        self.lastSequence = lastSequence
    }

    func isReplayOrValidateNext(_ sequence: Int) throws -> Bool {
        if sequence <= lastSequence { return false }
        let expected = lastSequence + 1
        guard sequence == expected else {
            throw MnemosyneWireError.sequenceGap(expected: expected, received: sequence)
        }
        return true
    }

    mutating func commit(_ sequence: Int) throws {
        guard sequence == lastSequence + 1 else {
            throw MnemosyneWireError.sequenceGap(expected: lastSequence + 1, received: sequence)
        }
        lastSequence = sequence
    }
}

func decodeMnemosyneTurnFrame(_ data: Data) throws -> MnemosyneTurnFrame {
    guard let frame = try JSONSerialization.jsonObject(with: data) as? [String: Any],
          frame["protocol_version"] as? String == MnemosyneContract.nativeProtocolVersion,
          let nativeType = frame["type"] as? String
    else { throw MnemosyneWireError.incompatibleFrame }
    let turnID = frame["turn_id"] as? String
    let sequence = frame["seq"] as? Int
    let metadata = frame["metadata"] as? [String: Any] ?? [:]
    guard let event = metadata["mnemosyne"] as? [String: Any] else {
        guard nativeType != "done" else { throw MnemosyneWireError.terminalMismatch }
        return MnemosyneTurnFrame(nativeType: nativeType, turnID: turnID,
                                  sequence: sequence, semanticEvent: nil)
    }
    guard let turnID, let sequence, sequence > 0,
          event["contract_version"] as? String == MnemosyneContract.version,
          event["turn_id"] as? String == turnID, event["seq"] as? Int == sequence,
          event["event_id"] as? String == "\(turnID):\(sequence)",
          let kind = event["type"] as? String,
          let payload = event["payload"] as? [String: Any],
          isKnownMnemosyneEvent(kind), hasRequiredEventPayload(kind, payload)
    else { throw MnemosyneWireError.identityMismatch }
    let terminal = ["completed": "turn.done", "failed": "turn.error", "cancelled": "turn.cancelled"]
    if nativeType == "done" {
        guard kind == terminal[metadata["status"] as? String ?? ""] else {
            throw MnemosyneWireError.terminalMismatch
        }
    } else if terminal.values.contains(kind) {
        throw MnemosyneWireError.terminalMismatch
    }
    guard let createdAt = event["created_at"] as? String,
          isISO8601Date(createdAt),
          Set(event.keys) == ["contract_version", "event_id", "turn_id", "seq", "created_at", "type", "payload"]
    else { throw MnemosyneWireError.incompatibleFrame }
    return MnemosyneTurnFrame(nativeType: nativeType, turnID: turnID, sequence: sequence,
                             semanticEvent: try JSONSerialization.data(withJSONObject: event))
}

private func isKnownMnemosyneEvent(_ type: String) -> Bool {
    ["turn.started", "assistant.delta", "citation.verified", "reader.goto", "reader.highlight",
     "reader.flash", "reader.annotate", "quiz.show", "question.show", "learning.updated",
     "turn.done", "turn.error", "turn.cancelled"].contains(type)
}

private func hasRequiredEventPayload(_ type: String, _ payload: [String: Any]) -> Bool {
    let required: [String: Set<String>] = [
        "turn.started": ["capability", "response_language"],
        "assistant.delta": ["text"],
        "citation.verified": ["citation"],
        "reader.goto": ["target", "position", "citation_id"],
        "reader.highlight": ["target", "rects", "citation_id", "ttl_ms", "persistent"],
        "reader.flash": ["target", "rects", "citation_id", "ttl_ms", "persistent"],
        "reader.annotate": ["annotation", "citation_id", "requires_confirmation", "suggested_mutation_id"],
        "quiz.show": ["quiz_id"],
        "question.show": ["quiz_id", "question_id"],
        "learning.updated": ["document_id", "learning_revision"],
        "turn.done": ["summary_ko", "learning_revision"],
        "turn.error": ["error"],
        "turn.cancelled": ["reason"]
    ]
    guard let keys = required[type], keys.isSubset(of: Set(payload.keys)) else { return false }
    func exactKeys(_ expected: Set<String>) -> Bool { Set(payload.keys) == expected }
    switch type {
    case "turn.started":
        return exactKeys(["capability", "response_language"]) &&
            payload["capability"] is String && payload["response_language"] is String
    case "assistant.delta": return exactKeys(["text"]) && payload["text"] is String
    case "reader.highlight", "reader.flash":
        guard exactKeys(["target", "rects", "citation_id", "ttl_ms", "persistent"]),
              payload["target"] is [String: Any], let rects = payload["rects"] as? [[Double]],
              !rects.isEmpty, rects.allSatisfy({ $0.count == 4 && $0.allSatisfy(\.isFinite) && $0[2] > 0 && $0[3] > 0 }),
              let ttl = payload["ttl_ms"] as? Int, (100...10_000).contains(ttl),
              let citationId = payload["citation_id"] as? String, UUID(uuidString: citationId) != nil,
              (payload["persistent"] as? Bool) == false else { return false }
        return true
    case "reader.goto":
        guard exactKeys(["target", "position", "citation_id"]), payload["target"] is [String: Any],
              let position = payload["position"] as? [Double], position.count == 2,
              position.allSatisfy(\.isFinite),
              let citationId = payload["citation_id"] as? String, UUID(uuidString: citationId) != nil else {
            return false
        }
        return true
    case "reader.annotate":
        guard exactKeys(["annotation", "citation_id", "requires_confirmation", "suggested_mutation_id"]),
              payload["annotation"] is [String: Any],
              let citationId = payload["citation_id"] as? String, UUID(uuidString: citationId) != nil,
              (payload["requires_confirmation"] as? Bool) == true,
              let mutationId = payload["suggested_mutation_id"] as? String, UUID(uuidString: mutationId) != nil
        else { return false }
        return true
    case "citation.verified": return exactKeys(["citation"]) && payload["citation"] is [String: Any]
    case "quiz.show":
        return exactKeys(["quiz_id"]) && (payload["quiz_id"] as? String).flatMap(UUID.init(uuidString:)) != nil
    case "question.show":
        return exactKeys(["quiz_id", "question_id"]) &&
            (payload["quiz_id"] as? String).flatMap(UUID.init(uuidString:)) != nil &&
            (payload["question_id"] as? String).flatMap(UUID.init(uuidString:)) != nil
    case "learning.updated":
        return exactKeys(["document_id", "learning_revision"]) &&
            (payload["document_id"] as? String).flatMap(UUID.init(uuidString:)) != nil &&
            (payload["learning_revision"] as? Int ?? 0) > 0
    case "turn.done":
        return exactKeys(["summary_ko", "learning_revision"]) && payload["summary_ko"] is String &&
            (payload["learning_revision"] as? Int ?? 0) > 0
    case "turn.error": return exactKeys(["error"]) && payload["error"] is [String: Any]
    case "turn.cancelled":
        return exactKeys(["reason"]) && ["user_cancelled", "server_shutdown"].contains(payload["reason"] as? String ?? "")
    default: return false
    }
}

private func isISO8601Date(_ value: String) -> Bool {
    let standard = ISO8601DateFormatter()
    if standard.date(from: value) != nil { return true }
    standard.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return standard.date(from: value) != nil
}

enum MnemosyneContract {
    static let version = "0.1.0"
    static let nativeProtocolVersion = "2.0"
}

struct MnemosyneSubject: Codable, Identifiable, Hashable, Sendable {
    let subjectId: UUID
    let name: String
    let serverRevision: Int
    var id: UUID { subjectId }
}

struct MnemosyneSubjectWrite: Codable, Sendable {
    let name: String
}

struct MnemosyneDocument: Codable, Identifiable, Hashable, Sendable {
    enum ParseState: String, Codable, Sendable { case pending, running, ready, failed }
    enum IndexState: String, Codable, Sendable { case pending, running, ready, failed }

    let documentId: UUID
    let versionId: String
    let sourceSha256: String
    let title: String
    let subjectId: UUID?
    let contentLanguage: String
    let pageCount: Int
    let serverRevision: Int
    let originalAvailable: Bool
    let parseState: ParseState
    let indexState: IndexState
    let createdAt: String
    var id: UUID { documentId }

    var isTutorReady: Bool { parseState == .ready && indexState == .ready }
}

struct MnemosyneDocumentUpdate: Encodable, Sendable {
    let title: String?
    let subjectId: UUID?
    private let includesSubjectId: Bool
    init(title: String? = nil, subjectId: UUID? = nil, includesSubjectId: Bool = false) {
        self.title = title
        self.subjectId = subjectId
        self.includesSubjectId = includesSubjectId
    }

    private enum CodingKeys: String, CodingKey { case title, subjectId }
    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encodeIfPresent(title, forKey: .title)
        if includesSubjectId {
            if let subjectId { try values.encode(subjectId, forKey: .subjectId) }
            else { try values.encodeNil(forKey: .subjectId) }
        }
    }
}

struct MnemosyneReadiness: Codable, Sendable {
    enum Status: String, Codable, Sendable { case ready, degraded, starting }
    enum ComponentState: String, Codable, Sendable { case ready, pending, failed, disabled }
    enum Capability: String, Codable, CaseIterable, Sendable {
        case chat, reading, quiz, assessment, mastery, solve, memory, progress, review
    }
    struct Components: Codable, Sendable {
        let database: ComponentState
        let storage: ComponentState
        let parser: ComponentState
        let index: ComponentState
        let provider: ComponentState
    }

    let contractVersion: String
    let status: Status
    let components: Components
    let capabilities: [Capability]
    let eventResumeSeconds: Int
}

struct MnemosynePublicSettings: Decodable, Sendable {
    struct Provider: Decodable, Sendable {
        let adapter: String
        let baseUrl: String
        let model: String
        let credentialConfigured: Bool
    }
    let serverRevision: Int
    let provider: Provider
    let responseLanguage: String
}

struct MnemosynePairRequest: Codable, Sendable {
    let oneTimeCode: String
    let deviceName: String
}

struct MnemosynePairReceipt: Codable, Sendable {
    let deviceId: UUID
    let accessToken: String
    let tokenType: String
    let expiresAt: String
}

struct MnemosyneErrorEnvelope: Decodable, Sendable {
    struct Details: Decodable, Sendable {
        let currentRevision: Int?
        let retryAfterSeconds: Int?
    }
    let contractVersion: String
    let code: String
    let messageKo: String
    let requestId: UUID
    let retryable: Bool
    let details: Details
}

struct MnemosynePage: Decodable, Sendable {
    struct Geometry: Decodable, Sendable {
        let mediaBox: [Double]
        let cropBox: [Double]
        let rotationDegrees: Int
        let userUnit: Double
    }
    struct Segment: Decodable, Sendable {
        let startScalar: Int
        let endScalar: Int
        let rect: [Double]
    }
    let documentId: UUID
    let versionId: String
    let pageIndex: Int
    let displayPageNumber: Int
    let displayLabel: String
    let parseRevision: String
    let textBasis: String
    let text: String
    let textSha256: String
    let geometry: Geometry
    let segments: [Segment]
}

struct MnemosyneTextAnchor: Codable, Sendable, Equatable {
    let documentId: UUID
    let versionId: String
    let pageIndex: Int
    let parseRevision: String
    let textSha256: String
    let startScalar: Int
    let endScalar: Int
    let quote: String
    let rects: [[Double]]
}

struct MnemosyneVerifiedCitation: Decodable, Sendable, Equatable {
    let citationId: UUID
    let verificationId: UUID
    let verified: Bool
    let anchor: MnemosyneTextAnchor
}

struct MnemosyneQuiz: Decodable, Identifiable, Sendable {
    struct Question: Decodable, Identifiable, Sendable {
        struct Choice: Decodable, Identifiable, Sendable {
            let choiceId: String
            let text: String
            var id: String { choiceId }
        }
        let questionId: UUID
        let prompt: String
        let kind: String
        let choices: [Choice]
        let citations: [MnemosyneVerifiedCitation]
        var id: UUID { questionId }
    }
    let quizId: UUID
    let documentId: UUID
    let versionId: String
    let title: String
    let questions: [Question]
    let responseLanguage: String
    var id: UUID { quizId }
}

struct MnemosyneAttempt: Encodable, Sendable {
    struct Answer: Encodable, Sendable {
        let questionId: UUID
        let answer: String
    }
    let attemptId: UUID
    let clientMutationId: UUID
    let quizId: UUID
    let documentId: UUID
    let versionId: String
    let baseLearningRevision: Int
    let submittedAt: String
    let answers: [Answer]
}

struct MnemosyneAssessment: Decodable, Sendable {
    let attemptId: UUID
    let score: Double
    let feedbackKo: String
    let learningRevision: Int
    let citations: [MnemosyneVerifiedCitation]
}

struct MnemosyneLearningState: Decodable, Sendable {
    struct QuizAttempt: Decodable, Sendable {
        let attemptId: UUID
        let quizId: UUID
        let score: Double
    }
    struct Mastery: Decodable, Identifiable, Sendable {
        let conceptId: String
        let labelKo: String
        let score: Double
        let evidenceAttemptIds: [UUID]
        var id: String { conceptId }
    }
    struct Memory: Decodable, Identifiable, Sendable {
        let memoryId: UUID
        let frontKo: String
        let backKo: String
        let dueAt: String
        let reviewCount: Int
        let citations: [MnemosyneVerifiedCitation]
        var id: UUID { memoryId }
    }
    struct Progress: Decodable, Sendable {
        let lastPageIndex: Int
        let pagesRead: [Int]
        let readingSeconds: Int
        let nextReviewAt: String
    }
    struct Activity: Decodable, Identifiable, Sendable {
        let activityId: UUID
        let kind: String
        let turnId: String?
        let summaryKo: String
        let createdAt: String
        var id: UUID { activityId }
    }

    let documentId: UUID
    let versionId: String
    let learningRevision: Int
    let quizAttempts: [QuizAttempt]
    let mastery: [Mastery]
    let memory: [Memory]
    let progress: Progress
    let activities: [Activity]
}

struct MnemosyneMemoryReview: Encodable, Sendable {
    let clientMutationId: UUID
    let memoryId: UUID
    let baseLearningRevision: Int
    let grade: Int
    let reviewedAt: String
}

enum MnemosyneAPIError: Error, LocalizedError, Sendable {
    case invalidServerURL
    case pairingRequired
    case invalidResponse
    case contractMismatch(expected: String, received: String?)
    case server(status: Int, code: String, message: String, requestId: UUID?, retryable: Bool, retryAfter: Int?)
    case invalidPDF

    var errorDescription: String? {
        switch self {
        case .invalidServerURL:
            return "서버 주소를 확인해 주세요. HTTPS 주소 또는 로컬 네트워크 주소를 입력할 수 있습니다."
        case .pairingRequired:
            return "이 기기를 서버와 연결해야 합니다."
        case .invalidResponse:
            return "서버 응답을 읽을 수 없습니다. 서버 버전과 연결 상태를 확인해 주세요."
        case let .contractMismatch(expected, received):
            return "앱 계약 버전은 \(expected)입니다. 서버 응답 버전은 \(received ?? "확인 불가")입니다."
        case let .server(_, _, message, _, _, _):
            return message
        case .invalidPDF:
            return "다운로드한 PDF의 형식 또는 원본 해시가 문서 정보와 일치하지 않습니다."
        }
    }

    var retryAfterSeconds: Int? {
        if case let .server(_, _, _, _, _, value) = self { return value }
        return nil
    }
}

struct MnemosynePairingInfo: Sendable {
    let deviceId: UUID
    let expiresAt: String
}

/// Pairing bearer credentials stay in Keychain; this actor never exposes them to views.
actor MnemosyneTokenStore {
    static let shared = MnemosyneTokenStore()
    private let service = Bundle.main.bundleIdentifier ?? "org.mnemosyne.ipad"
    private let account = "paired-device-bearer"

    func read() -> String? {
        var query = baseQuery
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    func save(_ token: String) throws {
        let data = Data(token.utf8)
        let status = SecItemUpdate(baseQuery as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var query = baseQuery
            query[kSecValueData as String] = data
            query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            let addStatus = SecItemAdd(query as CFDictionary, nil)
            guard addStatus == errSecSuccess else { throw MnemosyneKeychainError(status: addStatus) }
        } else if status != errSecSuccess {
            throw MnemosyneKeychainError(status: status)
        }
    }

    func delete() throws {
        let status = SecItemDelete(baseQuery as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw MnemosyneKeychainError(status: status)
        }
    }

    private var baseQuery: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }
}

private struct MnemosyneKeychainError: Error, Sendable {
    let status: OSStatus
}

/// Contract-backed client. `/health` and `/ready` are observed upstream endpoints;
/// `/v1/*` methods are clients for the planned Mnemosyne HTTP extensions.
actor MnemosyneAPIClient {
    private let baseURL: URL
    private let session: URLSession
    private let tokenStore: MnemosyneTokenStore

    init(baseURL: URL, session: URLSession = .shared, tokenStore: MnemosyneTokenStore = .shared) throws {
        guard Self.isAllowedServerURL(baseURL) else { throw MnemosyneAPIError.invalidServerURL }
        self.baseURL = baseURL
        self.session = session
        self.tokenStore = tokenStore
    }

    static func validatedURL(_ rawValue: String) throws -> URL {
        guard let url = URL(string: rawValue.trimmingCharacters(in: .whitespacesAndNewlines)),
              isAllowedServerURL(url) else { throw MnemosyneAPIError.invalidServerURL }
        return url
    }

    static func isAllowedServerURL(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased(),
              ["https", "http"].contains(scheme),
              let host = url.host?.lowercased(),
              !host.isEmpty,
              url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else { return false }
        if scheme == "https" { return true }
        if host == "localhost" || host == "127.0.0.1" || host == "::1" { return true }
        let octets = host.split(separator: ".").compactMap { Int($0) }
        guard octets.count == 4, octets.allSatisfy({ (0...255).contains($0) }) else { return false }
        return octets[0] == 10 ||
            (octets[0] == 192 && octets[1] == 168) ||
            (octets[0] == 172 && (16...31).contains(octets[1]))
    }

    func isPaired() async -> Bool { await tokenStore.read() != nil }

    func health() async throws {
        let (data, response) = try await perform(path: "health", method: "GET", authenticated: false, contractHeader: false)
        guard (200..<300).contains(response.statusCode),
              let body = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              body["status"] == "alive" else { throw MnemosyneAPIError.invalidResponse }
    }

    /// Observed DeepTutor readiness endpoint; distinct from the planned typed Mnemosyne readiness API.
    func serverReady() async throws -> Bool {
        let (_, response) = try await perform(path: "ready", method: "GET", authenticated: false,
                                              contractHeader: false)
        if response.statusCode == 200 { return true }
        if response.statusCode == 503 { return false }
        throw MnemosyneAPIError.server(status: response.statusCode, code: "server_not_ready",
            message: "서버 준비 상태를 확인할 수 없습니다.", requestId: nil,
            retryable: response.statusCode >= 500, retryAfter: Self.retryAfter(response))
    }

    func readiness() async throws -> MnemosyneReadiness {
        let value: MnemosyneReadiness = try await get("v1/readiness")
        guard value.contractVersion == MnemosyneContract.version else {
            throw MnemosyneAPIError.contractMismatch(expected: MnemosyneContract.version, received: value.contractVersion)
        }
        return value
    }

    func pair(oneTimeCode: String, deviceName: String) async throws -> MnemosynePairingInfo {
        let request = MnemosynePairRequest(oneTimeCode: oneTimeCode, deviceName: deviceName)
        let data = try JSONEncoder.mnemosyne.encode(request)
        let (responseData, response) = try await perform(path: "v1/session/pair", method: "POST", body: data,
                                                          authenticated: false)
        try requireSuccess(responseData, response)
        let receipt = try JSONDecoder.mnemosyne.decode(MnemosynePairReceipt.self, from: responseData)
        guard receipt.tokenType == "Bearer", receipt.accessToken.count >= 32 else {
            throw MnemosyneAPIError.invalidResponse
        }
        try await tokenStore.save(receipt.accessToken)
        return MnemosynePairingInfo(deviceId: receipt.deviceId, expiresAt: receipt.expiresAt)
    }

    func unpair() async throws {
        _ = try await requestJSON(path: "v1/session", method: "DELETE", authenticated: true,
                                  as: [String: Bool].self)
        try await tokenStore.delete()
    }

    func subjects() async throws -> [MnemosyneSubject] { try await get("v1/subjects") }

    func createSubject(name: String) async throws -> MnemosyneSubject {
        try await send("v1/subjects", method: "POST", body: MnemosyneSubjectWrite(name: name))
    }

    func updateSubject(_ subject: MnemosyneSubject, name: String) async throws -> MnemosyneSubject {
        try await send("v1/subjects/\(subject.subjectId.uuidString.lowercased())", method: "PATCH",
                       body: MnemosyneSubjectWrite(name: name), ifMatch: subject.serverRevision)
    }

    func deleteSubject(_ subject: MnemosyneSubject) async throws {
        let _: [String: Bool] = try await requestJSON(path: "v1/subjects/\(subject.subjectId.uuidString.lowercased())",
            method: "DELETE", authenticated: true, ifMatch: subject.serverRevision, as: [String: Bool].self)
    }

    func documents(subjectId: UUID? = nil) async throws -> [MnemosyneDocument] {
        var query: [URLQueryItem] = []
        if let subjectId { query.append(URLQueryItem(name: "subject_id", value: subjectId.uuidString.lowercased())) }
        return try await get("v1/documents", query: query)
    }

    func updateDocument(_ document: MnemosyneDocument, title: String? = nil,
                        subjectId: UUID? = nil, includesSubjectId: Bool = false) async throws -> MnemosyneDocument {
        try await send("v1/documents/\(document.documentId.uuidString.lowercased())", method: "PATCH",
                       body: MnemosyneDocumentUpdate(title: title, subjectId: subjectId,
                                                     includesSubjectId: includesSubjectId),
                       ifMatch: document.serverRevision)
    }

    func deleteDocument(_ document: MnemosyneDocument) async throws {
        let path = "v1/documents/\(document.documentId.uuidString.lowercased())"
        let _: [String: Bool] = try await requestJSON(path: path, method: "DELETE", authenticated: true,
            ifMatch: document.serverRevision,
            extraHeaders: ["X-Confirm-Action": "document.delete:\(document.documentId.uuidString.lowercased())"],
            as: [String: Bool].self)
    }

    func uploadDocument(fileURL: URL, title: String, subjectId: UUID? = nil) async throws -> MnemosyneDocument {
        guard fileURL.isFileURL, try Self.hasPDFMagic(at: fileURL) else { throw MnemosyneAPIError.invalidPDF }
        let boundary = "Mnemosyne-\(UUID().uuidString)"
        let stagingURL = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).multipart")
        defer { try? FileManager.default.removeItem(at: stagingURL) }
        try Self.writeMultipart(to: stagingURL, source: fileURL, title: title, subjectId: subjectId, boundary: boundary)

        var request = URLRequest(url: endpoint("v1/documents"))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        addContractHeader(to: &request)
        try await addBearer(to: &request)
        let (data, response) = try await session.upload(for: request, fromFile: stagingURL)
        guard let http = response as? HTTPURLResponse else { throw MnemosyneAPIError.invalidResponse }
        try requireContractVersion(http)
        try requireSuccess(data, http)
        return try JSONDecoder.mnemosyne.decode(MnemosyneDocument.self, from: data)
    }

    /// Returns the URLSession temporary file only after checking PDF magic and the
    /// full source SHA-256. The caller must immediately install it via the Reader facade.
    func downloadOriginal(_ document: MnemosyneDocument) async throws -> URL {
        guard document.originalAvailable else { throw MnemosyneAPIError.invalidPDF }
        let path = "v1/documents/\(document.documentId.uuidString.lowercased())/file"
        let query = [URLQueryItem(name: "version_id", value: document.versionId)]
        var request = URLRequest(url: endpoint(path, query: query))
        request.httpMethod = "GET"
        addContractHeader(to: &request)
        try await addBearer(to: &request)
        let (url, response) = try await session.download(for: request)
        guard let http = response as? HTTPURLResponse else { throw MnemosyneAPIError.invalidResponse }
        try requireContractVersion(http)
        if !(200..<300).contains(http.statusCode) {
            let errorData = (try? Data(contentsOf: url)) ?? Data()
            try requireSuccess(errorData, http)
        }
        guard response.mimeType?.lowercased() == "application/pdf",
              try Self.hasPDFMagic(at: url),
              try Self.sha256(of: url) == document.sourceSha256 else { throw MnemosyneAPIError.invalidPDF }
        return url
    }

    func page(documentId: UUID, versionId: String, pageIndex: Int, parseRevision: String) async throws -> MnemosynePage {
        let path = "v1/documents/\(documentId.uuidString.lowercased())/pages/\(pageIndex)"
        return try await get(path, query: [URLQueryItem(name: "version_id", value: versionId),
                                           URLQueryItem(name: "parse_revision", value: parseRevision)])
    }

    func search(documentId: UUID, versionId: String, query: String, limit: Int = 20) async throws -> [MnemosyneTextAnchor] {
        struct Body: Encodable, Sendable { let query: String; let versionId: String; let limit: Int }
        return try await send("v1/documents/\(documentId.uuidString.lowercased())/search", method: "POST",
                              body: Body(query: query, versionId: versionId, limit: min(max(limit, 1), 100)))
    }

    func verifyCitation(_ anchor: MnemosyneTextAnchor) async throws -> MnemosyneVerifiedCitation {
        try await send("v1/citations/verify", method: "POST", body: anchor)
    }

    func annotationSnapshot(documentId: UUID, versionId: String) async throws -> Data {
        try await getData("v1/documents/\(documentId.uuidString.lowercased())/annotations/snapshot",
                          query: [URLQueryItem(name: "version_id", value: versionId)])
    }

    func annotationChanges(documentId: UUID, versionId: String, cursor: String, limit: Int = 100) async throws -> Data {
        try await getData("v1/documents/\(documentId.uuidString.lowercased())/annotations/changes",
            query: [URLQueryItem(name: "version_id", value: versionId),
                    URLQueryItem(name: "cursor", value: cursor),
                    URLQueryItem(name: "limit", value: String(min(max(limit, 1), 500)))])
    }

    func applyAnnotationMutations(documentId: UUID, batch: Data) async throws -> Data {
        try await postData("v1/documents/\(documentId.uuidString.lowercased())/annotations/mutations", body: batch)
    }

    func quiz(quizId: UUID) async throws -> MnemosyneQuiz {
        try await get("v1/quizzes/\(quizId.uuidString.lowercased())")
    }

    func submitAttempt(_ attempt: MnemosyneAttempt) async throws -> MnemosyneAssessment {
        try await send("v1/quizzes/\(attempt.quizId.uuidString.lowercased())/attempts", method: "POST", body: attempt)
    }

    func learning(documentId: UUID, versionId: String) async throws -> MnemosyneLearningState {
        try await get("v1/documents/\(documentId.uuidString.lowercased())/learning",
                      query: [URLQueryItem(name: "version_id", value: versionId)])
    }

    func reviewMemory(_ review: MnemosyneMemoryReview) async throws -> MnemosyneLearningState {
        try await send("v1/memory/\(review.memoryId.uuidString.lowercased())/reviews", method: "POST", body: review)
    }

    func turnReceipt(turnId: String) async throws -> MnemosyneTurnReceipt {
        guard turnId.range(of: #"^[A-Za-z0-9_-]{1,256}$"#, options: .regularExpression) != nil else {
            throw MnemosyneAPIError.invalidResponse
        }
        return try await get("v1/tutor/turns/\(turnId)")
    }

    func settings() async throws -> MnemosynePublicSettings { try await get("v1/settings") }

    func exportReceipt(documentId: UUID, body: Data) async throws -> Data {
        try await postData("v1/documents/\(documentId.uuidString.lowercased())/exports", body: body)
    }

    func downloadExport(exportId: UUID) async throws -> URL {
        let path = "v1/exports/\(exportId.uuidString.lowercased())/file"
        var request = URLRequest(url: endpoint(path))
        request.httpMethod = "GET"
        addContractHeader(to: &request)
        try await addBearer(to: &request)
        let (url, response) = try await session.download(for: request)
        guard let http = response as? HTTPURLResponse else { throw MnemosyneAPIError.invalidResponse }
        try requireContractVersion(http)
        if !(200..<300).contains(http.statusCode) {
            try requireSuccess((try? Data(contentsOf: url)) ?? Data(), http)
        }
        guard response.mimeType?.lowercased() == "application/pdf", try Self.hasPDFMagic(at: url) else {
            throw MnemosyneAPIError.invalidPDF
        }
        return url
    }

    private func get<T: Decodable & Sendable>(_ path: String, query: [URLQueryItem] = []) async throws -> T {
        let data = try await getData(path, query: query)
        return try decode(T.self, from: data)
    }

    private func send<Body: Encodable & Sendable, Response: Decodable & Sendable>(
        _ path: String, method: String, body: Body, ifMatch: Int? = nil
    ) async throws -> Response {
        let bodyData = try JSONEncoder.mnemosyne.encode(body)
        return try await requestJSON(path: path, method: method, body: bodyData,
                                     authenticated: true, ifMatch: ifMatch)
    }

    private func requestJSON<Response: Decodable & Sendable>(
        path: String, method: String, body: Data? = nil, authenticated: Bool,
        ifMatch: Int? = nil, extraHeaders: [String: String] = [:], as type: Response.Type
    ) async throws -> Response {
        let (data, response) = try await perform(path: path, method: method, body: body,
            authenticated: authenticated, ifMatch: ifMatch, extraHeaders: extraHeaders)
        try requireSuccess(data, response)
        return try decode(type, from: data)
    }

    private func getData(_ path: String, query: [URLQueryItem] = []) async throws -> Data {
        let (data, response) = try await perform(path: path, method: "GET", query: query)
        try requireSuccess(data, response)
        return data
    }

    private func postData(_ path: String, body: Data) async throws -> Data {
        let (data, response) = try await perform(path: path, method: "POST", body: body)
        try requireSuccess(data, response)
        return data
    }

    private func perform(path: String, method: String, body: Data? = nil,
                         query: [URLQueryItem] = [], authenticated: Bool = true,
                         contractHeader: Bool = true, ifMatch: Int? = nil,
                         extraHeaders: [String: String] = [:]) async throws -> (Data, HTTPURLResponse) {
        var request = URLRequest(url: endpoint(path, query: query))
        request.httpMethod = method
        request.httpBody = body
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if contractHeader { addContractHeader(to: &request) }
        if let ifMatch { request.setValue("\"\(ifMatch)\"", forHTTPHeaderField: "If-Match") }
        for (name, value) in extraHeaders { request.setValue(value, forHTTPHeaderField: name) }
        if authenticated { try await addBearer(to: &request) }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw MnemosyneAPIError.invalidResponse }
        if contractHeader { try requireContractVersion(http) }
        return (data, http)
    }

    private func endpoint(_ path: String, query: [URLQueryItem] = []) -> URL {
        var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false)!
        let prefix = components.path == "/" ? "" : components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = "/" + [prefix, path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))]
            .filter { !$0.isEmpty }.joined(separator: "/")
        if !query.isEmpty { components.queryItems = query }
        return components.url!
    }

    private func addContractHeader(to request: inout URLRequest) {
        request.setValue(MnemosyneContract.version, forHTTPHeaderField: "X-Mnemosyne-Contract-Version")
    }

    private func requireContractVersion(_ response: HTTPURLResponse) throws {
        let received = response.value(forHTTPHeaderField: "X-Mnemosyne-Contract-Version")
        guard received == MnemosyneContract.version else {
            throw MnemosyneAPIError.contractMismatch(expected: MnemosyneContract.version, received: received)
        }
    }

    private func addBearer(to request: inout URLRequest) async throws {
        guard let token = await tokenStore.read(), !token.isEmpty else { throw MnemosyneAPIError.pairingRequired }
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }

    private func requireSuccess(_ data: Data, _ response: HTTPURLResponse) throws {
        guard (200..<300).contains(response.statusCode) else {
            let envelope = try? JSONDecoder.mnemosyne.decode(MnemosyneErrorEnvelope.self, from: data)
            if let envelope, envelope.contractVersion != MnemosyneContract.version {
                throw MnemosyneAPIError.contractMismatch(expected: MnemosyneContract.version,
                                                         received: envelope.contractVersion)
            }
            throw MnemosyneAPIError.server(status: response.statusCode,
                code: envelope?.code ?? "http_\(response.statusCode)",
                message: envelope?.messageKo ?? "서버 요청을 처리하지 못했습니다. (\(response.statusCode))",
                requestId: envelope?.requestId, retryable: envelope?.retryable ?? response.statusCode >= 500,
                retryAfter: envelope?.details.retryAfterSeconds ?? Self.retryAfter(response))
        }
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            let value = try JSONDecoder.mnemosyne.decode(type, from: data)
            if let versioned = value as? any MnemosyneVersionedResponse,
               versioned.contractVersion != MnemosyneContract.version {
                throw MnemosyneAPIError.contractMismatch(expected: MnemosyneContract.version,
                                                         received: versioned.contractVersion)
            }
            return value
        } catch let error as MnemosyneAPIError {
            throw error
        } catch {
            throw MnemosyneAPIError.invalidResponse
        }
    }

    private static func retryAfter(_ response: HTTPURLResponse) -> Int? {
        guard let value = response.value(forHTTPHeaderField: "Retry-After") else { return nil }
        return Int(value)
    }

    private static func hasPDFMagic(at url: URL) throws -> Bool {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        return try handle.read(upToCount: 5) == Data("%PDF-".utf8)
    }

    private static func sha256(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 1024 * 1024), !chunk.isEmpty { hasher.update(data: chunk) }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func writeMultipart(to destination: URL, source: URL, title: String,
                                       subjectId: UUID?, boundary: String) throws {
        guard let input = try? FileHandle(forReadingFrom: source) else { throw MnemosyneAPIError.invalidPDF }
        defer { try? input.close() }
        guard FileManager.default.createFile(atPath: destination.path, contents: nil) else {
            throw MnemosyneAPIError.invalidResponse
        }
        let handle = try FileHandle(forWritingTo: destination)
        defer { try? handle.close() }
        func write(_ string: String) throws { try handle.write(contentsOf: Data(string.utf8)) }
        let safeTitle = title.replacingOccurrences(of: "\r", with: " ").replacingOccurrences(of: "\n", with: " ")
        try write("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"document.pdf\"\r\nContent-Type: application/pdf\r\n\r\n")
        while let chunk = try input.read(upToCount: 1024 * 1024), !chunk.isEmpty { try handle.write(contentsOf: chunk) }
        try write("\r\n--\(boundary)\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\n\(safeTitle)\r\n")
        if let subjectId {
            try write("--\(boundary)\r\nContent-Disposition: form-data; name=\"subject_id\"\r\n\r\n\(subjectId.uuidString.lowercased())\r\n")
        }
        try write("--\(boundary)--\r\n")
    }
}

private protocol MnemosyneVersionedResponse { var contractVersion: String { get } }
extension MnemosyneReadiness: MnemosyneVersionedResponse {}

extension JSONDecoder {
    static var mnemosyne: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}

extension JSONEncoder {
    static var mnemosyne: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }
}

enum MnemosyneTutorTransportError: Error, LocalizedError {
    case invalidCommand
    case missingTurnIdentity
    case sequenceGap(expected: Int, received: Int)
    case protocolRejected(String)
    case unsupportedFrame

    var errorDescription: String? {
        switch self {
        case .invalidCommand: return "튜터 요청 형식이 서버 계약과 다릅니다."
        case .missingTurnIdentity: return "서버가 이어받을 학습 요청 ID를 반환하지 않았습니다."
        case let .sequenceGap(expected, received):
            return "응답 순서가 끊겼습니다. (예상 \(expected), 수신 \(received))"
        case let .protocolRejected(message): return message
        case .unsupportedFrame: return "지원하지 않는 튜터 스트림 프레임입니다."
        }
    }
}

/// One native DeepTutor `/ws` turn. Every persisted native frame is checkpointed
/// before its Mnemosyne semantic event reaches the UI or Reader.
@MainActor
final class MnemosyneTutorTransport {
    typealias Checkpoint = @MainActor @Sendable (_ turnId: String, _ sequence: Int, _ rawFrame: Data) async throws -> Void
    typealias EventHandler = @MainActor @Sendable (_ event: Data) async throws -> Void

    private let baseURL: URL
    private let session: URLSession
    private let tokenStore: MnemosyneTokenStore
    private var socket: URLSessionWebSocketTask?
    private var activeTurnId: String?
    private var sequenceCheckpoint = MnemosyneSequenceCheckpoint()
    private var activeCancelCommandId: UUID?

    init(baseURL: URL, session: URLSession = .shared, tokenStore: MnemosyneTokenStore = .shared) {
        self.baseURL = baseURL
        self.session = session
        self.tokenStore = tokenStore
    }

    var turnId: String? { activeTurnId }
    var checkpointSequence: Int { sequenceCheckpoint.lastSequence }

    func run(startCommand: Data? = nil, resumeTurnId: String? = nil, afterSequence: Int = 0,
             checkpoint: @escaping Checkpoint, onEvent: @escaping EventHandler) async throws {
        guard afterSequence >= 0,
              (resumeTurnId != nil || startCommand.map(Self.isNativeStartCommand) == true) else {
            throw MnemosyneTutorTransportError.invalidCommand
        }
        activeTurnId = resumeTurnId
        sequenceCheckpoint = MnemosyneSequenceCheckpoint(lastSequence: afterSequence)
        var reconnectAttempt = 0
        var shouldSendStart = resumeTurnId == nil

        while !Task.isCancelled {
            do {
                let task = try await connect()
                if shouldSendStart {
                    guard let startCommand,
                          let commandText = String(data: startCommand, encoding: .utf8) else {
                        throw MnemosyneTutorTransportError.invalidCommand
                    }
                    try await task.send(.string(commandText))
                    shouldSendStart = false
                } else if let activeTurnId {
                    let resume = try Self.resumeCommand(turnId: activeTurnId,
                                                        sequence: sequenceCheckpoint.lastSequence)
                    guard let resumeText = String(data: resume, encoding: .utf8) else {
                        throw MnemosyneTutorTransportError.invalidCommand
                    }
                    try await task.send(.string(resumeText))
                } else {
                    throw MnemosyneTutorTransportError.missingTurnIdentity
                }

                reconnectAttempt = 0
                try await receiveLoop(task, checkpoint: checkpoint, onEvent: onEvent)
                return
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                socket?.cancel(with: .goingAway, reason: nil)
                socket = nil
                if Task.isCancelled { throw CancellationError() }
                guard activeTurnId != nil else { throw error }
                reconnectAttempt += 1
                try await Self.backoff(attempt: reconnectAttempt)
            }
        }
        throw CancellationError()
    }

    /// Uses one stable command ID for retries; the native server treats it as an
    /// idempotent cancel command. Calling cancel never resets the read checkpoint.
    func cancel(commandId: UUID) async throws {
        guard let activeTurnId, let socket else { throw MnemosyneTutorTransportError.missingTurnIdentity }
        if activeCancelCommandId == nil { activeCancelCommandId = commandId }
        guard activeCancelCommandId == commandId else { throw MnemosyneTutorTransportError.invalidCommand }
        let body: [String: Any] = [
            "type": "cancel_turn",
            "protocol_version": MnemosyneContract.nativeProtocolVersion,
            "turn_id": activeTurnId,
            "command_id": commandId.uuidString.lowercased()
        ]
        let data = try JSONSerialization.data(withJSONObject: body, options: [.sortedKeys])
        guard let commandText = String(data: data, encoding: .utf8) else {
            throw MnemosyneTutorTransportError.invalidCommand
        }
        try await socket.send(.string(commandText))
    }

    func close() {
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
    }

    private func connect() async throws -> URLSessionWebSocketTask {
        guard let token = await tokenStore.read(), !token.isEmpty,
              let url = Self.webSocketURL(from: baseURL) else { throw MnemosyneAPIError.pairingRequired }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(Self.origin(from: baseURL), forHTTPHeaderField: "Origin")
        request.setValue(MnemosyneContract.version, forHTTPHeaderField: "X-Mnemosyne-Contract-Version")
        let task = session.webSocketTask(with: request)
        socket = task
        task.resume()
        return task
    }

    private func receiveLoop(_ task: URLSessionWebSocketTask, checkpoint: Checkpoint,
                             onEvent: EventHandler) async throws {
        while !Task.isCancelled {
            let message = try await task.receive()
            let rawFrame: Data
            switch message {
            case let .data(data): rawFrame = data
            case let .string(text): rawFrame = Data(text.utf8)
            @unknown default: throw MnemosyneTutorTransportError.unsupportedFrame
            }

            let object = try JSONSerialization.jsonObject(with: rawFrame) as? [String: Any]
            guard let object, object["protocol_version"] as? String == MnemosyneContract.nativeProtocolVersion else {
                throw MnemosyneWireError.incompatibleFrame
            }
            if object["type"] as? String == "protocol_error" {
                let message = (object["message"] as? String) ?? "서버가 스트림 요청을 거부했습니다."
                throw MnemosyneTutorTransportError.protocolRejected(message)
            }

            let frame = try decodeMnemosyneTurnFrame(rawFrame)
            if let frameTurnId = frame.turnID {
                if let activeTurnId, activeTurnId != frameTurnId { throw MnemosyneWireError.identityMismatch }
                activeTurnId = frameTurnId
            }
            guard let sequence = frame.sequence else { continue } // control frame, no persisted turn seq
            guard let activeTurnId else { throw MnemosyneTutorTransportError.missingTurnIdentity }
            guard try sequenceCheckpoint.isReplayOrValidateNext(sequence) else { continue }

            try await checkpoint(activeTurnId, sequence, rawFrame)
            try sequenceCheckpoint.commit(sequence)
            if let semanticEvent = frame.semanticEvent { try await onEvent(semanticEvent) }
            if object["type"] as? String == "done" { return }
        }
        throw CancellationError()
    }

    private static func isNativeStartCommand(_ data: Data) -> Bool {
        guard let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return value["type"] as? String == "start_turn" &&
            value["protocol_version"] as? String == MnemosyneContract.nativeProtocolVersion &&
            (value["content"] as? String)?.isEmpty == false
    }

    private static func resumeCommand(turnId: String, sequence: Int) throws -> Data {
        let command: [String: Any] = [
            "type": "resume_from",
            "protocol_version": MnemosyneContract.nativeProtocolVersion,
            "turn_id": turnId,
            "seq": sequence
        ]
        return try JSONSerialization.data(withJSONObject: command, options: [.sortedKeys])
    }

    private static func webSocketURL(from baseURL: URL) -> URL? {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return nil }
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        let prefix = components.path == "/" ? "" : components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        components.path = "/" + [prefix, "ws"].filter { !$0.isEmpty }.joined(separator: "/")
        components.query = nil
        components.fragment = nil
        return components.url
    }

    private static func origin(from url: URL) -> String {
        var components = URLComponents()
        components.scheme = url.scheme
        components.host = url.host
        components.port = url.port
        return components.string ?? ""
    }

    private static func backoff(attempt: Int) async throws {
        let capped = min(60.0, pow(2.0, Double(min(attempt - 1, 6))))
        let jitter = Double.random(in: 0.8...1.2)
        try await Task.sleep(nanoseconds: UInt64(capped * jitter * 1_000_000_000))
    }
}

enum MnemosyneReaderEventError: Error, Equatable {
    case malformed
    case documentMismatch
    case versionMismatch
    case invalidPage
    case unverifiedCitation
    case geometryMismatch
}

enum MnemosyneReaderEventDisposition: Equatable {
    case notReaderEvent
    case apply
    case requiresUserConfirmation
}

/// Guards the app-to-Reader boundary. The server's verified citation must be
/// observed earlier in the same turn, and every target must match the open PDF.
enum MnemosyneReaderEventValidator {
    private struct Target: Decodable {
        let documentId: UUID
        let versionId: String
        let pageIndex: Int
    }

    static func verifiedCitation(from eventData: Data) throws -> MnemosyneVerifiedCitation? {
        let object = try semanticObject(eventData)
        guard object["type"] as? String == "citation.verified" else { return nil }
        guard let payload = object["payload"] as? [String: Any],
              let citation = payload["citation"],
              let data = try? JSONSerialization.data(withJSONObject: citation),
              let decoded = try? JSONDecoder.mnemosyne.decode(MnemosyneVerifiedCitation.self, from: data),
              decoded.verified else { throw MnemosyneReaderEventError.malformed }
        return decoded
    }

    static func validate(_ eventData: Data, documentId: UUID, versionId: String,
                         pageCount: Int, verifiedCitations: [UUID: MnemosyneVerifiedCitation]) throws -> MnemosyneReaderEventDisposition {
        let object = try semanticObject(eventData)
        guard let type = object["type"] as? String,
              let payload = object["payload"] as? [String: Any] else { throw MnemosyneReaderEventError.malformed }
        if type == "citation.verified" {
            guard let citation = try verifiedCitation(from: eventData) else { throw MnemosyneReaderEventError.malformed }
            try validateIdentity(documentId: citation.anchor.documentId, versionId: citation.anchor.versionId,
                                 pageIndex: citation.anchor.pageIndex, expectedDocumentId: documentId,
                                 expectedVersionId: versionId, pageCount: pageCount)
            guard citation.anchor.endScalar > citation.anchor.startScalar,
                  !citation.anchor.quote.isEmpty, !citation.anchor.rects.isEmpty,
                  citation.anchor.rects.allSatisfy(isValidRect) else { throw MnemosyneReaderEventError.geometryMismatch }
            return .notReaderEvent
        }

        guard ["reader.goto", "reader.highlight", "reader.flash", "reader.annotate"].contains(type) else {
            return .notReaderEvent
        }
        guard let targetData = try? JSONSerialization.data(withJSONObject: payload["target"] ?? NSNull()),
              let target = try? JSONDecoder.mnemosyne.decode(Target.self, from: targetData) else {
            throw MnemosyneReaderEventError.malformed
        }
        try validateIdentity(documentId: target.documentId, versionId: target.versionId,
                             pageIndex: target.pageIndex, expectedDocumentId: documentId,
                             expectedVersionId: versionId, pageCount: pageCount)
        guard let citationString = payload["citation_id"] as? String,
              let citationId = UUID(uuidString: citationString),
              let citation = verifiedCitations[citationId], citation.verified,
              citation.anchor.documentId == target.documentId,
              citation.anchor.versionId == target.versionId,
              citation.anchor.pageIndex == target.pageIndex else { throw MnemosyneReaderEventError.unverifiedCitation }

        switch type {
        case "reader.goto":
            guard let position = payload["position"] as? [Double], position.count == 2,
                  position.allSatisfy(\.isFinite),
                  citation.anchor.rects.contains(where: { contains($0, x: position[0], y: position[1]) }) else {
                throw MnemosyneReaderEventError.geometryMismatch
            }
            return .apply
        case "reader.highlight", "reader.flash":
            guard let rects = payload["rects"] as? [[Double]], rects == citation.anchor.rects,
                  payload["persistent"] as? Bool == false else { throw MnemosyneReaderEventError.geometryMismatch }
            return .apply
        case "reader.annotate":
            guard payload["requires_confirmation"] as? Bool == true,
                  let annotation = payload["annotation"] as? [String: Any],
                  (annotation["document_id"] as? String).flatMap(UUID.init(uuidString:)) == target.documentId,
                  annotation["version_id"] as? String == target.versionId,
                  annotation["page_index"] as? Int == target.pageIndex,
                  let annotationPayload = annotation["payload"] as? [String: Any],
                  let anchorValue = annotationPayload["anchor"],
                  let anchorData = try? JSONSerialization.data(withJSONObject: anchorValue),
                  let anchor = try? JSONDecoder.mnemosyne.decode(MnemosyneTextAnchor.self, from: anchorData),
                  anchor == citation.anchor,
                  let mutationId = payload["suggested_mutation_id"] as? String,
                  UUID(uuidString: mutationId) != nil else { throw MnemosyneReaderEventError.malformed }
            return .requiresUserConfirmation
        default:
            return .notReaderEvent
        }
    }

    private static func semanticObject(_ data: Data) throws -> [String: Any] {
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              value["contract_version"] as? String == MnemosyneContract.version,
              value["event_id"] as? String != nil,
              value["type"] as? String != nil else { throw MnemosyneReaderEventError.malformed }
        return value
    }

    private static func validateIdentity(documentId: UUID, versionId: String, pageIndex: Int,
                                          expectedDocumentId: UUID, expectedVersionId: String,
                                          pageCount: Int) throws {
        guard documentId == expectedDocumentId else { throw MnemosyneReaderEventError.documentMismatch }
        guard versionId == expectedVersionId else { throw MnemosyneReaderEventError.versionMismatch }
        guard pageIndex >= 0, pageIndex < pageCount else { throw MnemosyneReaderEventError.invalidPage }
    }

    private static func isValidRect(_ rect: [Double]) -> Bool {
        rect.count == 4 && rect.allSatisfy(\.isFinite) && rect[2] > 0 && rect[3] > 0
    }

    private static func contains(_ rect: [Double], x: Double, y: Double) -> Bool {
        isValidRect(rect) && x >= rect[0] && y >= rect[1] && x <= rect[0] + rect[2] && y <= rect[1] + rect[3]
    }
}

@MainActor
final class MnemosyneAnnotationSyncWorker: ObservableObject, MnemosyneSyncWorker {
    enum State: Equatable {
        case idle, syncing, synced(Date), waiting(String), needsPairing(String), failed(String)
    }

    @Published private(set) var state: State = .idle
    @Published private(set) var conflictedMutationIds: [UUID] = []
    private let api: MnemosyneAPIClient
    private let reader: any MnemosyneReaderFacade
    private let syncState: any MnemosyneSyncStateStore
    private var backgroundTask: Task<Void, Never>?
    private var isSynchronizing = false

    init(api: MnemosyneAPIClient, reader: any MnemosyneReaderFacade,
         syncState: any MnemosyneSyncStateStore) {
        self.api = api
        self.reader = reader
        self.syncState = syncState
    }

    func startForegroundWorker() {
        guard backgroundTask == nil else { return }
        backgroundTask = Task { [weak self] in
            guard let self else { return }
            var attempt = 0
            while !Task.isCancelled {
                do {
                    try await synchronize()
                    attempt = 0
                    try await Task.sleep(nanoseconds: 30_000_000_000)
                } catch is CancellationError {
                    break
                } catch {
                    attempt += 1
                    let delay = retryDelay(error: error, attempt: attempt)
                    if Self.requiresPairing(error) {
                        state = .needsPairing(error.localizedDescription)
                    } else {
                        state = .waiting("동기화를 다시 시도합니다. \(error.localizedDescription)")
                    }
                    do { try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000)) }
                    catch { break }
                }
            }
        }
    }

    func stopForegroundWorker() {
        backgroundTask?.cancel()
        backgroundTask = nil
    }

    func synchronize() async throws {
        guard !isSynchronizing else { return }
        isSynchronizing = true
        state = .syncing
        defer { isSynchronizing = false }
        do {
            conflictedMutationIds = []
            try await pushPendingMutations()
            try await pullServerChanges()
            state = .synced(Date())
        } catch {
            if Self.requiresPairing(error) {
                state = .needsPairing(error.localizedDescription)
            } else {
                state = .failed(error.localizedDescription)
            }
            throw error
        }
    }

    private func pushPendingMutations() async throws {
        let pending = try reader.pendingMutations(limit: 100)
        let groups = try Self.groupMutations(pending)
        for group in groups {
            for batch in group.mutations.chunked(maxCount: 100) {
                let body = try Self.mutationBatch(documentId: group.documentId,
                                                  versionId: group.versionId, mutations: batch)
                let receipt = try await api.applyAnnotationMutations(documentId: group.documentId, batch: body)
                try Self.validateReceipt(receipt, documentId: group.documentId, versionId: group.versionId,
                                         expectedMutationIds: Set(batch.compactMap(Self.mutationId)))
                conflictedMutationIds.append(contentsOf: Self.conflicts(in: receipt))
                // A mutation remains in the local outbox until this facade call commits the receipt.
                try reader.applySyncReceipts(receipt)
            }
        }
    }

    private func pullServerChanges() async throws {
        let documents = try await api.documents()
        for document in documents where document.originalAvailable {
            if case .invalid = try reader.downloadState(documentID: document.documentId, versionID: document.versionId) { continue }
            if let cursor = try syncState.syncCursor(documentID: document.documentId, versionID: document.versionId) {
                try await pullChanges(document: document, startingAt: cursor)
            } else {
                let snapshot = try await api.annotationSnapshot(documentId: document.documentId,
                                                               versionId: document.versionId)
                try Self.validateSnapshot(snapshot, documentId: document.documentId, versionId: document.versionId)
                // Snapshot replacement preserves local pending drafts and commits its cursor atomically.
                try syncState.applyRemoteSnapshot(snapshot)
                if let nextCursor = Self.stringField("next_cursor", in: snapshot) {
                    try await pullChanges(document: document, startingAt: nextCursor)
                }
            }
        }
    }

    private func pullChanges(document: MnemosyneDocument, startingAt firstCursor: String) async throws {
        var cursor = firstCursor
        var cursorExpiredRecoveryUsed = false
        for _ in 0..<1_000 {
            let page: Data
            do {
                page = try await api.annotationChanges(documentId: document.documentId,
                    versionId: document.versionId, cursor: cursor)
            } catch let error as MnemosyneAPIError {
                guard !cursorExpiredRecoveryUsed,
                      case let .server(_, code, _, _, _, _) = error, code == "cursor_expired" else { throw error }
                cursorExpiredRecoveryUsed = true
                let snapshot = try await api.annotationSnapshot(documentId: document.documentId,
                                                                 versionId: document.versionId)
                try Self.validateSnapshot(snapshot, documentId: document.documentId, versionId: document.versionId)
                try syncState.applyRemoteSnapshot(snapshot) // retained local outbox is reconciled by the facade
                guard let refreshedCursor = Self.stringField("next_cursor", in: snapshot),
                      refreshedCursor != cursor else { throw MnemosyneAPIError.invalidResponse }
                cursor = refreshedCursor
                continue
            }
            let metadata = try Self.validateChangePage(page, documentId: document.documentId,
                                                       versionId: document.versionId)
            guard metadata.nextCursor != cursor else { throw MnemosyneAPIError.invalidResponse }
            try reader.applyRemotePage(page) // changes + opaque next cursor commit in the facade transaction
            cursor = metadata.nextCursor
            if !metadata.hasMore { return }
        }
        throw MnemosyneAPIError.invalidResponse
    }

    private func retryDelay(error: Error, attempt: Int) -> Double {
        if let apiError = error as? MnemosyneAPIError,
           let retryAfter = apiError.retryAfterSeconds { return min(300, max(1, Double(retryAfter))) }
        let capped = min(60.0, pow(2.0, Double(min(max(attempt - 1, 0), 6))))
        return capped * Double.random(in: 0.8...1.2)
    }

    private static func requiresPairing(_ error: Error) -> Bool {
        guard let apiError = error as? MnemosyneAPIError else { return false }
        switch apiError {
        case .pairingRequired: return true
        case let .server(status, _, _, _, _, _): return status == 401
        default: return false
        }
    }

    private struct MutationGroup {
        let documentId: UUID
        let versionId: String
        let mutations: [[String: Any]]
    }

    private struct ChangeMetadata {
        let nextCursor: String
        let hasMore: Bool
    }

    private static func groupMutations(_ data: [Data]) throws -> [MutationGroup] {
        var groups: [String: (UUID, String, [[String: Any]])] = [:]
        for encodedMutation in data {
            guard let mutation = try JSONSerialization.jsonObject(with: encodedMutation) as? [String: Any],
                  let idText = mutation["document_id"] as? String, let documentId = UUID(uuidString: idText),
                  let versionId = mutation["version_id"] as? String,
                  versionId.range(of: #"^sha256:[a-f0-9]{64}$"#, options: .regularExpression) != nil,
                  let mutationId = mutation["client_mutation_id"] as? String, UUID(uuidString: mutationId) != nil else {
                throw MnemosyneAPIError.invalidResponse
            }
            let key = "\(documentId.uuidString.lowercased())|\(versionId)"
            var group = groups[key] ?? (documentId, versionId, [])
            group.2.append(mutation)
            groups[key] = group
        }
        return groups.values.map { MutationGroup(documentId: $0.0, versionId: $0.1, mutations: $0.2) }
            .sorted { $0.documentId.uuidString < $1.documentId.uuidString }
    }

    private static func mutationBatch(documentId: UUID, versionId: String,
                                      mutations: [[String: Any]]) throws -> Data {
        try JSONSerialization.data(withJSONObject: [
            "contract_version": MnemosyneContract.version,
            "document_id": documentId.uuidString.lowercased(),
            "version_id": versionId,
            "mutations": mutations
        ], options: [.sortedKeys])
    }

    private static func mutationId(_ mutation: [String: Any]) -> UUID? {
        (mutation["client_mutation_id"] as? String).flatMap(UUID.init(uuidString:))
    }

    private static func validateReceipt(_ data: Data, documentId: UUID, versionId: String,
                                        expectedMutationIds: Set<UUID>) throws {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["contract_version"] as? String == MnemosyneContract.version,
              (object["document_id"] as? String).flatMap(UUID.init(uuidString:)) == documentId,
              object["version_id"] as? String == versionId,
              let results = object["results"] as? [[String: Any]],
              Set(results.compactMap(mutationId)) == expectedMutationIds,
              results.allSatisfy({ ["applied", "conflict", "rejected"].contains($0["status"] as? String ?? "") }) else {
            throw MnemosyneAPIError.invalidResponse
        }
    }

    private static func conflicts(in data: Data) -> [UUID] {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let results = object["results"] as? [[String: Any]] else { return [] }
        return results.compactMap { result in
            guard result["status"] as? String == "conflict" else { return nil }
            return mutationId(result)
        }
    }

    private static func validateSnapshot(_ data: Data, documentId: UUID, versionId: String) throws {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["contract_version"] as? String == MnemosyneContract.version,
              (object["document_id"] as? String).flatMap(UUID.init(uuidString:)) == documentId,
              object["version_id"] as? String == versionId,
              object["snapshot_revision"] is Int,
              object["annotations"] is [[String: Any]],
              object["next_cursor"] as? String != nil else { throw MnemosyneAPIError.invalidResponse }
    }

    private static func validateChangePage(_ data: Data, documentId: UUID,
                                           versionId: String) throws -> ChangeMetadata {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              object["contract_version"] as? String == MnemosyneContract.version,
              (object["document_id"] as? String).flatMap(UUID.init(uuidString:)) == documentId,
              object["version_id"] as? String == versionId,
              object["changes"] is [[String: Any]],
              let nextCursor = object["next_cursor"] as? String, !nextCursor.isEmpty,
              let hasMore = object["has_more"] as? Bool else { throw MnemosyneAPIError.invalidResponse }
        return ChangeMetadata(nextCursor: nextCursor, hasMore: hasMore)
    }

    private static func stringField(_ field: String, in data: Data) -> String? {
        (try? JSONSerialization.jsonObject(with: data) as? [String: Any])?[field] as? String
    }
}

private extension Array {
    func chunked(maxCount: Int) -> [[Element]] {
        guard maxCount > 0 else { return [self] }
        return stride(from: 0, to: count, by: maxCount).map { start in
            Array(self[start..<Swift.min(start + maxCount, count)])
        }
    }
}
