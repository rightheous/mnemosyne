"use client";

import type { StreamEvent } from "../../contracts/generated/turn-protocol";
import { apiFetch } from "@/shared/api/client";

export const MNEMOSYNE_CONTRACT_VERSION = "0.2.0" as const;
export const MNEMOSYNE_PROTOCOL_VERSION = "2.0" as const;

export type PdfRect = [number, number, number, number];

export interface PageGeometry {
  media_box: [number, number, number, number];
  crop_box: [number, number, number, number];
  rotation_degrees: 0 | 90 | 180 | 270;
  user_unit: number;
}

/** Map canonical PDF user-space coordinates to the rotated page's top-left unit square. */
export function pdfPointToPageUnit(
  point: [number, number],
  geometry: PageGeometry,
): [number, number] {
  const [x0, y0, x1, y1] = geometry.crop_box;
  const width = x1 - x0;
  const height = y1 - y0;
  const u = point[0] - x0;
  const v = point[1] - y0;
  let x = 0;
  let y = 0;
  let viewWidth = width;
  let viewHeight = height;
  switch (geometry.rotation_degrees) {
    case 0: x = u; y = height - v; break;
    case 90: x = v; y = u; viewWidth = height; viewHeight = width; break;
    case 180: x = width - u; y = v; break;
    case 270: x = height - v; y = width - u; viewWidth = height; viewHeight = width; break;
  }
  return [x / viewWidth, y / viewHeight];
}

/** Transform a PDF-space rectangle by all four corners so rotation keeps its bounds correct. */
export function pdfRectToPageUnit(
  rect: PdfRect,
  geometry: PageGeometry,
): [number, number, number, number] {
  const [x, y, width, height] = rect;
  const corners: Array<[number, number]> = [
    [x, y],
    [x + width, y],
    [x, y + height],
    [x + width, y + height],
  ];
  const unit = corners.map((point) => pdfPointToPageUnit(point, geometry));
  const xs = unit.map(([pointX]) => pointX);
  const ys = unit.map(([, pointY]) => pointY);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

/** Normalize an ink width against the displayed page width, including /Rotate and /UserUnit. */
export function pdfStrokeWidthToPageUnit(widthPt: number, geometry: PageGeometry): number {
  const [llx, lly, urx, ury] = geometry.crop_box;
  const pageWidth = geometry.rotation_degrees === 90 || geometry.rotation_degrees === 270
    ? ury - lly
    : urx - llx;
  return widthPt / (pageWidth * geometry.user_unit);
}

export interface MnemosyneSubject {
  subject_id: string;
  name: string;
  server_revision: number;
}

export interface MnemosyneDocument {
  document_id: string;
  version_id: string;
  source_sha256: string;
  title: string;
  subject_id: string | null;
  content_language: string;
  page_count: number;
  server_revision: number;
  original_available: boolean;
  parse_state: "pending" | "running" | "ready" | "failed";
  index_state: "pending" | "running" | "ready" | "failed";
  created_at: string;
}

export interface MnemosyneTextAnchor {
  document_id: string;
  version_id: string;
  page_index: number;
  parse_revision: string;
  text_sha256: string;
  start_scalar: number;
  end_scalar: number;
  quote: string;
  rects: PdfRect[];
}

export interface MnemosynePage {
  document_id: string;
  version_id: string;
  page_index: number;
  display_page_number: number;
  display_label: string;
  parse_revision: string;
  text_basis: "parser:nfc-lf-v1";
  text: string;
  text_sha256: string;
  geometry: PageGeometry;
  segments: Array<{ start_scalar: number; end_scalar: number; rect: PdfRect }>;
}

export interface VerifiedCitation {
  citation_id: string;
  verification_id: string;
  verified: true;
  anchor: MnemosyneTextAnchor;
}

export interface Readiness {
  contract_version: typeof MNEMOSYNE_CONTRACT_VERSION;
  status: "ready" | "degraded" | "starting";
  components: Record<"database" | "storage" | "parser" | "index" | "provider", "ready" | "pending" | "failed" | "disabled">;
  capabilities: Array<"chat" | "reading" | "quiz" | "assessment" | "mastery" | "solve" | "memory" | "progress" | "review">;
  event_resume_seconds: number;
}

export interface MnemosyneAnnotation {
  annotation_id: string;
  document_id: string;
  version_id: string;
  page_index: number;
  kind: "highlight" | "note" | "bookmark" | "ink";
  server_revision: number;
  updated_at: string;
  deleted: boolean;
  deleted_at: string | null;
  payload: Record<string, unknown> | null;
}

export interface MnemosyneSnapshot {
  contract_version: typeof MNEMOSYNE_CONTRACT_VERSION;
  document_id: string;
  version_id: string;
  snapshot_revision: number;
  annotations: MnemosyneAnnotation[];
  next_cursor: string;
}

export interface MnemosyneLearningState {
  document_id: string;
  version_id: string;
  learning_revision: number;
  quiz_attempts: Array<{ attempt_id: string; quiz_id: string; score: number }>;
  mastery: Array<{ concept_id: string; label_ko: string; score: number; evidence_attempt_ids: string[] }>;
  memory: Array<{ memory_id: string; front_ko: string; back_ko: string; due_at: string; review_count: number; citations: VerifiedCitation[] }>;
  progress: { last_page_index: number; pages_read: number[]; reading_seconds: number; next_review_at: string };
  activities: Array<{ activity_id: string; kind: string; turn_id: string | null; summary_ko: string; created_at: string }>;
}

export interface MnemosyneProgressMutation {
  client_mutation_id: string;
  version_id: string;
  base_learning_revision: number;
  page_index: number;
  reading_seconds: number;
}

export interface MnemosyneQuiz {
  quiz_id: string;
  document_id: string;
  version_id: string;
  title: string;
  response_language: string;
  questions: Array<{
    question_id: string;
    prompt: string;
    kind: "single_choice" | "free_text";
    choices: Array<{ choice_id: string; text: string }>;
    citations: VerifiedCitation[];
  }>;
}

export interface MnemosyneAssessment {
  attempt_id: string;
  score: number;
  feedback_ko: string;
  learning_revision: number;
  citations: VerifiedCitation[];
}

export interface PublicSettings {
  server_revision: number;
  provider: {
    adapter: "openai-compatible";
    base_url: string;
    model: string;
    credential_configured: boolean;
  };
  response_language: string;
}

export interface MnemosyneQuizGenerationRequest {
  client_mutation_id: string;
  version_id: string;
  page_index: number;
  prompt: string;
  response_language: string;
}

export interface ExportReceipt {
  export_id: string;
  download_path: string;
  original_sha256: string;
  export_sha256: string;
}

export interface MnemosyneTurnRequest {
  client_mutation_id: string;
  capability: "chat" | "reading" | "quiz" | "assessment" | "mastery" | "solve" | "memory" | "progress" | "review";
  message: string;
  reader_context: {
    document_id: string;
    version_id: string;
    page_index: number;
    viewport_rect: PdfRect;
    selection: MnemosyneTextAnchor | null;
    content_language: string;
    response_language: string;
  };
  response_language: string;
}

export type NativeTutorCapability =
  | "chat"
  | "immersive_reading"
  | "deep_question"
  | "mastery_path"
  | "deep_solve";

const NATIVE_TUTOR_CAPABILITIES: Partial<
  Record<MnemosyneTurnRequest["capability"], NativeTutorCapability>
> = {
  chat: "chat",
  reading: "immersive_reading",
  quiz: "deep_question",
  assessment: "deep_question",
  mastery: "mastery_path",
  solve: "deep_solve",
};

/** Map product actions onto capabilities accepted by the existing /ws protocol. */
export function nativeTutorCapability(
  capability: MnemosyneTurnRequest["capability"],
): NativeTutorCapability | null {
  return NATIVE_TUTOR_CAPABILITIES[capability] ?? null;
}

export interface SemanticEvent {
  contract_version: typeof MNEMOSYNE_CONTRACT_VERSION;
  event_id: string;
  turn_id: string;
  seq: number;
  type: string;
  payload: Record<string, unknown>;
}

export class MnemosyneApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(input: { status: number; code?: string; message: string; requestId?: string | null; retryable?: boolean }) {
    super(input.message);
    this.name = "MnemosyneApiError";
    this.status = input.status;
    this.code = input.code ?? "http_error";
    this.requestId = input.requestId ?? null;
    this.retryable = input.retryable ?? input.status >= 500;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sameDocumentVersion(value: { document_id?: unknown; version_id?: unknown }, document: MnemosyneDocument): boolean {
  return value.document_id === document.document_id && value.version_id === document.version_id;
}

function revisionHeader(revision: number): string {
  return `\"${revision}\"`;
}

function defaultServerURL(): URL {
  const configured = process.env.NEXT_PUBLIC_MNEMOSYNE_SERVER_URL;
  if (typeof window !== "undefined") return new URL(configured || "/", window.location.origin);
  return new URL(configured || "http://localhost/");
}

/** Contract-backed same-origin HTTP client. It never stores or returns API keys or bearer tokens. */
export class MnemosyneApi {
  readonly baseURL: URL;

  constructor(baseURL: URL = defaultServerURL()) {
    this.baseURL = new URL(baseURL.toString());
    if (typeof window !== "undefined" && this.baseURL.origin !== window.location.origin) {
      throw new Error("Mnemosyne 웹 연결은 same-origin 보호 세션을 사용해야 합니다.");
    }
  }

  private async json<T>(path: string, init: RequestInit = {}): Promise<T> {
    const url = new URL(path, this.baseURL);
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    headers.set("X-Mnemosyne-Contract-Version", MNEMOSYNE_CONTRACT_VERSION);
    const response = await apiFetch(url, {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
      skipAuthRedirect: true,
    });
    const serverVersion = response.headers.get("x-mnemosyne-contract-version");
    if (serverVersion && serverVersion !== MNEMOSYNE_CONTRACT_VERSION) {
      throw new MnemosyneApiError({ status: 409, code: "contract_mismatch", message: `서버 계약 버전 ${serverVersion}은 웹 계약 ${MNEMOSYNE_CONTRACT_VERSION}과 다릅니다.` });
    }
    if (!response.ok) {
      let envelope: Record<string, unknown> = {};
      try {
        const body: unknown = await response.json();
        if (isRecord(body)) envelope = body;
      } catch {
        // The status line below is enough for a non-JSON proxy response.
      }
      const code = typeof envelope.code === "string" ? envelope.code : `http_${response.status}`;
      const message = typeof envelope.message_ko === "string" && envelope.message_ko
        ? envelope.message_ko
        : response.status === 401
          ? "서버 페어링이 필요하거나 세션이 만료되었습니다."
          : response.status === 404
            ? "서버가 이 Mnemosyne API를 제공하지 않습니다. 서버 통합 상태를 확인해 주세요."
            : `요청을 완료하지 못했습니다. (HTTP ${response.status})`;
      throw new MnemosyneApiError({
        status: response.status,
        code,
        message,
        requestId: typeof envelope.request_id === "string" ? envelope.request_id : null,
        retryable: typeof envelope.retryable === "boolean" ? envelope.retryable : undefined,
      });
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  private async blob(path: string): Promise<Blob> {
    const url = new URL(path, this.baseURL);
    const response = await apiFetch(url, {
      credentials: "include",
      cache: "no-store",
      skipAuthRedirect: true,
      headers: {
        Accept: "application/pdf",
        "X-Mnemosyne-Contract-Version": MNEMOSYNE_CONTRACT_VERSION,
      },
    });
    const serverVersion = response.headers.get("x-mnemosyne-contract-version");
    if (serverVersion && serverVersion !== MNEMOSYNE_CONTRACT_VERSION) {
      throw new MnemosyneApiError({ status: 409, code: "contract_mismatch", message: `서버 계약 버전 ${serverVersion}은 웹 계약 ${MNEMOSYNE_CONTRACT_VERSION}과 다릅니다.` });
    }
    if (!response.ok) throw new MnemosyneApiError({ status: response.status, message: response.status === 404 ? "파일을 찾을 수 없습니다." : `파일을 내려받지 못했습니다. (HTTP ${response.status})` });
    return response.blob();
  }

  async pair(oneTimeCode: string, deviceName: string): Promise<{ device_id: string; expires_at: string }> {
    const receipt = await this.json<{ device_id: string; access_token: string; token_type: "Bearer"; expires_at: string }>("/v1/session/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ one_time_code: oneTimeCode, device_name: deviceName }),
    });
    if (!receipt.device_id || !receipt.expires_at) throw new Error("서버 페어링 응답이 계약과 다릅니다.");
    // access_token is intentionally discarded. Web authentication must be an HttpOnly same-origin cookie.
    return { device_id: receipt.device_id, expires_at: receipt.expires_at };
  }

  async revokeSession(): Promise<{ revoked: boolean }> {
    return this.json("/v1/session", { method: "DELETE" });
  }

  async readiness(): Promise<Readiness> {
    return this.json("/v1/readiness");
  }

  async listSubjects(): Promise<MnemosyneSubject[]> {
    return this.json("/v1/subjects");
  }

  async createSubject(name: string): Promise<MnemosyneSubject> {
    return this.json("/v1/subjects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
  }

  async renameSubject(subject: MnemosyneSubject, name: string): Promise<MnemosyneSubject> {
    return this.json(`/v1/subjects/${encodeURIComponent(subject.subject_id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "If-Match": revisionHeader(subject.server_revision) },
      body: JSON.stringify({ name }),
    });
  }

  async deleteSubject(subject: MnemosyneSubject): Promise<void> {
    await this.json(`/v1/subjects/${encodeURIComponent(subject.subject_id)}`, { method: "DELETE", headers: { "If-Match": revisionHeader(subject.server_revision) } });
  }

  async listDocuments(subjectID?: string): Promise<MnemosyneDocument[]> {
    const query = subjectID ? `?subject_id=${encodeURIComponent(subjectID)}` : "";
    return this.json(`/v1/documents${query}`);
  }

  async getDocument(documentID: string): Promise<MnemosyneDocument> {
    return this.json(`/v1/documents/${encodeURIComponent(documentID)}`);
  }

  async uploadDocument(file: File, title: string, subjectID?: string): Promise<MnemosyneDocument> {
    if (!file.name.toLowerCase().endsWith(".pdf") || (file.type && file.type !== "application/pdf")) {
      throw new Error("PDF 파일만 올릴 수 있습니다.");
    }
    if (await file.slice(0, 5).text() !== "%PDF-") throw new Error("파일의 PDF 서명을 확인할 수 없습니다.");
    const form = new FormData();
    form.set("file", file, file.name);
    form.set("title", title.trim() || file.name.replace(/\.pdf$/i, ""));
    if (subjectID) form.set("subject_id", subjectID);
    return this.json("/v1/documents", { method: "POST", body: form });
  }

  async updateDocument(document: MnemosyneDocument, update: { title?: string; subject_id?: string | null }): Promise<MnemosyneDocument> {
    return this.json(`/v1/documents/${encodeURIComponent(document.document_id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "If-Match": revisionHeader(document.server_revision) },
      body: JSON.stringify(update),
    });
  }

  async deleteDocument(document: MnemosyneDocument): Promise<void> {
    await this.json(`/v1/documents/${encodeURIComponent(document.document_id)}`, {
      method: "DELETE",
      headers: {
        "If-Match": revisionHeader(document.server_revision),
        "X-Confirm-Action": `document.delete:${document.document_id}`,
      },
    });
  }

  originalFileURL(document: MnemosyneDocument): string {
    const url = new URL(`/v1/documents/${encodeURIComponent(document.document_id)}/file`, this.baseURL);
    url.searchParams.set("version_id", document.version_id);
    return url.toString();
  }

  async getPage(document: MnemosyneDocument, pageIndex: number, parseRevision: string): Promise<MnemosynePage> {
    const query = new URLSearchParams({ version_id: document.version_id, parse_revision: parseRevision });
    const page = await this.json<MnemosynePage>(`/v1/documents/${encodeURIComponent(document.document_id)}/pages/${pageIndex}?${query}`);
    if (!sameDocumentVersion(page, document) || page.page_index !== pageIndex) throw new Error("페이지 응답의 문서/version이 현재 Reader와 다릅니다.");
    return page;
  }

  async searchDocument(document: MnemosyneDocument, query: string, limit = 30): Promise<MnemosyneTextAnchor[]> {
    return this.json(`/v1/documents/${encodeURIComponent(document.document_id)}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, version_id: document.version_id, limit }),
    });
  }

  async verifyCitation(anchor: MnemosyneTextAnchor, document: MnemosyneDocument): Promise<VerifiedCitation> {
    if (!sameDocumentVersion(anchor, document)) throw new Error("다른 문서의 인용은 Reader에 적용하지 않습니다.");
    const citation = await this.json<VerifiedCitation>("/v1/citations/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(anchor),
    });
    if (citation.verified !== true || !sameDocumentVersion(citation.anchor, document)) throw new Error("서버에서 인용을 검증하지 못했습니다.");
    return citation;
  }

  async annotationSnapshot(document: MnemosyneDocument): Promise<MnemosyneSnapshot> {
    const query = new URLSearchParams({ version_id: document.version_id });
    const snapshot = await this.json<MnemosyneSnapshot>(`/v1/documents/${encodeURIComponent(document.document_id)}/annotations/snapshot?${query}`);
    if (!sameDocumentVersion(snapshot, document)) throw new Error("주석 응답의 문서/version이 현재 Reader와 다릅니다.");
    return snapshot;
  }

  async mutateAnnotations(document: MnemosyneDocument, mutations: Array<Record<string, unknown>>): Promise<{ contract_version: string; document_id: string; version_id: string; results: Array<Record<string, unknown>> }> {
    return this.json(`/v1/documents/${encodeURIComponent(document.document_id)}/annotations/mutations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contract_version: MNEMOSYNE_CONTRACT_VERSION, document_id: document.document_id, version_id: document.version_id, mutations }),
    });
  }

  async getTurn(turnID: string): Promise<{ turn_id: string; state: string; event_path: "/ws"; response_language: string }> {
    return this.json(`/v1/tutor/turns/${encodeURIComponent(turnID)}`);
  }

  async getQuiz(quizID: string): Promise<MnemosyneQuiz> {
    return this.json(`/v1/quizzes/${encodeURIComponent(quizID)}`);
  }

  async createQuiz(document: MnemosyneDocument, pageIndex: number, prompt: string, clientMutationID: string): Promise<MnemosyneQuiz> {
    const normalizedPrompt = prompt.trim();
    const quiz = await this.json<MnemosyneQuiz>(`/v1/documents/${encodeURIComponent(document.document_id)}/quizzes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_mutation_id: clientMutationID,
        version_id: document.version_id,
        page_index: pageIndex,
        prompt: normalizedPrompt,
        response_language: "ko",
      } satisfies MnemosyneQuizGenerationRequest),
    });
    if (!sameDocumentVersion(quiz, document)) throw new Error("다른 문서의 퀴즈 생성을 거부했습니다.");
    return quiz;
  }

  async submitAttempt(quizID: string, attempt: Record<string, unknown>): Promise<MnemosyneAssessment> {
    return this.json(`/v1/quizzes/${encodeURIComponent(quizID)}/attempts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(attempt) });
  }

  async learningState(document: MnemosyneDocument): Promise<MnemosyneLearningState> {
    const query = new URLSearchParams({ version_id: document.version_id });
    const state = await this.json<MnemosyneLearningState>(`/v1/documents/${encodeURIComponent(document.document_id)}/learning?${query}`);
    if (!sameDocumentVersion(state, document)) throw new Error("학습 기록의 문서/version이 현재 Reader와 다릅니다.");
    return state;
  }

  async recordProgress(
    document: MnemosyneDocument,
    mutation: MnemosyneProgressMutation,
  ): Promise<MnemosyneLearningState> {
    if (mutation.version_id !== document.version_id) throw new Error("다른 문서 version의 진도를 저장하지 않습니다.");
    const path = `/v1/documents/${encodeURIComponent(document.document_id)}/progress`;
    const submit = (value: MnemosyneProgressMutation) => this.json<MnemosyneLearningState>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value),
    });
    try {
      const state = await submit(mutation);
      if (!sameDocumentVersion(state, document)) throw new Error("진도 응답의 문서/version이 현재 Reader와 다릅니다.");
      return state;
    } catch (error) {
      if (!(error instanceof MnemosyneApiError) || error.code !== "conflict") throw error;
      const latest = await this.learningState(document);
      const retry = await submit({ ...mutation, base_learning_revision: latest.learning_revision });
      if (!sameDocumentVersion(retry, document)) throw new Error("진도 재시도 응답의 문서/version이 현재 Reader와 다릅니다.");
      return retry;
    }
  }

  async reviewMemory(memoryID: string, review: Record<string, unknown>): Promise<MnemosyneLearningState> {
    return this.json(`/v1/memory/${encodeURIComponent(memoryID)}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(review) });
  }

  async publicSettings(): Promise<PublicSettings> {
    const value: unknown = await this.json("/v1/settings");
    if (!isRecord(value) || !isRecord(value.provider)) throw new Error("설정 응답이 계약과 다릅니다.");
    const provider = value.provider;
    if (provider.adapter !== "openai-compatible" || typeof provider.base_url !== "string" || typeof provider.model !== "string" || typeof provider.credential_configured !== "boolean") {
      throw new Error("설정 응답이 계약과 다릅니다.");
    }
    if (typeof value.server_revision !== "number" || typeof value.response_language !== "string") throw new Error("설정 응답이 계약과 다릅니다.");
    // Whitelist masked metadata; never retain an unexpected api_key field from a broken server.
    return {
      server_revision: value.server_revision,
      provider: { adapter: "openai-compatible", base_url: provider.base_url, model: provider.model, credential_configured: provider.credential_configured },
      response_language: value.response_language,
    };
  }

  async updateSettings(settings: { provider: { adapter: "openai-compatible"; base_url: string; model: string; api_key?: string }; response_language: string }, revision: number): Promise<PublicSettings> {
    const value: unknown = await this.json("/v1/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "If-Match": revisionHeader(revision), "X-Confirm-Action": "settings.update" },
      body: JSON.stringify(settings),
    });
    if (!isRecord(value) || !isRecord(value.provider)) throw new Error("설정 저장 응답이 계약과 다릅니다.");
    const provider = value.provider;
    if (provider.adapter !== "openai-compatible" || typeof provider.base_url !== "string" || typeof provider.model !== "string" || typeof provider.credential_configured !== "boolean" || typeof value.server_revision !== "number" || typeof value.response_language !== "string") {
      throw new Error("설정 저장 응답이 계약과 다릅니다.");
    }
    return {
      server_revision: value.server_revision,
      provider: { adapter: "openai-compatible", base_url: provider.base_url, model: provider.model, credential_configured: provider.credential_configured },
      response_language: value.response_language,
    };
  }

  async createExport(document: MnemosyneDocument, annotationRevision: number, includeInk: boolean): Promise<ExportReceipt> {
    return this.json(`/v1/documents/${encodeURIComponent(document.document_id)}/exports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version_id: document.version_id, annotation_revision: annotationRevision, include_ink: includeInk }),
    });
  }

  async downloadExport(receipt: ExportReceipt): Promise<Blob> {
    const path = new URL(receipt.download_path, this.baseURL);
    if (path.origin !== this.baseURL.origin || !/^\/v1\/exports\/[a-f0-9-]+\/file$/.test(path.pathname)) throw new Error("내보내기 경로가 계약과 다릅니다.");
    return this.blob(`${path.pathname}${path.search}`);
  }

  async downloadOriginal(document: MnemosyneDocument): Promise<Blob> {
    const url = new URL(this.originalFileURL(document));
    return this.blob(`${url.pathname}${url.search}`);
  }
}

/** UNIT-05 uses the native /ws client, preserving every native sequence. */
export function consumeNativeFrame(frame: StreamEvent): SemanticEvent | null {
  const value = frame.metadata?.mnemosyne as SemanticEvent | undefined;
  if (!value) return null;
  if (
    frame.protocol_version !== MNEMOSYNE_PROTOCOL_VERSION ||
    !Number.isInteger(frame.seq) ||
    typeof frame.turn_id !== "string" ||
    value.contract_version !== MNEMOSYNE_CONTRACT_VERSION ||
    value.turn_id !== frame.turn_id ||
    value.seq !== frame.seq ||
    value.event_id !== `${frame.turn_id}:${frame.seq}`
  ) throw new Error("Wire/semantic event mismatch");
  const terminal: Record<string, string> = { completed: "turn.done", failed: "turn.error", cancelled: "turn.cancelled" };
  if (frame.type === "done") {
    if (value.type !== terminal[String(frame.metadata?.status)]) throw new Error("Terminal status mismatch");
  } else if (Object.values(terminal).includes(value.type)) {
    throw new Error("Premature terminal event");
  }
  return value;
}

export interface MnemosyneWebDependencies {
  serverURL: URL;
  dispatchReaderEvent: (event: SemanticEvent) => void;
  persistCheckpoint: (turnID: string, seq: number) => Promise<void>;
}

/** Composition seam used by the Korean screens; all network calls stay behind their real contracts. */
export function mountMnemosyneWeb(dependencies: MnemosyneWebDependencies) {
  return { dependencies, consumeNativeFrame, contractVersion: MNEMOSYNE_CONTRACT_VERSION };
}
