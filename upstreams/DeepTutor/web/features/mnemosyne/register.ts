import type { StreamEvent } from '../../contracts/generated/turn-protocol'

export interface SemanticEvent {
  contract_version: '0.1.0'
  event_id: string
  turn_id: string
  seq: number
  type: string
  payload: Record<string, unknown>
}

/** UNIT-05 uses the native /ws client, preserving every native sequence. */
export function consumeNativeFrame(frame: StreamEvent): SemanticEvent | null {
  const value = frame.metadata?.mnemosyne as SemanticEvent | undefined
  if (!value) return null
  if (
    frame.protocol_version !== '2.0' ||
    value.contract_version !== '0.1.0' ||
    value.turn_id !== frame.turn_id ||
    value.seq !== frame.seq ||
    value.event_id !== `${frame.turn_id}:${frame.seq}`
  )
    throw new Error('Wire/semantic event mismatch')
  const terminal: Record<string, string> = {
    completed: 'turn.done',
    failed: 'turn.error',
    cancelled: 'turn.cancelled',
  }
  if (frame.type === 'done') {
    if (value.type !== terminal[String(frame.metadata?.status)]) {
      throw new Error('Terminal status mismatch')
    }
  } else if (Object.values(terminal).includes(value.type)) {
    throw new Error('Premature terminal event')
  }
  return value
}

export interface MnemosyneWebDependencies {
  serverURL: URL
  dispatchReaderEvent: (event: SemanticEvent) => void
  persistCheckpoint: (turnID: string, seq: number) => Promise<void>
}

/** Composition seam only. UNIT-05 mounts Korean screens in existing app/. */
export function mountMnemosyneWeb(dependencies: MnemosyneWebDependencies) {
  return { dependencies, consumeNativeFrame, contractVersion: '0.1.0' as const }
}
