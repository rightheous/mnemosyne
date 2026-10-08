import Foundation

/// UNIT-04's native /ws boundary. Checkpoint every persisted frame, including
/// frames with no Reader extension. JSON schema validation remains mandatory.
struct MnemosyneTurnFrame {
    let turnID: String?
    let sequence: Int?
    let semanticEvent: Data?
}

enum MnemosyneWireError: Error { case incompatibleFrame, identityMismatch, terminalMismatch }

func decodeMnemosyneTurnFrame(_ data: Data) throws -> MnemosyneTurnFrame {
    guard let frame = try JSONSerialization.jsonObject(with: data) as? [String: Any],
          frame["protocol_version"] as? String == "2.0"
    else { throw MnemosyneWireError.incompatibleFrame }
    let turnID = frame["turn_id"] as? String
    let sequence = frame["seq"] as? Int
    let metadata = frame["metadata"] as? [String: Any] ?? [:]
    guard let event = metadata["mnemosyne"] as? [String: Any] else {
        return MnemosyneTurnFrame(turnID: turnID, sequence: sequence, semanticEvent: nil)
    }
    guard let turnID, let sequence, sequence > 0,
          event["contract_version"] as? String == "0.1.0",
          event["turn_id"] as? String == turnID, event["seq"] as? Int == sequence,
          event["event_id"] as? String == "\(turnID):\(sequence)"
    else { throw MnemosyneWireError.identityMismatch }
    let terminal = ["completed": "turn.done", "failed": "turn.error", "cancelled": "turn.cancelled"]
    let kind = event["type"] as? String ?? ""
    if frame["type"] as? String == "done" {
        guard kind == terminal[metadata["status"] as? String ?? ""] else {
            throw MnemosyneWireError.terminalMismatch
        }
    } else if terminal.values.contains(kind) {
        throw MnemosyneWireError.terminalMismatch
    }
    return MnemosyneTurnFrame(turnID: turnID, sequence: sequence,
                             semanticEvent: try JSONSerialization.data(withJSONObject: event))
}
