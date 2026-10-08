"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import Link from "next/link";
import { ArrowLeft, BookOpen, Check, ChevronDown, CircleAlert, Download, FileText, FolderPlus, LoaderCircle, MessageCircle, Pencil, Plus, RefreshCw, Search, Settings2, Trash2, Upload } from "lucide-react";
import { PdfDocumentView, type JumpRequest, type SelectionPayload } from "@/components/reading/PdfDocumentView";
import type { AnnotationItem } from "@/lib/reading-api";
import type { InkOverlayStroke } from "@/components/reading/AnnotationLayer";
import { SettingsProvider, useSettings } from "@/features/settings/store/SettingsStore";
import { flattenModels, modelProvider, type RegistryEdit } from "@/lib/provider-registry";
import { browserStorage } from "@/shared/storage/store";
import type { StreamEvent } from "../../contracts/generated/turn-protocol";
import {
  MNEMOSYNE_CONTRACT_VERSION,
  MNEMOSYNE_PROTOCOL_VERSION,
  MnemosyneApi,
  MnemosyneApiError,
  consumeNativeFrame,
  mountMnemosyneWeb,
  type ExportReceipt,
  type MnemosyneAnnotation,
  type MnemosyneAssessment,
  type MnemosyneDocument,
  type MnemosyneLearningState,
  type MnemosyneQuiz,
  type MnemosyneSnapshot,
  type MnemosyneSubject,
  type MnemosyneTurnRequest,
  type MnemosyneTextAnchor,
  type PageGeometry,
  type PdfRect,
  type PublicSettings,
  type Readiness,
  type SemanticEvent,
  type VerifiedCitation,
} from "./register";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sameDocumentVersion(value: { document_id?: unknown; version_id?: unknown }, document: MnemosyneDocument): boolean {
  return value.document_id === document.document_id && value.version_id === document.version_id;
}

function useMnemosyneApi(): MnemosyneApi {
  return useMemo(() => new MnemosyneApi(), []);
}

function newUUID(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "요청을 완료하지 못했습니다.";
}

function saveBlob(blob: Blob, filename: string): void {
  const objectURL = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectURL;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(objectURL), 1000);
}

function MnemosyneNav({ active }: { active: "library" | "learning" | "settings" }) {
  const items = [
    { id: "library", href: "/learning/reading", label: "라이브러리", icon: BookOpen },
    { id: "learning", href: "/learning", label: "학습 기록·복습", icon: Check },
    { id: "settings", href: "/settings", label: "설정", icon: Settings2 },
  ] as const;
  return (
    <header className="sticky top-0 z-30 border-b border-[#E4E7EC] bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between px-5 lg:px-8">
        <Link href="/learning/reading" className="flex items-center gap-3 text-[#1F2937] no-underline">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#315DA8] text-white"><BookOpen size={19} /></span>
          <span><span className="block text-[15px] font-semibold tracking-tight">므네모시네</span><span className="block text-[11px] text-[#667085]">개인 학습 공간</span></span>
        </Link>
        <nav aria-label="주요 메뉴" className="flex items-center gap-1">
          {items.map(({ id, href, label, icon: Icon }) => (
            <Link key={id} href={href} aria-current={active === id ? "page" : undefined} className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] no-underline transition ${active === id ? "bg-[#EDF3FC] font-semibold text-[#315DA8]" : "text-[#667085] hover:bg-[#F2F4F7] hover:text-[#1F2937]"}`}>
              <Icon size={16} aria-hidden="true" /><span className="hidden sm:inline">{label}</span>
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}

function PairingPanel({ api, onPaired }: { api: MnemosyneApi; onPaired: () => Promise<void> }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.pair(code.trim(), `${navigator.platform || "Mac"} 브라우저`);
      setCode("");
      await onPaired();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit} className="mt-4 rounded-xl border border-[#D0D5DD] bg-white p-4">
      <div className="text-sm font-semibold text-[#1F2937]">개인 서버 연결</div>
      <p className="mt-1 text-xs leading-5 text-[#667085]">서버에서 발급한 일회용 페어링 코드를 입력하세요. 코드와 토큰은 브라우저 저장소에 보관하지 않습니다.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <label className="sr-only" htmlFor="mnemosyne-pair-code">일회용 페어링 코드</label>
        <input id="mnemosyne-pair-code" autoComplete="one-time-code" value={code} onChange={(event) => setCode(event.target.value)} className="min-w-0 flex-1 rounded-lg border border-[#D0D5DD] px-3 py-2 text-sm outline-none focus:border-[#315DA8] focus:ring-2 focus:ring-[#315DA8]/15" placeholder="일회용 코드" required minLength={8} maxLength={128} />
        <button disabled={busy} className="rounded-lg bg-[#315DA8] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{busy ? "연결 중…" : "연결"}</button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-[#B42318]">{error}</p>}
    </form>
  );
}

function ErrorPanel({ error, onRetry, api }: { error: unknown; onRetry: () => void; api: MnemosyneApi }) {
  const [pairingOpen, setPairingOpen] = useState(error instanceof MnemosyneApiError && error.status === 401);
  const [retryingPair, setRetryingPair] = useState(false);
  const retryAfterPair = async () => {
    setRetryingPair(true);
    try {
      await onRetry();
      setPairingOpen(false);
    } finally {
      setRetryingPair(false);
    }
  };
  return (
    <section className="rounded-2xl border border-[#FDA29B] bg-[#FEF3F2] p-5 text-[#7A271A]" role="alert">
      <div className="flex items-start gap-3"><CircleAlert size={19} className="mt-0.5 shrink-0" /><div className="min-w-0 flex-1"><h2 className="text-sm font-semibold">서버 응답을 확인하지 못했습니다</h2><p className="mt-1 break-words text-sm leading-6">{errorMessage(error)}</p>
        {error instanceof MnemosyneApiError && error.requestId && <p className="mt-1 text-xs">요청 ID: {error.requestId}</p>}
        <div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={onRetry} className="rounded-lg border border-[#F97066] px-3 py-2 text-sm font-medium">다시 불러오기</button>{error instanceof MnemosyneApiError && error.status === 401 && <button type="button" onClick={() => setPairingOpen((open) => !open)} className="rounded-lg px-3 py-2 text-sm font-medium underline">페어링</button>}</div>
        {pairingOpen && <PairingPanel api={api} onPaired={retryAfterPair} />}
        {retryingPair && <span className="sr-only">페어링 후 다시 확인 중</span>}
      </div></div>
    </section>
  );
}

function ReadinessLine({ readiness, checking = false }: { readiness: Readiness | null; checking?: boolean }) {
  if (!readiness) return checking
    ? <span className="inline-flex items-center gap-1.5 text-xs text-[#667085]"><LoaderCircle size={14} className="animate-spin" />서버 준비 상태 확인 중</span>
    : <span className="inline-flex items-center gap-1.5 rounded-full bg-[#F2F4F7] px-2.5 py-1 text-xs text-[#667085]">서버 상태 확인 불가</span>;
  const label = readiness.status === "ready" ? "학습 준비 완료" : readiness.status === "starting" ? "서버 시작 중" : "일부 기능 준비 중";
  const tone = readiness.status === "ready" ? "bg-[#ECFDF3] text-[#027A48]" : readiness.status === "starting" ? "bg-[#FFFAEB] text-[#B54708]" : "bg-[#FEF3F2] text-[#B42318]";
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}><span className="h-1.5 w-1.5 rounded-full bg-current" />{label}</span>;
}

function DocumentReadiness({ document: item }: { document: MnemosyneDocument }) {
  const parse = item.parse_state === "ready" ? "읽기 분석 완료" : item.parse_state === "failed" ? "분석 실패" : item.parse_state === "running" ? "분석 중" : "분석 대기";
  const index = item.index_state === "ready" ? "검색·튜터 준비 완료" : item.index_state === "failed" ? "검색 분석 실패" : item.index_state === "running" ? "검색 분석 중" : "검색 분석 대기";
  return <div className="flex flex-wrap gap-1.5 text-[11px]"><span className={`rounded-full px-2 py-1 ${item.original_available ? "bg-[#ECFDF3] text-[#027A48]" : "bg-[#F2F4F7] text-[#667085]"}`}>{item.original_available ? "PDF 읽기 가능" : "원본 없음"}</span><span className={`rounded-full px-2 py-1 ${item.parse_state === "failed" ? "bg-[#FEF3F2] text-[#B42318]" : item.parse_state === "ready" ? "bg-[#EEF4FF] text-[#315DA8]" : "bg-[#F2F4F7] text-[#667085]"}`}>{parse}</span><span className={`rounded-full px-2 py-1 ${item.index_state === "failed" ? "bg-[#FEF3F2] text-[#B42318]" : item.index_state === "ready" ? "bg-[#EEF4FF] text-[#315DA8]" : "bg-[#F2F4F7] text-[#667085]"}`}>{index}</span></div>;
}

export function MnemosyneLibrary() {
  const api = useMnemosyneApi();
  const [subjects, setSubjects] = useState<MnemosyneSubject[]>([]);
  const [documents, setDocuments] = useState<MnemosyneDocument[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [readinessError, setReadinessError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [query, setQuery] = useState("");
  const [subjectID, setSubjectID] = useState("");
  const [busyID, setBusyID] = useState("");
  const [notice, setNotice] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    setReadinessError("");
    try {
      try {
        const [nextSubjects, nextDocuments] = await Promise.all([api.listSubjects(), api.listDocuments(subjectID || undefined)]);
        setSubjects(nextSubjects);
        setDocuments(nextDocuments);
      } catch (caught) {
        setError(caught);
      }
      try {
        setReadiness(await api.readiness());
      } catch (caught) {
        setReadiness(null);
        setReadinessError(errorMessage(caught));
      }
    } finally {
      setLoading(false);
    }
  }, [api, subjectID]);

  useEffect(() => { void reload(); }, [reload]);

  const visibleDocuments = documents.filter((item) => item.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));

  const addSubject = async () => {
    const name = window.prompt("새 과목 이름");
    if (!name?.trim()) return;
    setBusyID("subject");
    setNotice("");
    try {
      await api.createSubject(name.trim());
      await reload();
      setNotice("과목을 저장했습니다.");
    } catch (caught) {
      setNotice(errorMessage(caught));
    } finally { setBusyID(""); }
  };

  const renameSubject = async (subject: MnemosyneSubject) => {
    const name = window.prompt("과목 이름 변경", subject.name);
    if (!name?.trim() || name.trim() === subject.name) return;
    setBusyID(subject.subject_id);
    setNotice("");
    try { await api.renameSubject(subject, name.trim()); await reload(); setNotice("과목 이름을 저장했습니다."); }
    catch (caught) { setNotice(errorMessage(caught)); }
    finally { setBusyID(""); }
  };

  const removeSubject = async (subject: MnemosyneSubject) => {
    if (!window.confirm(`과목 “${subject.name}”을 삭제할까요?`)) return;
    setBusyID(subject.subject_id);
    setNotice("");
    try { await api.deleteSubject(subject); if (subjectID === subject.subject_id) setSubjectID(""); await reload(); setNotice("과목을 삭제했습니다."); }
    catch (caught) { setNotice(errorMessage(caught)); }
    finally { setBusyID(""); }
  };

  const uploadFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setBusyID("upload");
    setNotice("");
    try {
      const uploaded = await api.uploadDocument(file, file.name.replace(/\.pdf$/i, ""), subjectID || undefined);
      await reload();
      if (uploaded.parse_state === "failed" || uploaded.index_state === "failed") setNotice("파일은 서버에 저장됐지만 분석이 실패했습니다. 다시 상태를 확인하거나 서버에서 재분석을 진행해 주세요.");
    } catch (caught) { setNotice(errorMessage(caught)); }
    finally { setBusyID(""); }
  };

  const changeSubject = async (item: MnemosyneDocument, nextSubject: string) => {
    setBusyID(item.document_id);
    setNotice("");
    try { await api.updateDocument(item, { subject_id: nextSubject || null }); await reload(); setNotice("문서 과목을 저장했습니다."); }
    catch (caught) { setNotice(errorMessage(caught)); }
    finally { setBusyID(""); }
  };

  const download = async (item: MnemosyneDocument) => {
    setBusyID(item.document_id);
    setNotice("");
    try { saveBlob(await api.downloadOriginal(item), `${item.title}.pdf`); setNotice("원본 PDF 다운로드를 시작했습니다."); }
    catch (caught) { setNotice(errorMessage(caught)); }
    finally { setBusyID(""); }
  };

  const removeDocument = async (item: MnemosyneDocument) => {
    if (!window.confirm(`“${item.title}” 원본과 서버 기록을 삭제할까요? 삭제할 문서를 다시 확인했습니다.`)) return;
    setBusyID(item.document_id);
    setNotice("");
    try { await api.deleteDocument(item); await reload(); setNotice("문서 삭제를 서버에서 확인했습니다."); }
    catch (caught) { setNotice(errorMessage(caught)); }
    finally { setBusyID(""); }
  };

  return (
    <div className="min-h-screen bg-[#F5F6F8] text-[#1F2937]">
      <MnemosyneNav active="library" />
      <main className="mx-auto max-w-[1500px] px-5 py-8 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div><div className="flex items-center gap-3"><h1 className="text-2xl font-semibold tracking-tight">라이브러리</h1><ReadinessLine readiness={readiness} checking={loading} /></div><p className="mt-2 text-sm text-[#667085]">원본 PDF와 분석 준비 상태를 관리합니다.</p></div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => void addSubject()} disabled={busyID === "subject"} className="inline-flex items-center gap-2 rounded-lg border border-[#D0D5DD] bg-white px-3 py-2.5 text-sm font-medium hover:bg-[#F9FAFB] disabled:opacity-50"><FolderPlus size={16} />과목 추가</button>
            <button type="button" onClick={() => fileRef.current?.click()} disabled={busyID === "upload"} className="inline-flex items-center gap-2 rounded-lg bg-[#315DA8] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#264B8C] disabled:opacity-50"><Upload size={16} />{busyID === "upload" ? "업로드 중…" : "PDF 올리기"}</button>
            <input ref={fileRef} type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(event) => void uploadFile(event)} />
          </div>
        </div>

        {notice && <p role="status" className="mt-5 rounded-lg border border-[#D0D5DD] bg-white px-4 py-3 text-sm">{notice}</p>}
        {readinessError && <p role="status" className="mt-4 rounded-lg border border-[#FEDF89] bg-[#FFFAEB] px-4 py-3 text-xs leading-5 text-[#7A2E0E]">서버 준비 정보를 확인하지 못했습니다. 문서별 상태는 서버가 돌려준 값으로 표시합니다. {readinessError}</p>}
        {error ? <div className="mt-6"><ErrorPanel error={error} onRetry={() => void reload()} api={api} /></div> : <>
          <section className="mt-7 grid gap-4 rounded-2xl border border-[#EAECF0] bg-white p-4 md:grid-cols-[minmax(0,1fr)_260px] md:items-center">
            <label className="relative block"><span className="sr-only">문서 제목 검색</span><Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#98A2B3]" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="문서 제목 검색" className="w-full rounded-lg border border-[#D0D5DD] py-2.5 pl-10 pr-3 text-sm outline-none focus:border-[#315DA8] focus:ring-2 focus:ring-[#315DA8]/15" /></label>
            <label className="relative block"><span className="sr-only">과목 필터</span><select value={subjectID} onChange={(event) => setSubjectID(event.target.value)} className="w-full appearance-none rounded-lg border border-[#D0D5DD] bg-white px-3 py-2.5 pr-9 text-sm outline-none focus:border-[#315DA8]"><option value="">모든 과목</option>{subjects.map((subject) => <option key={subject.subject_id} value={subject.subject_id}>{subject.name}</option>)}</select><ChevronDown size={16} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#667085]" /></label>
          </section>

          <section className="mt-4 flex flex-wrap items-center gap-2" aria-label="과목 목록">
            {subjects.map((subject) => <div key={subject.subject_id} className={`inline-flex items-center gap-1 rounded-full border px-2 py-1.5 text-xs ${subjectID === subject.subject_id ? "border-[#9AB8E8] bg-[#EDF3FC] text-[#315DA8]" : "border-[#E4E7EC] bg-white text-[#475467]"}`}><button type="button" onClick={() => setSubjectID(subjectID === subject.subject_id ? "" : subject.subject_id)} className="px-1 font-medium">{subject.name}</button><button type="button" aria-label={`${subject.name} 이름 변경`} onClick={() => void renameSubject(subject)} disabled={busyID === subject.subject_id} className="rounded p-1 hover:bg-black/5"><Pencil size={12} /></button><button type="button" aria-label={`${subject.name} 삭제`} onClick={() => void removeSubject(subject)} disabled={busyID === subject.subject_id} className="rounded p-1 text-[#B42318] hover:bg-[#FEF3F2]"><Trash2 size={12} /></button></div>)}
            {subjects.length === 0 && !loading && <span className="text-xs text-[#667085]">과목을 만들면 문서를 주제별로 모을 수 있습니다.</span>}
          </section>

          <div className="mt-6 flex items-center justify-between"><h2 className="text-sm font-semibold">문서 <span className="ml-1 font-normal text-[#667085]">{visibleDocuments.length}</span></h2><button type="button" onClick={() => void reload()} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-[#667085] hover:bg-white"><RefreshCw size={13} />상태 새로고침</button></div>
          {loading ? <div className="mt-4 flex items-center justify-center gap-2 rounded-2xl border border-[#EAECF0] bg-white py-16 text-sm text-[#667085]"><LoaderCircle size={17} className="animate-spin" />라이브러리를 불러오는 중</div> : visibleDocuments.length === 0 ? <div className="mt-4 rounded-2xl border border-dashed border-[#D0D5DD] bg-white px-6 py-16 text-center"><FileText size={28} className="mx-auto text-[#98A2B3]" /><h3 className="mt-3 text-sm font-semibold">{query ? "검색 결과가 없습니다" : "아직 등록한 PDF가 없습니다"}</h3><p className="mt-1 text-sm text-[#667085]">{query ? "다른 제목이나 과목을 선택해 보세요." : "PDF를 올리면 원본 읽기와 분석 상태를 여기서 확인할 수 있습니다."}</p>{!query && <button onClick={() => fileRef.current?.click()} className="mt-4 rounded-lg bg-[#315DA8] px-4 py-2 text-sm font-medium text-white">첫 PDF 올리기</button>}</div> : <div className="mt-4 grid gap-3 xl:grid-cols-2">{visibleDocuments.map((item) => <article key={item.document_id} className="rounded-2xl border border-[#EAECF0] bg-white p-5 shadow-[0_1px_2px_rgba(16,24,40,.04)]"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="flex items-center gap-2"><FileText size={17} className="shrink-0 text-[#315DA8]" /><h3 className="truncate text-[15px] font-semibold">{item.title}</h3></div><p className="mt-1 pl-6 text-xs text-[#667085]">{item.page_count}쪽 · {new Date(item.created_at).toLocaleDateString("ko-KR")}</p></div><label className="relative shrink-0"><span className="sr-only">{item.title} 과목</span><select value={item.subject_id ?? ""} onChange={(event) => void changeSubject(item, event.target.value)} disabled={busyID === item.document_id} className="max-w-[150px] appearance-none rounded-lg border border-[#EAECF0] bg-white px-2.5 py-2 pr-7 text-xs text-[#475467]"><option value="">과목 없음</option>{subjects.map((subject) => <option key={subject.subject_id} value={subject.subject_id}>{subject.name}</option>)}</select><ChevronDown size={13} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[#667085]" /></label></div><div className="mt-4"><DocumentReadiness document={item} /></div><div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[#F2F4F7] pt-4"><Link href={`/learning/reading/${encodeURIComponent(item.document_id)}`} className="inline-flex items-center gap-1.5 rounded-lg bg-[#315DA8] px-3 py-2 text-xs font-medium text-white no-underline hover:bg-[#264B8C]">PDF 읽기 <ArrowLeft size={13} className="rotate-180" /></Link><button type="button" onClick={() => void download(item)} disabled={!item.original_available || busyID === item.document_id} className="inline-flex items-center gap-1.5 rounded-lg border border-[#D0D5DD] px-3 py-2 text-xs font-medium text-[#475467] disabled:opacity-40"><Download size={14} />원본 다운로드</button><button type="button" onClick={() => void removeDocument(item)} disabled={busyID === item.document_id} className="ml-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium text-[#B42318] hover:bg-[#FEF3F2] disabled:opacity-50"><Trash2 size={14} />삭제</button></div>{item.parse_state === "failed" || item.index_state === "failed" ? <p className="mt-3 text-xs text-[#B42318]">서버 분석이 실패했습니다. 현재 계약에는 재분석 action이 없으므로 상태만 다시 확인할 수 있습니다.</p> : null}</article>)}</div>}
        </>}
      </main>
    </div>
  );
}

function pdfPointToUnit(point: [number, number], geometry: PageGeometry): [number, number] {
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

function pdfRectToUnit(rect: PdfRect, geometry: PageGeometry): [number, number, number, number] {
  const [x, y, width, height] = rect;
  const corners: Array<[number, number]> = [[x, y], [x + width, y], [x, y + height], [x + width, y + height]];
  const unit = corners.map((point) => pdfPointToUnit(point, geometry));
  const xs = unit.map(([pointX]) => pointX);
  const ys = unit.map(([, pointY]) => pointY);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

function toReaderAnnotationItems(records: MnemosyneAnnotation[], geometryByPage: Record<number, PageGeometry>): AnnotationItem[] {
  return records.flatMap((record) => {
    if (record.deleted || (record.kind !== "highlight" && record.kind !== "note")) return [];
    const payload = record.payload;
    const anchor = payload && isRecord(payload.anchor) ? payload.anchor : null;
    const geometry = geometryByPage[record.page_index];
    const rawRects = anchor && Array.isArray(anchor.rects) ? anchor.rects as PdfRect[] : [];
    const rects = geometry ? rawRects.map((rect) => pdfRectToUnit(rect, geometry)) : [];
    const body = payload && typeof payload.body === "string" ? payload.body : "";
    const color = payload && typeof payload.color === "string" ? payload.color : "#FFE082AA";
    if (record.kind === "highlight" && !rects.length) return [];
    return [{
      annotation_id: record.annotation_id,
      locator: record.page_index + 1,
      material_revision: record.server_revision,
      kind: record.kind,
      color,
      quote: anchor && typeof anchor.quote === "string" ? anchor.quote : "",
      note: body,
      rects,
      source_anchor: "",
      author: "user",
      created_at: new Date(record.updated_at).getTime(),
      updated_at: new Date(record.updated_at).getTime(),
    } satisfies AnnotationItem];
  });
}

function toReaderInk(records: MnemosyneAnnotation[], geometryByPage: Record<number, PageGeometry>): InkOverlayStroke[] {
  return records.flatMap((record) => {
    if (record.deleted || record.kind !== "ink" || !record.payload || !Array.isArray(record.payload.strokes)) return [];
    const geometry = geometryByPage[record.page_index];
    if (!geometry) return [];
    const [llx, lly, urx, ury] = geometry.crop_box;
    const physicalWidth = (geometry.rotation_degrees === 90 || geometry.rotation_degrees === 270 ? ury - lly : urx - llx) * geometry.user_unit;
    return (record.payload.strokes as Array<Record<string, unknown>>).flatMap((stroke) => {
      if (!Array.isArray(stroke.points) || typeof stroke.stroke_id !== "string" || typeof stroke.color !== "string" || typeof stroke.width_pt !== "number" || (stroke.tool !== "pen" && stroke.tool !== "highlighter")) return [];
      const points = stroke.points.flatMap((point) => {
        if (!isRecord(point) || typeof point.x !== "number" || typeof point.y !== "number") return [];
        return [pdfPointToUnit([point.x, point.y], geometry)];
      });
      if (!points.length) return [];
      return [{ stroke_id: stroke.stroke_id, locator: record.page_index + 1, tool: stroke.tool, color: stroke.color, width: stroke.width_pt / physicalWidth, points } satisfies InkOverlayStroke];
    });
  });
}

function clientDeviceID(): string {
  const key = "mnemosyne.web.device_id";
  try {
    const existing = browserStorage.readRaw("local", key);
    if (existing) return existing;
    const created = newUUID();
    browserStorage.writeRaw("local", key, created);
    return created;
  } catch {
    return newUUID();
  }
}

function applyMutationReceipt(receipt: Awaited<ReturnType<MnemosyneApi["mutateAnnotations"]>>, document: MnemosyneDocument): void {
  if (receipt.contract_version !== MNEMOSYNE_CONTRACT_VERSION || receipt.document_id !== document.document_id || receipt.version_id !== document.version_id || !receipt.results.length) throw new Error("주석 저장 응답이 현재 문서와 맞지 않습니다.");
  const failed = receipt.results.find((result) => result.status !== "applied" || result.code !== "ok");
  if (failed) throw new Error(failed.code === "conflict" ? "다른 기기에서 주석을 바꿨습니다. 최신 주석을 불러온 뒤 다시 시도하세요." : `주석을 저장하지 못했습니다. (${String(failed.code)})`);
}

function annotationMutation(document: MnemosyneDocument, annotation: { annotation_id: string; kind: MnemosyneAnnotation["kind"]; payload: Record<string, unknown> }, mutationID = newUUID(), baseRevision = 0): Record<string, unknown> {
  const now = new Date().toISOString();
  return {
    client_mutation_id: mutationID,
    client_id: clientDeviceID(),
    document_id: document.document_id,
    version_id: document.version_id,
    annotation_id: annotation.annotation_id,
    base_revision: baseRevision,
    created_at: now,
    operation: "upsert",
    annotation: {
      annotation_id: annotation.annotation_id,
      document_id: document.document_id,
      version_id: document.version_id,
      page_index: annotation.payload.page_index,
      kind: annotation.kind,
      payload: annotation.payload.payload,
    },
  };
}

function annotationDeleteMutation(document: MnemosyneDocument, annotation: MnemosyneAnnotation, mutationID = newUUID()): Record<string, unknown> {
  return {
    client_mutation_id: mutationID,
    client_id: clientDeviceID(),
    document_id: document.document_id,
    version_id: document.version_id,
    annotation_id: annotation.annotation_id,
    base_revision: annotation.server_revision,
    created_at: new Date().toISOString(),
    operation: "delete",
  };
}

function readerPositionKey(document: MnemosyneDocument): string {
  return `mnemosyne.reader.position.${document.document_id}.${document.version_id}`;
}

export function MnemosyneReader({ documentID }: { documentID: string }) {
  const api = useMnemosyneApi();
  const [document, setDocument] = useState<MnemosyneDocument | null>(null);
  const [snapshot, setSnapshot] = useState<MnemosyneSnapshot | null>(null);
  const [learning, setLearning] = useState<MnemosyneLearningState | null>(null);
  const [loading, setLoading] = useState(true);
  const [documentError, setDocumentError] = useState<unknown>(null);
  const [readerError, setReaderError] = useState("");
  const [notice, setNotice] = useState("");
  const [currentPage, setCurrentPage] = useState(0);
  const [positionStatus, setPositionStatus] = useState("");
  const [geometryByPage, setGeometryByPage] = useState<Record<number, PageGeometry>>({});
  const [jump, setJump] = useState<JumpRequest | null>(null);
  const jumpNonce = useRef(0);
  const [selectionPayload, setSelectionPayload] = useState<SelectionPayload | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<VerifiedCitation | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MnemosyneTextAnchor[]>([]);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [annotationBusy, setAnnotationBusy] = useState("");
  const [noteComposer, setNoteComposer] = useState(false);
  const [noteDraft, setNoteDraft] = useState("");
  const [pendingSuggestion, setPendingSuggestion] = useState<{ event: SemanticEvent; citation: VerifiedCitation } | null>(null);
  const [quiz, setQuiz] = useState<MnemosyneQuiz | null>(null);
  const [learningRefresh, setLearningRefresh] = useState(0);
  const [panelMode, setPanelMode] = useState<"tutor" | "notes" | "quiz">("tutor");
  const [tutorCapability, setTutorCapability] = useState<MnemosyneTurnRequest["capability"]>("chat");

  const reload = useCallback(async () => {
    setLoading(true);
    setDocumentError(null);
    setReaderError("");
    try {
      const found = await api.getDocument(documentID);
      setDocument(found);
      const params = new URLSearchParams(window.location.search);
      const pageParam = params.get("page_index");
      const queryPage = pageParam === null ? Number.NaN : Number(pageParam);
      let savedPage: number | null = Number.isInteger(queryPage) && queryPage >= 0 && queryPage < found.page_count ? queryPage : null;
      if (savedPage === null) {
        try {
          const stored = browserStorage.readRaw("local", readerPositionKey(found));
          if (stored) {
            const value: unknown = JSON.parse(stored);
            if (isRecord(value) && Number.isInteger(value.page_index) && Number(value.page_index) >= 0 && Number(value.page_index) < found.page_count) savedPage = Number(value.page_index);
          }
        } catch { /* A broken local reading cursor does not block opening the PDF. */ }
      }
      if (savedPage !== null) {
        setCurrentPage(savedPage);
        jumpNonce.current += 1;
        setJump({ locator: savedPage + 1, nonce: jumpNonce.current });
      }
      const requestedCapability = params.get("capability");
      if (["chat", "reading", "quiz", "assessment", "mastery", "solve", "memory", "progress", "review"].includes(requestedCapability ?? "")) setTutorCapability(requestedCapability as MnemosyneTurnRequest["capability"]);
      const quizID = params.get("quiz_id");
      if (quizID) {
        try {
          const foundQuiz = await api.getQuiz(quizID);
          if (sameDocumentVersion(foundQuiz, found)) { setQuiz(foundQuiz); setPanelMode("quiz"); }
          else setReaderError("다른 문서의 퀴즈를 거부했습니다.");
        } catch (caught) { setReaderError(`퀴즈를 불러오지 못했습니다: ${errorMessage(caught)}`); }
      }
      const [nextSnapshot, nextLearning] = await Promise.allSettled([api.annotationSnapshot(found), api.learningState(found)]);
      if (nextSnapshot.status === "fulfilled") setSnapshot(nextSnapshot.value);
      else { setSnapshot(null); setReaderError(`주석을 불러오지 못했습니다: ${errorMessage(nextSnapshot.reason)}`); }
      if (nextLearning.status === "fulfilled") setLearning(nextLearning.value);
      else setLearning(null);
    } catch (caught) { setDocumentError(caught); }
    finally { setLoading(false); }
  }, [api, documentID]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    if (!document) return;
    let cancelled = false;
    void api.learningState(document).then((next) => { if (!cancelled) setLearning(next); }).catch(() => { if (!cancelled) setLearning(null); });
    return () => { cancelled = true; };
  }, [api, document, learningRefresh]);

  const geometryFor = useCallback((locator: number, geometry: { crop_box: [number, number, number, number]; rotation_degrees: 0 | 90 | 180 | 270; user_unit: number }) => {
    const pageIndex = locator - 1;
    setGeometryByPage((current) => {
      const prior = current[pageIndex];
      if (prior && prior.rotation_degrees === geometry.rotation_degrees && prior.user_unit === geometry.user_unit && prior.crop_box.every((n, index) => n === geometry.crop_box[index])) return current;
      return { ...current, [pageIndex]: { media_box: geometry.crop_box, crop_box: geometry.crop_box, rotation_degrees: geometry.rotation_degrees, user_unit: geometry.user_unit } };
    });
  }, []);
  const sourceHeaders = useMemo(() => ({ "X-Mnemosyne-Contract-Version": MNEMOSYNE_CONTRACT_VERSION }), []);
  const currentGeometry = geometryByPage[currentPage] ?? null;
  const readerAnnotations = useMemo(() => toReaderAnnotationItems(snapshot?.annotations ?? [], geometryByPage), [snapshot, geometryByPage]);
  const inkStrokes = useMemo(() => toReaderInk(snapshot?.annotations ?? [], geometryByPage), [snapshot, geometryByPage]);

  const goTo = useCallback((pageIndex: number, quote?: string) => {
    if (!document || !Number.isInteger(pageIndex) || pageIndex < 0 || pageIndex >= document.page_count) return;
    setCurrentPage(pageIndex);
    jumpNonce.current += 1;
    setJump({ locator: pageIndex + 1, ...(quote ? { quote } : {}), nonce: jumpNonce.current });
  }, [document]);

  const onVisiblePage = useCallback((locator: number) => {
    const next = locator - 1;
    if (!document || next < 0 || next >= document.page_count) return;
    setCurrentPage(next);
    const saved = browserStorage.writeRaw("local", readerPositionKey(document), JSON.stringify({ page_index: next, saved_at: new Date().toISOString() }));
    setPositionStatus(saved ? "읽던 위치를 이 브라우저에 저장했습니다." : "브라우저 저장소에 읽던 위치를 저장하지 못했습니다.");
  }, [document]);

  const search = async (query = searchQuery, autoSelectExact = false) => {
    if (!document || !query.trim()) return;
    setSearchBusy(true);
    setSearchError("");
    setSearchResults([]);
    try {
      const results = await api.searchDocument(document, query.trim());
      const valid = results.filter((anchor) => sameDocumentVersion(anchor, document));
      setSearchResults(valid);
      if (autoSelectExact) {
        const exact = valid.find((anchor) => anchor.quote === query.trim());
        if (!exact) throw new Error("서버 분석 결과에서 선택 문장과 정확히 일치하는 근거를 찾지 못했습니다.");
        const citation = await api.verifyCitation(exact, document);
        setSelectedCitation(citation);
        goTo(citation.anchor.page_index, citation.anchor.quote);
      }
      if (!valid.length) setSearchError("문서 검색 결과가 없습니다.");
    } catch (caught) { setSearchError(errorMessage(caught)); }
    finally { setSearchBusy(false); }
  };

  const chooseSearchResult = async (anchor: MnemosyneTextAnchor) => {
    if (!document) return;
    setSearchBusy(true);
    setSearchError("");
    try {
      const citation = await api.verifyCitation(anchor, document);
      setSelectedCitation(citation);
      goTo(citation.anchor.page_index, citation.anchor.quote);
      setNotice("문서 출처를 서버에서 검증했습니다.");
    } catch (caught) { setSearchError(errorMessage(caught)); }
    finally { setSearchBusy(false); }
  };

  const mutate = async (mutation: Record<string, unknown>, statusLabel: string) => {
    if (!document) return;
    setAnnotationBusy("save");
    setNotice("");
    try {
      const receipt = await api.mutateAnnotations(document, [mutation]);
      applyMutationReceipt(receipt, document);
      const fresh = await api.annotationSnapshot(document);
      setSnapshot(fresh);
      setNotice(statusLabel);
    } catch (caught) { setNotice(errorMessage(caught)); }
    finally { setAnnotationBusy(""); }
  };

  const saveHighlight = async () => {
    if (!document || !selectedCitation || !sameDocumentVersion(selectedCitation.anchor, document)) {
      setNotice("하이라이트 저장 전에 검색 결과의 근거를 서버에서 검증해 주세요.");
      return;
    }
    const annotation = { annotation_id: newUUID(), kind: "highlight" as const, payload: { page_index: selectedCitation.anchor.page_index, payload: { anchor: selectedCitation.anchor, color: "#FFE082AA" } } };
    await mutate(annotationMutation(document, annotation), "하이라이트를 서버에 저장했습니다.");
  };

  const saveBookmark = async () => {
    if (!document) return;
    const annotation = { annotation_id: newUUID(), kind: "bookmark" as const, payload: { page_index: currentPage, payload: { label: `p. ${currentPage + 1}` } } };
    await mutate(annotationMutation(document, annotation), "북마크를 서버에 저장했습니다.");
  };

  const saveNote = async () => {
    if (!document || !currentGeometry || !noteDraft.trim()) return;
    const anchor = selectedCitation?.anchor.page_index === currentPage && sameDocumentVersion(selectedCitation.anchor, document) ? selectedCitation.anchor : null;
    const [llx, lly, urx, ury] = currentGeometry.crop_box;
    const position = anchor?.rects[0] ? [anchor.rects[0][0] + anchor.rects[0][2] / 2, anchor.rects[0][1] + anchor.rects[0][3] / 2] : [(llx + urx) / 2, (lly + ury) / 2];
    const annotation = { annotation_id: newUUID(), kind: "note" as const, payload: { page_index: currentPage, payload: { position, body: noteDraft.trim(), anchor } } };
    await mutate(annotationMutation(document, annotation), "노트를 서버에 저장했습니다.");
    setNoteDraft("");
    setNoteComposer(false);
  };

  const deleteAnnotation = async (annotation: MnemosyneAnnotation) => {
    if (!document || !window.confirm("이 주석을 삭제할까요? 삭제 기록은 동기화용 tombstone으로 보관됩니다.")) return;
    await mutate(annotationDeleteMutation(document, annotation), "주석 삭제를 서버에서 확인했습니다.");
  };

  const exportAnnotated = async () => {
    if (!document || !snapshot) return;
    setAnnotationBusy("export");
    setNotice("");
    try {
      const receipt = await api.createExport(document, snapshot.snapshot_revision, true);
      const blob = await api.downloadExport(receipt);
      saveBlob(blob, `${document.title}-주석포함.pdf`);
      setNotice(`원본과 분리된 주석 PDF를 받았습니다. 원본 SHA-256 ${receipt.original_sha256.slice(0, 12)}…`);
    } catch (caught) { setNotice(errorMessage(caught)); }
    finally { setAnnotationBusy(""); }
  };

  const onReaderEvent = useCallback((event: SemanticEvent, citation: VerifiedCitation) => {
    if (!document || !sameDocumentVersion(citation.anchor, document)) return;
    const target = event.payload.target;
    if (!targetMatchesDocument(target, document) || target.page_index !== citation.anchor.page_index) {
      setReaderError("현재 문서와 일치하지 않는 Tutor 명령을 거부했습니다.");
      return;
    }
    if (event.type === "reader.annotate") {
      if (event.payload.requires_confirmation !== true) { setReaderError("확인되지 않은 주석 제안은 저장하지 않았습니다."); return; }
      setPendingSuggestion({ event, citation });
      setPanelMode("notes");
      return;
    }
    if (["reader.goto", "reader.highlight", "reader.flash"].includes(event.type)) {
      goTo(citation.anchor.page_index, citation.anchor.quote);
      setSelectedCitation(citation);
      setPanelMode("tutor");
    }
  }, [document, goTo]);

  const approveSuggestion = async () => {
    if (!document || !pendingSuggestion) return;
    const { event } = pendingSuggestion;
    const suggestedMutationID = event.payload.suggested_mutation_id;
    const draft = event.payload.annotation;
    if (typeof suggestedMutationID !== "string" || !isRecord(draft) || typeof draft.annotation_id !== "string" || typeof draft.kind !== "string" || !isRecord(draft.payload) || draft.document_id !== document.document_id || draft.version_id !== document.version_id) {
      setReaderError("주석 제안이 계약과 맞지 않아 저장하지 않았습니다.");
      return;
    }
    const kind = draft.kind as MnemosyneAnnotation["kind"];
    if (!["highlight", "note", "bookmark", "ink"].includes(kind)) { setReaderError("지원하지 않는 주석 제안입니다."); return; }
    const baseRecord = snapshot?.annotations.find((item) => item.annotation_id === draft.annotation_id);
    const mutation = annotationMutation(document, { annotation_id: draft.annotation_id, kind, payload: { page_index: draft.page_index, payload: draft.payload } }, suggestedMutationID, baseRecord?.server_revision ?? 0);
    await mutate(mutation, "Tutor 주석 제안을 승인해 저장했습니다.");
    setPendingSuggestion(null);
  };

  if (loading && !document) return <div className="min-h-screen bg-[#F5F6F8]"><MnemosyneNav active="library" /><div className="flex min-h-[60vh] items-center justify-center gap-2 text-sm text-[#667085]"><LoaderCircle size={17} className="animate-spin" />문서를 여는 중</div></div>;
  if (documentError) return <div className="min-h-screen bg-[#F5F6F8]"><MnemosyneNav active="library" /><main className="mx-auto max-w-3xl px-5 py-10"><ErrorPanel error={documentError} onRetry={() => void reload()} api={api} /></main></div>;
  if (!document) return null;

  const pageItems = snapshot?.annotations.filter((item) => !item.deleted) ?? [];
  const bookmarks = pageItems.filter((item) => item.kind === "bookmark");
  const pageTitle = `p. ${currentPage + 1}`;

  return (
    <div className="flex h-screen min-h-[680px] flex-col bg-[#F5F6F8] text-[#1F2937]">
      <MnemosyneNav active="library" />
      <div className="flex min-h-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E4E7EC] bg-white px-4 py-3 lg:px-6">
          <div className="flex min-w-0 items-center gap-3"><Link href="/learning/reading" className="rounded-lg p-2 text-[#667085] hover:bg-[#F2F4F7]" aria-label="라이브러리로 돌아가기"><ArrowLeft size={17} /></Link><div className="min-w-0"><h1 className="truncate text-sm font-semibold">{document.title}</h1><div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[#667085]"><span>{document.page_count}쪽</span><span>·</span><span>{document.original_available ? "읽기 가능" : "원본 없음"}</span><span>·</span><span>{document.parse_state === "ready" ? "분석 완료" : document.parse_state === "failed" ? "분석 실패" : "분석 중"}</span></div></div></div>
          <div className="flex flex-wrap items-center gap-2">
            <form onSubmit={(event) => { event.preventDefault(); void search(); }} className="flex items-center gap-1"><label htmlFor="mnemo-reader-search" className="sr-only">PDF에서 검색</label><div className="relative"><Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#98A2B3]" /><input id="mnemo-reader-search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="문서에서 찾기" className="w-40 rounded-lg border border-[#D0D5DD] py-2 pl-8 pr-2 text-xs outline-none focus:border-[#315DA8] md:w-52" /></div><button disabled={searchBusy || !searchQuery.trim()} className="rounded-lg border border-[#D0D5DD] px-2.5 py-2 text-xs disabled:opacity-50">{searchBusy ? "검색 중" : "검색"}</button></form>
            <label className="flex items-center gap-1 rounded-lg border border-[#D0D5DD] bg-white px-2.5 py-2 text-xs"><span className="text-[#667085]">페이지</span><input aria-label="물리 페이지 번호" type="number" min={1} max={document.page_count} value={currentPage + 1} onChange={(event) => { const page = Number(event.target.value); if (page > 0 && page <= document.page_count) goTo(page - 1); }} className="w-12 border-0 p-0 text-center text-xs outline-none" /><span className="text-[#667085]">/ {document.page_count}</span></label>
            <button type="button" onClick={() => void saveHighlight()} disabled={annotationBusy !== "" || !selectedCitation} className="rounded-lg border border-[#D0D5DD] bg-white px-2.5 py-2 text-xs font-medium disabled:opacity-40">하이라이트</button>
            <button type="button" onClick={() => setNoteComposer((value) => !value)} className="rounded-lg border border-[#D0D5DD] bg-white px-2.5 py-2 text-xs font-medium">노트</button>
            <button type="button" onClick={() => void saveBookmark()} disabled={annotationBusy !== ""} className="rounded-lg border border-[#D0D5DD] bg-white px-2.5 py-2 text-xs font-medium">북마크</button>
            <button type="button" onClick={() => void exportAnnotated()} disabled={annotationBusy !== "" || !snapshot} className="inline-flex items-center gap-1.5 rounded-lg bg-[#315DA8] px-3 py-2 text-xs font-medium text-white disabled:opacity-50"><Download size={14} />{annotationBusy === "export" ? "내보내는 중" : "주석 PDF"}</button>
          </div>
        </header>
        {(notice || readerError || searchError || positionStatus) && <div role="status" className={`border-b px-4 py-2 text-xs ${readerError || searchError ? "border-[#FDA29B] bg-[#FEF3F2] text-[#B42318]" : "border-[#D0D5DD] bg-white text-[#475467]"}`}>{readerError || searchError || notice || positionStatus}</div>}
        {searchResults.length > 0 && <div className="flex gap-2 overflow-x-auto border-b border-[#E4E7EC] bg-[#F8FAFC] px-4 py-2">{searchResults.map((anchor, index) => <button key={`${anchor.page_index}-${anchor.start_scalar}-${index}`} type="button" onClick={() => void chooseSearchResult(anchor)} disabled={searchBusy} className="max-w-[300px] shrink-0 rounded-lg border border-[#D0D5DD] bg-white px-3 py-2 text-left text-xs hover:border-[#98B3DE]"><span className="font-semibold text-[#315DA8]">p. {anchor.page_index + 1}</span><span className="ml-2 line-clamp-2 text-[#475467]">{anchor.quote}</span></button>)}</div>}
        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_390px]">
          <main className="relative min-h-[420px] min-w-0 border-r border-[#E4E7EC]">
            <div className="absolute left-4 top-3 z-10 rounded-full border border-[#E4E7EC] bg-white/95 px-3 py-1 text-xs font-medium shadow-sm">{pageTitle}</div>
            <PdfDocumentView materialId={document.document_id} sourceUrl={api.originalFileURL(document)} sourceHeaders={sourceHeaders} unitCount={document.page_count} annotations={readerAnnotations} inkStrokes={inkStrokes} jump={jump} onSelection={setSelectionPayload} onVisibleLocatorChange={onVisiblePage} onPageGeometryChange={geometryFor} onAnnotationClick={(annotation) => { const record = snapshot?.annotations.find((item) => item.annotation_id === annotation.annotation_id); if (record) goTo(record.page_index, annotation.quote || undefined); }} />
            {selectionPayload && <div className="absolute bottom-3 left-3 right-3 z-10 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#D0D5DD] bg-white/95 p-3 shadow-lg"><span className="line-clamp-2 min-w-0 flex-1 text-xs text-[#475467]">선택: {selectionPayload.quote}</span><button type="button" onClick={() => { setSearchQuery(selectionPayload.quote); void search(selectionPayload.quote, true); }} disabled={searchBusy || document.parse_state !== "ready"} className="rounded-lg bg-[#315DA8] px-3 py-2 text-xs font-medium text-white disabled:opacity-40">{searchBusy ? "근거 확인 중" : "선택 문장 근거 찾기"}</button><button type="button" onClick={() => setSelectionPayload(null)} aria-label="선택 지우기" className="rounded p-2 text-[#667085] hover:bg-[#F2F4F7]">×</button></div>}
            {document.parse_state !== "ready" && <div className="absolute bottom-3 left-3 z-10 max-w-[300px] rounded-lg border border-[#FEDF89] bg-[#FFFAEB] px-3 py-2 text-[11px] leading-5 text-[#7A2E0E]">PDF는 읽을 수 있습니다. 문서 검색과 텍스트 인용은 분석 완료 후 사용할 수 있습니다.</div>}
          </main>
          <aside className="flex min-h-[520px] min-w-0 flex-col bg-white">
            <div className="flex border-b border-[#EAECF0] px-3 pt-2"><button type="button" onClick={() => setPanelMode("tutor")} className={`flex-1 rounded-t-lg px-2 py-2 text-xs font-medium ${panelMode === "tutor" ? "border-b-2 border-[#315DA8] text-[#315DA8]" : "text-[#667085]"}`}>튜터</button><button type="button" onClick={() => setPanelMode("notes")} className={`flex-1 rounded-t-lg px-2 py-2 text-xs font-medium ${panelMode === "notes" ? "border-b-2 border-[#315DA8] text-[#315DA8]" : "text-[#667085]"}`}>노트·북마크</button><button type="button" onClick={() => setPanelMode("quiz")} className={`flex-1 rounded-t-lg px-2 py-2 text-xs font-medium ${panelMode === "quiz" ? "border-b-2 border-[#315DA8] text-[#315DA8]" : "text-[#667085]"}`}>퀴즈</button></div>
            {panelMode === "tutor" && currentGeometry && <TutorPanel api={api} document={document} pageIndex={currentPage} geometry={currentGeometry} selection={selectedCitation?.anchor ?? null} initialCapability={tutorCapability} onReaderEvent={onReaderEvent} onQuizReady={(value) => { setQuiz(value); setPanelMode("quiz"); }} onLearningUpdated={() => setLearningRefresh((value) => value + 1)} />}
            {panelMode === "tutor" && !currentGeometry && <div className="p-5 text-sm text-[#667085]">PDF 페이지 geometry를 불러오는 중입니다. geometry가 준비되면 이 문서에서 튜터를 사용할 수 있습니다.</div>}
            {panelMode === "quiz" && <QuizPanel api={api} document={document} quiz={quiz} learning={learning} onLearningUpdated={() => setLearningRefresh((value) => value + 1)} onGenerate={() => { setTutorCapability("quiz"); setPanelMode("tutor"); }} onCitation={(citation) => { setSelectedCitation(citation); goTo(citation.anchor.page_index, citation.anchor.quote); }} />}
            {panelMode === "notes" && <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {noteComposer && <div className="mb-4 rounded-xl border border-[#C7D7F2] bg-[#F8FAFF] p-3"><label htmlFor="mnemo-note-body" className="text-xs font-semibold">현재 페이지 노트</label><textarea id="mnemo-note-body" value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} rows={3} maxLength={20000} className="mt-2 w-full rounded-lg border border-[#D0D5DD] bg-white p-2 text-sm outline-none focus:border-[#315DA8]" placeholder="복습할 내용이나 생각을 기록하세요" /><div className="mt-2 flex justify-end gap-2"><button onClick={() => setNoteComposer(false)} className="rounded-lg px-3 py-2 text-xs">취소</button><button onClick={() => void saveNote()} disabled={!noteDraft.trim() || !currentGeometry || annotationBusy !== ""} className="rounded-lg bg-[#315DA8] px-3 py-2 text-xs font-medium text-white disabled:opacity-50">{annotationBusy === "save" ? "저장 중" : "서버에 저장"}</button></div></div>}
              {pendingSuggestion && <div className="mb-4 rounded-xl border border-[#FEDF89] bg-[#FFFAEB] p-3"><div className="text-xs font-semibold text-[#7A2E0E]">Tutor 주석 제안</div><p className="mt-1 text-xs leading-5 text-[#7A2E0E]">검증된 근거에 연결된 제안입니다. 승인하기 전에는 주석으로 저장되지 않습니다.</p><div className="mt-2 flex gap-2"><button onClick={() => void approveSuggestion()} className="rounded-lg bg-[#315DA8] px-3 py-2 text-xs font-medium text-white">승인하고 저장</button><button onClick={() => setPendingSuggestion(null)} className="rounded-lg border border-[#D0D5DD] bg-white px-3 py-2 text-xs">거절</button></div></div>}
              <div className="text-xs font-semibold text-[#667085]">저장된 주석</div>
              {!snapshot && <div className="mt-3 rounded-lg border border-[#FDA29B] bg-[#FEF3F2] p-3 text-xs text-[#B42318]">주석 snapshot을 불러오지 못했습니다. 저장 상태를 추측하지 않습니다.<button onClick={() => void reload()} className="ml-2 underline">다시 시도</button></div>}
              {pageItems.length === 0 && snapshot && <div className="py-10 text-center text-xs text-[#667085]">이 문서에는 아직 저장된 주석이 없습니다.</div>}
              <div className="mt-2 space-y-2">{pageItems.map((annotation) => { const payload = annotation.payload ?? {}; const anchor = isRecord(payload.anchor) ? payload.anchor : null; const label = annotation.kind === "bookmark" ? (typeof payload.label === "string" ? payload.label : "북마크") : annotation.kind === "note" ? (typeof payload.body === "string" ? payload.body : "노트") : annotation.kind === "highlight" ? (anchor && typeof anchor.quote === "string" ? anchor.quote : "하이라이트") : `iPad 필기 · ${(Array.isArray(payload.strokes) ? payload.strokes.length : 0)}획`;
                return <article key={annotation.annotation_id} className="rounded-xl border border-[#EAECF0] p-3"><div className="flex items-start justify-between gap-2"><button type="button" onClick={() => goTo(annotation.page_index, anchor && typeof anchor.quote === "string" ? anchor.quote : undefined)} className="min-w-0 flex-1 text-left"><span className="block text-[10px] font-semibold text-[#315DA8]">p. {annotation.page_index + 1} · {annotation.kind === "highlight" ? "하이라이트" : annotation.kind === "note" ? "노트" : annotation.kind === "bookmark" ? "북마크" : "iPad 필기"}</span><span className="mt-1 block break-words text-xs leading-5 text-[#475467]">{label}</span></button><button type="button" onClick={() => void deleteAnnotation(annotation)} disabled={annotationBusy !== ""} aria-label="주석 삭제" className="rounded p-1.5 text-[#B42318] hover:bg-[#FEF3F2] disabled:opacity-50"><Trash2 size={14} /></button></div></article>;
              })}</div>
              {bookmarks.length > 0 && <p className="mt-3 text-[10px] text-[#667085]">북마크 {bookmarks.length}개 · 주석 revision {snapshot?.snapshot_revision ?? "—"}</p>}
            </div>}
          </aside>
        </div>
      </div>
    </div>
  );
}

type TutorStatus = "idle" | "connecting" | "streaming" | "reconnecting" | "cancelling" | "completed" | "failed" | "cancelled";
type TutorMessage = { id: string; role: "user" | "assistant" | "system"; text: string };

function eventCitationID(event: SemanticEvent): string | null {
  const payload = event.payload;
  return typeof payload.citation_id === "string" ? payload.citation_id : null;
}

function targetMatchesDocument(target: unknown, document: MnemosyneDocument): target is { document_id: string; version_id: string; page_index: number } {
  return isRecord(target) && target.document_id === document.document_id && target.version_id === document.version_id && Number.isInteger(target.page_index) && Number(target.page_index) >= 0;
}

function TutorPanel({
  api,
  document,
  pageIndex,
  geometry,
  selection,
  initialCapability,
  onReaderEvent,
  onQuizReady,
  onLearningUpdated,
}: {
  api: MnemosyneApi;
  document: MnemosyneDocument;
  pageIndex: number;
  geometry: PageGeometry | null;
  selection: MnemosyneTextAnchor | null;
  initialCapability: MnemosyneTurnRequest["capability"];
  onReaderEvent: (event: SemanticEvent, citation: VerifiedCitation) => void;
  onQuizReady: (quiz: MnemosyneQuiz) => void;
  onLearningUpdated: () => void;
}) {
  const [capability, setCapability] = useState<MnemosyneTurnRequest["capability"]>(initialCapability);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<TutorMessage[]>([]);
  const [citations, setCitations] = useState<VerifiedCitation[]>([]);
  const [status, setStatus] = useState<TutorStatus>("idle");
  const [error, setError] = useState("");
  const [resumeCandidate, setResumeCandidate] = useState<{ turn_id: string; seq: number; session_id: string } | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const attemptsRef = useRef(0);
  const runtimeRef = useRef<{
    request: MnemosyneTurnRequest;
    command: Record<string, unknown>;
    sessionID: string;
    turnID: string | null;
    lastSeq: number;
    reconnecting: boolean;
    shouldReconnect: boolean;
    assistantMessageID: string;
  } | null>(null);
  const connectRef = useRef<() => void>(() => undefined);
  const verifiedCitationRef = useRef<VerifiedCitation | null>(null);
  const citationMapRef = useRef(new Map<string, VerifiedCitation>());
  const resumeStorageKey = `mnemosyne.resume.${document.document_id}.${document.version_id}`;

  useEffect(() => { setCapability(initialCapability); }, [initialCapability]);

  const bridge = useMemo(() => mountMnemosyneWeb({
    serverURL: api.baseURL,
    dispatchReaderEvent: (event) => {
      const citation = verifiedCitationRef.current;
      if (citation) onReaderEvent(event, citation);
    },
    persistCheckpoint: async (turnID, seq) => {
      const runtime = runtimeRef.current;
      if (!runtime || runtime.turnID !== turnID) return;
      const value = { turn_id: turnID, seq, session_id: runtime.sessionID };
      browserStorage.writeRaw("local", resumeStorageKey, JSON.stringify(value));
    },
  }), [api, onReaderEvent, resumeStorageKey]);

  useEffect(() => {
    try {
      const saved = browserStorage.readRaw("local", resumeStorageKey);
      if (!saved) { setResumeCandidate(null); return; }
      const parsed: unknown = JSON.parse(saved);
      if (isRecord(parsed) && typeof parsed.turn_id === "string" && Number.isInteger(parsed.seq) && typeof parsed.session_id === "string") {
        setResumeCandidate({ turn_id: parsed.turn_id, seq: Number(parsed.seq), session_id: parsed.session_id });
      }
    } catch { setResumeCandidate(null); }
  }, [resumeStorageKey]);

  const connectSocket = useCallback(() => {
    const runtime = runtimeRef.current;
    if (!runtime || !runtime.shouldReconnect || socketRef.current?.readyState === WebSocket.OPEN || socketRef.current?.readyState === WebSocket.CONNECTING) return;
    setStatus(runtime.reconnecting ? "reconnecting" : "connecting");
    setError("");
    try {
      const url = new URL("/ws", api.baseURL);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      const socket = new WebSocket(url.toString());
      socketRef.current = socket;
      socket.onopen = () => {
        const active = runtimeRef.current;
        if (!active || !active.shouldReconnect) { socket.close(); return; }
        attemptsRef.current = 0;
        if (active.turnID) {
          socket.send(JSON.stringify({ type: "resume_from", protocol_version: MNEMOSYNE_PROTOCOL_VERSION, turn_id: active.turnID, seq: active.lastSeq }));
        } else {
          socket.send(JSON.stringify(active.command));
        }
        setStatus("streaming");
      };
      socket.onmessage = (messageEvent) => {
        void (async () => {
          const active = runtimeRef.current;
          if (!active || !active.shouldReconnect) return;
          let frame: StreamEvent;
          try {
            const decoded: unknown = JSON.parse(String(messageEvent.data));
            if (!isRecord(decoded) || typeof decoded.type !== "string") throw new Error("잘못된 WebSocket frame입니다.");
            frame = decoded as unknown as StreamEvent;
          } catch (caught) { setError(errorMessage(caught)); return; }

          const seq = Number(frame.seq);
          const frameTurnID = typeof frame.turn_id === "string" ? frame.turn_id : "";
          if (frameTurnID && active.turnID && frameTurnID !== active.turnID) return;
          if (frameTurnID && !active.turnID && frame.type === "content") {
            // The server assigns an opaque native turn ID; it is never rewritten as a UUID.
            active.turnID = frameTurnID;
          }
          if (Number.isInteger(seq) && seq > 0 && frameTurnID) {
            if (active.turnID && frameTurnID !== active.turnID) return;
            if (seq <= active.lastSeq) return;
            if (active.lastSeq > 0 && seq !== active.lastSeq + 1) {
              socket.send(JSON.stringify({ type: "resume_from", protocol_version: MNEMOSYNE_PROTOCOL_VERSION, turn_id: frameTurnID, seq: active.lastSeq }));
              return;
            }
          }

          try {
            const semantic = bridge.consumeNativeFrame(frame);
            if (semantic) {
              if (semantic.turn_id !== (active.turnID ?? semantic.turn_id)) throw new Error("다른 Tutor turn의 이벤트를 거부했습니다.");
              if (semantic.type === "turn.started") {
                active.turnID = semantic.turn_id;
                setResumeCandidate({ turn_id: semantic.turn_id, seq, session_id: active.sessionID });
              } else if (semantic.type === "assistant.delta") {
                const text = semantic.payload.text;
                if (typeof text === "string") setMessages((current) => current.map((item) => item.id === active.assistantMessageID ? { ...item, text: item.text + text } : item));
              } else if (semantic.type === "citation.verified") {
                const rawCitation = semantic.payload.citation;
                if (!isRecord(rawCitation) || rawCitation.verified !== true || !isRecord(rawCitation.anchor) || !sameDocumentVersion(rawCitation.anchor, document)) throw new Error("현재 문서가 아닌 인용을 거부했습니다.");
                const citation = await api.verifyCitation(rawCitation.anchor as unknown as MnemosyneTextAnchor, document);
                if (citation.citation_id !== rawCitation.citation_id) throw new Error("서버 인용 ID가 스트림과 다릅니다.");
                citationMapRef.current.set(citation.citation_id, citation);
                verifiedCitationRef.current = citation;
                setCitations((current) => current.some((item) => item.citation_id === citation.citation_id) ? current : [...current, citation]);
              } else if (["reader.goto", "reader.highlight", "reader.flash", "reader.annotate"].includes(semantic.type)) {
                const payload = semantic.payload;
                const target = payload.target ?? (isRecord(payload.annotation) ? payload.annotation : null);
                if (!targetMatchesDocument(target, document)) throw new Error("다른 문서/version의 Reader 명령을 거부했습니다.");
                const citationID = eventCitationID(semantic);
                const citation = citationID ? citationMapRef.current.get(citationID) : null;
                if (!citation || !sameDocumentVersion(citation.anchor, document) || citation.anchor.page_index !== target.page_index) throw new Error("검증된 현재 문서 출처가 없는 Reader 명령을 거부했습니다.");
                if (semantic.type === "reader.annotate") {
                  if (payload.requires_confirmation !== true || typeof payload.suggested_mutation_id !== "string") throw new Error("주석 제안 확인 정보가 없습니다.");
                  const proposed = payload.annotation;
                  if (!isRecord(proposed) || proposed.document_id !== document.document_id || proposed.version_id !== document.version_id || proposed.page_index !== citation.anchor.page_index) throw new Error("현재 문서와 맞지 않는 주석 제안을 거부했습니다.");
                  const proposedPayload = isRecord(proposed.payload) ? proposed.payload : null;
                  const proposedAnchor = proposedPayload && isRecord(proposedPayload.anchor) ? proposedPayload.anchor : null;
                  if (proposedAnchor && JSON.stringify(proposedAnchor) !== JSON.stringify(citation.anchor)) throw new Error("검증 인용과 다른 위치의 주석 제안을 거부했습니다.");
                }
                verifiedCitationRef.current = citation;
                bridge.dependencies.dispatchReaderEvent(semantic);
              } else if (semantic.type === "quiz.show") {
                const quizID = semantic.payload.quiz_id;
                if (typeof quizID !== "string") throw new Error("퀴즈 이벤트에 quiz_id가 없습니다.");
                const quiz = await api.getQuiz(quizID);
                if (!sameDocumentVersion(quiz, document)) throw new Error("다른 문서의 퀴즈를 거부했습니다.");
                onQuizReady(quiz);
              } else if (semantic.type === "learning.updated") {
                onLearningUpdated();
              } else if (semantic.type === "turn.done") {
                active.shouldReconnect = false;
                setStatus("completed");
                onLearningUpdated();
              } else if (semantic.type === "turn.error") {
                active.shouldReconnect = false;
                setStatus("failed");
                setError(typeof semantic.payload.message_ko === "string" ? semantic.payload.message_ko : "Tutor 요청이 실패했습니다.");
              } else if (semantic.type === "turn.cancelled") {
                active.shouldReconnect = false;
                setStatus("cancelled");
              }
            } else if (frame.type === "error") {
              const metadata = isRecord(frame.metadata) ? frame.metadata : {};
              if (metadata.turn_terminal !== true) setError(typeof metadata.reason === "string" ? metadata.reason : "Tutor 연결에서 복구 가능한 오류가 발생했습니다. 다시 연결 중입니다.");
            }
            if (Number.isInteger(seq) && seq > active.lastSeq && frameTurnID && active.turnID === frameTurnID) {
              await bridge.dependencies.persistCheckpoint(frameTurnID, seq);
              active.lastSeq = seq;
              setResumeCandidate({ turn_id: frameTurnID, seq, session_id: active.sessionID });
            }
          } catch (caught) {
            setError(errorMessage(caught));
            // The rejected event is checkpointed so replay cannot repeat a command for the wrong document.
            if (Number.isInteger(seq) && seq > active.lastSeq && frameTurnID && active.turnID === frameTurnID) {
              await bridge.dependencies.persistCheckpoint(frameTurnID, seq);
              active.lastSeq = seq;
            }
          }
        })();
      };
      socket.onerror = () => setError("Tutor WebSocket에 연결할 수 없습니다.");
      socket.onclose = () => {
        const active = runtimeRef.current;
        if (!active?.shouldReconnect) return;
        attemptsRef.current += 1;
        if (attemptsRef.current > 10) { active.shouldReconnect = false; setStatus("failed"); setError("Tutor 재연결을 완료하지 못했습니다. 네트워크와 서버 준비 상태를 확인하세요."); return; }
        active.reconnecting = true;
        setStatus("reconnecting");
        timerRef.current = window.setTimeout(() => connectRef.current(), Math.min(8000, 500 * 2 ** (attemptsRef.current - 1)));
      };
    } catch (caught) {
      setStatus("failed");
      setError(errorMessage(caught));
    }
  }, [api, bridge, document, onLearningUpdated, onQuizReady]);
  connectRef.current = connectSocket;

  const makeSessionID = () => {
    const key = `mnemosyne.session.${document.document_id}.${document.version_id}`;
    try {
      const existing = browserStorage.readRaw("local", key);
      if (existing) return existing;
      const created = newUUID();
      browserStorage.writeRaw("local", key, created);
      return created;
    } catch { return newUUID(); }
  };

  const start = (message: string, selectedCapability = capability) => {
    if (!message.trim() || !geometry) return;
    const sessionID = makeSessionID();
    const request: MnemosyneTurnRequest = {
      client_mutation_id: newUUID(),
      capability: selectedCapability,
      message: message.trim(),
      reader_context: {
        document_id: document.document_id,
        version_id: document.version_id,
        page_index: pageIndex,
        viewport_rect: geometry.crop_box,
        selection: selection && sameDocumentVersion(selection, document) ? selection : null,
        content_language: document.content_language,
        response_language: "ko",
      },
      response_language: "ko",
    };
    const assistantMessageID = newUUID();
    const command = {
      type: "start_turn",
      protocol_version: MNEMOSYNE_PROTOCOL_VERSION,
      content: request.message,
      client_submission_id: request.client_mutation_id,
      session_id: sessionID,
      capability: "chat",
      reply_language_override: "ko",
      language: document.content_language,
      config: { mnemosyne: { contract_version: MNEMOSYNE_CONTRACT_VERSION, turn_request: request } },
    };
    runtimeRef.current = { request, command, sessionID, turnID: null, lastSeq: 0, reconnecting: false, shouldReconnect: true, assistantMessageID };
    citationMapRef.current.clear();
    setCitations([]);
    setMessages((current) => [...current, { id: newUUID(), role: "user", text: request.message }, { id: assistantMessageID, role: "assistant", text: "" }]);
    setDraft("");
    setError("");
    setStatus("connecting");
    attemptsRef.current = 0;
    connectRef.current();
  };

  const resume = async () => {
    if (!resumeCandidate) return;
    setError("");
    try {
      const receipt = await api.getTurn(resumeCandidate.turn_id);
      if (receipt.turn_id !== resumeCandidate.turn_id) throw new Error("서버 turn ID가 다릅니다.");
      const sessionID = resumeCandidate.session_id;
      const request: MnemosyneTurnRequest = {
        client_mutation_id: newUUID(), capability: "chat", message: "이전 Tutor 응답 이어 받기",
        reader_context: { document_id: document.document_id, version_id: document.version_id, page_index: pageIndex, viewport_rect: geometry?.crop_box ?? [0, 0, 1, 1], selection: null, content_language: document.content_language, response_language: "ko" }, response_language: "ko",
      };
      const assistantMessageID = newUUID();
      runtimeRef.current = { request, command: {}, sessionID, turnID: receipt.turn_id, lastSeq: resumeCandidate.seq, reconnecting: true, shouldReconnect: true, assistantMessageID };
      setMessages((current) => [...current, { id: newUUID(), role: "system", text: "저장된 Tutor 응답에 다시 연결합니다." }, { id: assistantMessageID, role: "assistant", text: "" }]);
      setStatus("reconnecting");
      connectRef.current();
    } catch (caught) { setError(errorMessage(caught)); }
  };

  const cancel = () => {
    const active = runtimeRef.current;
    const socket = socketRef.current;
    if (!active?.turnID || !socket || socket.readyState !== WebSocket.OPEN) return;
    setStatus("cancelling");
    socket.send(JSON.stringify({ type: "cancel_turn", protocol_version: MNEMOSYNE_PROTOCOL_VERSION, turn_id: active.turnID, command_id: newUUID() }));
  };

  useEffect(() => () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    const active = runtimeRef.current;
    if (active) active.shouldReconnect = false;
    socketRef.current?.close();
  }, []);

  const isBusy = ["connecting", "streaming", "reconnecting", "cancelling"].includes(status);
  const capabilityOptions: Array<[MnemosyneTurnRequest["capability"], string]> = [["chat", "문서와 대화"], ["reading", "읽기 도움"], ["quiz", "퀴즈 만들기"], ["assessment", "답안 평가"], ["mastery", "숙련도 학습"], ["solve", "심화 풀이"], ["memory", "기억 카드"], ["progress", "진도 확인"], ["review", "복습"]];
  const submit = (event: React.FormEvent<HTMLFormElement>) => { event.preventDefault(); start(draft); };

  return (
    <section className="flex h-full min-h-[520px] flex-col bg-white">
      <div className="border-b border-[#EAECF0] px-4 py-3"><div className="flex items-center justify-between gap-2"><div><h2 className="flex items-center gap-2 text-sm font-semibold"><MessageCircle size={16} className="text-[#315DA8]" />튜터</h2><p className="mt-1 text-[11px] text-[#667085]">현재 문서 · p. {pageIndex + 1}{selection ? " · 선택 인용 포함" : ""}</p></div><label className="sr-only" htmlFor="mnemo-capability">학습 기능</label><select id="mnemo-capability" value={capability} onChange={(event) => setCapability(event.target.value as MnemosyneTurnRequest["capability"])} disabled={isBusy} className="max-w-[145px] rounded-lg border border-[#D0D5DD] bg-white px-2 py-1.5 text-xs">{capabilityOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div></div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
        {messages.length === 0 && <div className="rounded-xl bg-[#F5F6F8] p-4"><p className="text-sm font-medium">읽던 PDF에서 바로 물어보세요.</p><p className="mt-1 text-xs leading-5 text-[#667085]">응답은 한국어로 요청하고, 인용·수식·코드는 원문 그대로 표시합니다.</p>{!geometry && <p className="mt-2 text-xs text-[#B54708]">PDF geometry가 아직 로드되지 않아 Tutor 요청을 보낼 수 없습니다.</p>}</div>}
        {messages.map((message) => <div key={message.id} className={`rounded-xl px-3.5 py-3 text-sm leading-6 ${message.role === "user" ? "ml-7 bg-[#EDF3FC] text-[#1F2937]" : message.role === "system" ? "bg-[#FFFAEB] text-[#7A2E0E]" : "mr-3 bg-[#F5F6F8] text-[#1F2937]"}`}><div className="mb-1 text-[10px] font-semibold text-[#667085]">{message.role === "user" ? "나" : message.role === "assistant" ? "튜터" : "상태"}</div><div className="whitespace-pre-wrap break-words">{message.text || (isBusy && message.role === "assistant" ? "답변을 기다리는 중…" : "")}</div></div>)}
        {citations.map((citation) => <button key={citation.citation_id} type="button" onClick={() => onReaderEvent({ contract_version: MNEMOSYNE_CONTRACT_VERSION, event_id: `citation:${citation.citation_id}`, turn_id: "", seq: 0, type: "reader.goto", payload: { target: { document_id: document.document_id, version_id: document.version_id, page_index: citation.anchor.page_index }, position: [0, 0], citation_id: citation.citation_id } }, citation)} className="rounded-full border border-[#C7D7F2] bg-[#F8FAFF] px-2.5 py-1 text-xs font-medium text-[#315DA8]">p. {citation.anchor.page_index + 1} · 근거 보기</button>)}
        {error && <div role="alert" className="rounded-lg border border-[#FDA29B] bg-[#FEF3F2] p-3 text-xs leading-5 text-[#B42318]">{error}</div>}
      </div>
      <div className="border-t border-[#EAECF0] px-3 py-2"><div className="flex items-center justify-between text-[11px] text-[#667085]"><span>{status === "streaming" ? "응답 생성 중" : status === "reconnecting" ? "이전 응답에 재접속 중" : status === "completed" ? "응답 저장 완료" : status === "cancelled" ? "요청 취소됨" : status === "failed" ? "요청 실패" : "서버 연결 시 Tutor 사용 가능"}</span>{isBusy && <button type="button" onClick={cancel} className="rounded px-2 py-1 font-medium text-[#B42318] hover:bg-[#FEF3F2]">취소</button>}{!isBusy && resumeCandidate && <button type="button" onClick={() => void resume()} className="inline-flex items-center gap-1 rounded px-2 py-1 font-medium text-[#315DA8] hover:bg-[#EDF3FC]"><RefreshCw size={12} />다시 연결</button>}</div></div>
      <form onSubmit={submit} className="border-t border-[#EAECF0] p-3"><label className="sr-only" htmlFor="mnemo-tutor-message">튜터에게 질문</label><textarea id="mnemo-tutor-message" value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={20000} rows={3} placeholder="이 페이지에서 궁금한 내용을 적어주세요" disabled={isBusy || !geometry} className="w-full resize-y rounded-lg border border-[#D0D5DD] px-3 py-2 text-sm outline-none focus:border-[#315DA8] focus:ring-2 focus:ring-[#315DA8]/15 disabled:bg-[#F9FAFB]" /><div className="mt-2 flex items-center justify-between"><span className="text-[10px] text-[#667085]">{selection ? "검증된 선택 인용이 포함됩니다." : "선택 인용은 Reader에서 서버 검증 후 포함됩니다."}</span><button type="submit" disabled={isBusy || !draft.trim() || !geometry} className="rounded-lg bg-[#315DA8] px-3 py-2 text-xs font-medium text-white disabled:opacity-50">보내기</button></div></form>
    </section>
  );
}

function QuizPanel({
  api,
  document,
  quiz,
  learning,
  onLearningUpdated,
  onGenerate,
  onCitation,
}: {
  api: MnemosyneApi;
  document: MnemosyneDocument;
  quiz: MnemosyneQuiz | null;
  learning: MnemosyneLearningState | null;
  onLearningUpdated: () => void;
  onGenerate: () => void;
  onCitation: (citation: VerifiedCitation) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [assessment, setAssessment] = useState<MnemosyneAssessment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { setAnswers({}); setAssessment(null); setError(""); }, [quiz?.quiz_id]);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!quiz || !learning) { setError("최신 학습 상태를 불러온 뒤 제출할 수 있습니다."); return; }
    const response = quiz.questions.map((question) => ({ question_id: question.question_id, answer: (answers[question.question_id] ?? "").trim() }));
    if (response.some((answer) => !answer.answer)) { setError("모든 문항에 답한 뒤 제출해 주세요."); return; }
    setBusy(true);
    setError("");
    setAssessment(null);
    try {
      const result = await api.submitAttempt(quiz.quiz_id, {
        attempt_id: newUUID(),
        client_mutation_id: newUUID(),
        quiz_id: quiz.quiz_id,
        document_id: document.document_id,
        version_id: document.version_id,
        base_learning_revision: learning.learning_revision,
        submitted_at: new Date().toISOString(),
        answers: response,
      });
      if (result.attempt_id.length === 0 || !result.citations.length) throw new Error("평가 응답에 검증된 근거가 없습니다.");
      setAssessment(result);
      onLearningUpdated();
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  };

  if (!quiz) return <div className="flex flex-1 flex-col justify-center p-6"><div className="mx-auto max-w-xs text-center"><div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-[#EDF3FC] text-[#315DA8]"><Check size={20} /></div><h2 className="mt-3 text-sm font-semibold">문서 근거 퀴즈</h2><p className="mt-2 text-xs leading-5 text-[#667085]">Tutor에서 퀴즈 기능을 선택해 생성하면, 문서 출처가 연결된 실제 문항을 여기에 표시합니다.</p><button type="button" onClick={onGenerate} className="mt-4 rounded-lg bg-[#315DA8] px-4 py-2.5 text-xs font-medium text-white">Tutor에서 퀴즈 만들기</button></div></div>;
  if (quiz.document_id !== document.document_id || quiz.version_id !== document.version_id) return <div className="m-4 rounded-lg border border-[#FDA29B] bg-[#FEF3F2] p-3 text-xs text-[#B42318]">다른 문서에서 생성된 퀴즈라 표시하지 않았습니다.</div>;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div className="mb-4"><p className="text-[10px] font-semibold uppercase tracking-wide text-[#667085]">실제 문서 퀴즈</p><h2 className="mt-1 text-base font-semibold">{quiz.title}</h2><p className="mt-1 text-xs text-[#667085]">문항 {quiz.questions.length}개 · 제출 전 정답은 표시하지 않습니다.</p></div>
      {assessment ? <div className="rounded-xl border border-[#B7E4C7] bg-[#ECFDF3] p-4"><div className="text-xs font-semibold text-[#027A48]">서버 평가 완료</div><div className="mt-1 text-2xl font-semibold text-[#1F2937]">{Math.round(assessment.score * 100)}%</div><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#344054]">{assessment.feedback_ko}</p><div className="mt-3 flex flex-wrap gap-2">{assessment.citations.map((citation) => <button type="button" key={citation.citation_id} onClick={() => onCitation(citation)} className="rounded-full border border-[#A6F4C5] bg-white px-2.5 py-1 text-xs text-[#027A48]">p. {citation.anchor.page_index + 1} · 근거 보기</button>)}</div><button type="button" onClick={() => { setAssessment(null); setAnswers({}); }} className="mt-4 rounded-lg border border-[#98A2B3] bg-white px-3 py-2 text-xs font-medium">다시 풀기</button></div> : <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {quiz.questions.map((question, index) => <fieldset key={question.question_id} className="rounded-xl border border-[#EAECF0] p-3"><legend className="px-1 text-xs font-semibold">{index + 1}. {question.prompt}</legend>{question.kind === "single_choice" ? <div className="mt-2 space-y-2">{question.choices.map((choice) => <label key={choice.choice_id} className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-xs hover:bg-[#F8FAFC]"><input type="radio" name={question.question_id} value={choice.choice_id} checked={answers[question.question_id] === choice.choice_id} onChange={() => setAnswers((current) => ({ ...current, [question.question_id]: choice.choice_id }))} className="mt-0.5 accent-[#315DA8]" /><span>{choice.text}</span></label>)}</div> : <textarea value={answers[question.question_id] ?? ""} onChange={(event) => setAnswers((current) => ({ ...current, [question.question_id]: event.target.value }))} rows={3} maxLength={10000} placeholder="답을 적어주세요" className="mt-2 w-full rounded-lg border border-[#D0D5DD] p-2 text-xs outline-none focus:border-[#315DA8]" />}
          <div className="mt-3 flex flex-wrap gap-1.5">{question.citations.map((citation) => <span key={citation.citation_id} className="rounded-full bg-[#F2F4F7] px-2 py-1 text-[10px] text-[#475467]">p. {citation.anchor.page_index + 1} 근거</span>)}</div>
        </fieldset>)}
        {!learning && <p className="rounded-lg bg-[#FFFAEB] p-3 text-xs text-[#7A2E0E]">최신 학습 revision을 불러오지 못해 제출을 막았습니다. 문서 상태를 새로 고쳐 주세요.</p>}
        {error && <p role="alert" className="rounded-lg bg-[#FEF3F2] p-3 text-xs text-[#B42318]">{error}</p>}
        <button disabled={busy || !learning} className="w-full rounded-lg bg-[#315DA8] px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50">{busy ? "평가 저장 중…" : "답안 제출·평가"}</button>
      </form>}
      {error && assessment && <p role="alert" className="mt-3 rounded-lg bg-[#FEF3F2] p-3 text-xs text-[#B42318]">{error}</p>}
    </div>
  );
}

export function MnemosyneLearning() {
  const api = useMnemosyneApi();
  const [documents, setDocuments] = useState<MnemosyneDocument[]>([]);
  const [documentID, setDocumentID] = useState("");
  const [learning, setLearning] = useState<MnemosyneLearningState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyMemory, setBusyMemory] = useState("");
  const [revealedMemory, setRevealedMemory] = useState("");
  const [notice, setNotice] = useState("");
  const activeDocument = documents.find((item) => item.document_id === documentID) ?? null;

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await api.listDocuments();
      setDocuments(rows);
      setDocumentID((current) => rows.some((item) => item.document_id === current) ? current : rows[0]?.document_id ?? "");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setLoading(false); }
  }, [api]);

  useEffect(() => { void loadDocuments(); }, [loadDocuments]);

  useEffect(() => {
    if (!activeDocument) { setLearning(null); return; }
    let cancelled = false;
    setLoading(true);
    setError("");
    void api.learningState(activeDocument).then((state) => { if (!cancelled) setLearning(state); }).catch((caught) => { if (!cancelled) { setLearning(null); setError(errorMessage(caught)); } }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [api, activeDocument]);

  const reviewMemory = async (memoryID: string, grade: number) => {
    if (!activeDocument || !learning) return;
    setBusyMemory(memoryID);
    setError("");
    setNotice("");
    try {
      const updated = await api.reviewMemory(memoryID, { client_mutation_id: newUUID(), memory_id: memoryID, base_learning_revision: learning.learning_revision, grade, reviewed_at: new Date().toISOString() });
      if (!sameDocumentVersion(updated, activeDocument)) throw new Error("다른 문서의 복습 응답을 거부했습니다.");
      setLearning(updated);
      setRevealedMemory("");
      setNotice("복습 결과를 서버에 저장했습니다.");
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusyMemory(""); }
  };

  const showCitation = async (citation: VerifiedCitation) => {
    if (!activeDocument) return;
    try {
      const verified = await api.verifyCitation(citation.anchor, activeDocument);
      if (!sameDocumentVersion(verified.anchor, activeDocument)) throw new Error("현재 문서가 아닌 근거를 거부했습니다.");
      window.location.href = `/learning/reading/${encodeURIComponent(activeDocument.document_id)}?page_index=${verified.anchor.page_index}`;
    } catch (caught) { setError(errorMessage(caught)); }
  };

  const pagesRead = learning?.progress.pages_read.length ?? 0;
  const progressPercent = activeDocument && activeDocument.page_count > 0 ? Math.min(100, Math.round((pagesRead / activeDocument.page_count) * 100)) : null;
  const dueMemory = learning?.memory.filter((memory) => Date.parse(memory.due_at) <= Date.now()) ?? [];

  return (
    <div className="min-h-screen bg-[#F5F6F8] text-[#1F2937]"><MnemosyneNav active="learning" />
      <main className="mx-auto max-w-[1320px] px-5 py-8 lg:px-8">
        <div className="flex flex-wrap items-end justify-between gap-4"><div><h1 className="text-2xl font-semibold tracking-tight">학습 기록·복습</h1><p className="mt-2 text-sm text-[#667085]">서버에 저장된 읽기, 평가, 숙련도와 기억 카드를 확인합니다.</p></div><label className="relative"><span className="sr-only">학습 문서 선택</span><select value={documentID} onChange={(event) => { setDocumentID(event.target.value); setRevealedMemory(""); }} className="min-w-[240px] appearance-none rounded-lg border border-[#D0D5DD] bg-white px-3 py-2.5 pr-9 text-sm"><option value="">문서 선택</option>{documents.map((item) => <option key={item.document_id} value={item.document_id}>{item.title}</option>)}</select><ChevronDown size={15} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[#667085]" /></label></div>
        {notice && <p role="status" className="mt-5 rounded-lg border border-[#B7E4C7] bg-[#ECFDF3] px-4 py-3 text-sm text-[#027A48]">{notice}</p>}
        {error && <div className="mt-5"><ErrorPanel error={error} onRetry={() => { if (activeDocument) { void api.learningState(activeDocument).then(setLearning).catch(setError); } else void loadDocuments(); }} api={api} /></div>}
        {loading && <div className="mt-6 flex items-center justify-center gap-2 rounded-2xl border border-[#EAECF0] bg-white py-14 text-sm text-[#667085]"><LoaderCircle size={16} className="animate-spin" />학습 기록을 불러오는 중</div>}
        {!loading && !activeDocument && !error && <div className="mt-6 rounded-2xl border border-dashed border-[#D0D5DD] bg-white py-16 text-center"><BookOpen size={26} className="mx-auto text-[#98A2B3]" /><h2 className="mt-3 text-sm font-semibold">학습할 문서가 없습니다</h2><p className="mt-1 text-xs text-[#667085]">라이브러리에 PDF를 올리면 실제 학습 상태가 여기에 나타납니다.</p><Link href="/learning/reading" className="mt-4 inline-block rounded-lg bg-[#315DA8] px-4 py-2 text-xs font-medium text-white no-underline">라이브러리 열기</Link></div>}
        {!loading && activeDocument && learning && <>
          <section className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <article className="rounded-2xl border border-[#EAECF0] bg-white p-4"><div className="text-xs text-[#667085]">읽은 물리 페이지</div><div className="mt-2 text-2xl font-semibold">{pagesRead}<span className="ml-1 text-sm font-normal text-[#667085]">/ {activeDocument.page_count}</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-[#EAECF0]"><div className="h-full rounded-full bg-[#315DA8]" style={{ width: `${progressPercent ?? 0}%` }} /></div><div className="mt-2 text-[11px] text-[#667085]">{progressPercent === null ? "진도 정보 없음" : `서버 진도 ${progressPercent}%`} · 마지막 p. {learning.progress.last_page_index + 1}</div></article>
            <article className="rounded-2xl border border-[#EAECF0] bg-white p-4"><div className="text-xs text-[#667085]">누적 읽기 시간</div><div className="mt-2 text-2xl font-semibold">{Math.floor(learning.progress.reading_seconds / 60)}<span className="ml-1 text-sm font-normal text-[#667085]">분</span></div><div className="mt-2 text-[11px] text-[#667085]">학습 revision {learning.learning_revision}</div></article>
            <article className="rounded-2xl border border-[#EAECF0] bg-white p-4"><div className="text-xs text-[#667085]">퀴즈 응시</div><div className="mt-2 text-2xl font-semibold">{learning.quiz_attempts.length}<span className="ml-1 text-sm font-normal text-[#667085]">회</span></div><div className="mt-2 text-[11px] text-[#667085]">실제 제출 기록</div></article>
            <article className="rounded-2xl border border-[#EAECF0] bg-white p-4"><div className="text-xs text-[#667085]">복습 예정</div><div className="mt-2 text-2xl font-semibold">{dueMemory.length}<span className="ml-1 text-sm font-normal text-[#667085]">장</span></div><div className="mt-2 text-[11px] text-[#667085]">{new Date(learning.progress.next_review_at).toLocaleString("ko-KR")}</div></article>
          </section>
          <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <section className="rounded-2xl border border-[#EAECF0] bg-white p-5"><div className="flex items-center justify-between"><div><h2 className="text-sm font-semibold">숙련도</h2><p className="mt-1 text-xs text-[#667085]">서버 평가 근거와 연결된 실제 점수입니다.</p></div><Link href={`/learning/reading/${encodeURIComponent(activeDocument.document_id)}?capability=mastery`} className="rounded-lg border border-[#D0D5DD] px-3 py-2 text-xs font-medium text-[#315DA8] no-underline">Tutor 학습</Link></div>
              {learning.mastery.length === 0 ? <p className="mt-6 rounded-lg bg-[#F8FAFC] p-4 text-xs text-[#667085]">저장된 숙련도 기록이 없습니다. 문서 Reader의 튜터에서 숙련도 학습을 시작할 수 있습니다.</p> : <div className="mt-4 space-y-3">{learning.mastery.map((item) => <div key={item.concept_id} className="rounded-xl border border-[#EAECF0] p-3"><div className="flex items-center justify-between gap-3"><span className="text-sm font-medium">{item.label_ko}</span><span className="text-xs font-semibold tabular-nums">{Math.round(item.score * 100)}%</span></div><div className="mt-2 h-1.5 rounded-full bg-[#EAECF0]"><div className="h-full rounded-full bg-[#78A1DF]" style={{ width: `${Math.round(item.score * 100)}%` }} /></div><p className="mt-2 text-[10px] text-[#667085]">평가 시도 {item.evidence_attempt_ids.length}회</p></div>)}</div>}
            </section>
            <section className="rounded-2xl border border-[#EAECF0] bg-white p-5"><div className="flex items-center justify-between"><div><h2 className="text-sm font-semibold">복습 카드</h2><p className="mt-1 text-xs text-[#667085]">카드를 확인한 뒤 기억 정도를 기록합니다.</p></div><span className="rounded-full bg-[#FFFAEB] px-2.5 py-1 text-[11px] text-[#B54708]">예정 {dueMemory.length}</span></div>
              {learning.memory.length === 0 ? <p className="mt-6 rounded-lg bg-[#F8FAFC] p-4 text-xs text-[#667085]">서버에 저장된 기억 카드가 없습니다. 학습 준비가 되면 실제 생성된 카드만 표시됩니다.</p> : <div className="mt-4 space-y-3">{learning.memory.map((memory) => <article key={memory.memory_id} className="rounded-xl border border-[#EAECF0] p-3"><div className="flex items-start justify-between gap-3"><div><div className="text-xs font-semibold">{memory.front_ko}</div><p className="mt-1 text-[10px] text-[#667085]">복습 {memory.review_count}회 · 예정 {new Date(memory.due_at).toLocaleDateString("ko-KR")}</p></div><button type="button" onClick={() => setRevealedMemory(revealedMemory === memory.memory_id ? "" : memory.memory_id)} className="shrink-0 rounded-lg border border-[#D0D5DD] px-2.5 py-1.5 text-[11px]">{revealedMemory === memory.memory_id ? "답 숨기기" : "답 확인"}</button></div>
                  {revealedMemory === memory.memory_id && <><div className="mt-3 rounded-lg bg-[#F8FAFC] p-3 text-xs leading-5 text-[#475467]">{memory.back_ko}</div><div className="mt-2 flex flex-wrap gap-1.5">{memory.citations.map((citation) => <button key={citation.citation_id} type="button" onClick={() => void showCitation(citation)} className="rounded-full border border-[#D0D5DD] px-2 py-1 text-[10px] text-[#315DA8]">p. {citation.anchor.page_index + 1} · 근거 보기</button>)}</div><div className="mt-3 flex items-center gap-1.5"><span className="mr-1 text-[10px] text-[#667085]">기억 평가</span>{[0, 1, 2, 3].map((grade) => <button key={grade} type="button" onClick={() => void reviewMemory(memory.memory_id, grade)} disabled={busyMemory !== ""} aria-label={`기억 평가 ${grade}`} className="rounded-lg border border-[#D0D5DD] px-3 py-2 text-xs font-medium hover:border-[#315DA8] disabled:opacity-40">{grade}</button>)}{busyMemory === memory.memory_id && <LoaderCircle size={14} className="animate-spin text-[#667085]" />}</div></>}
                </article>)}</div>}
            </section>
          </div>
          <section className="mt-4 grid gap-4 xl:grid-cols-2">
            <div className="rounded-2xl border border-[#EAECF0] bg-white p-5"><div className="flex items-center justify-between"><h2 className="text-sm font-semibold">퀴즈·평가 기록</h2><Link href={`/learning/reading/${encodeURIComponent(activeDocument.document_id)}?capability=quiz`} className="text-xs font-medium text-[#315DA8] no-underline">새 퀴즈 만들기</Link></div>{learning.quiz_attempts.length === 0 ? <p className="mt-4 text-xs text-[#667085]">저장된 퀴즈 응시가 없습니다.</p> : <div className="mt-3 divide-y divide-[#F2F4F7]">{learning.quiz_attempts.map((attempt) => <Link key={attempt.attempt_id} href={`/learning/reading/${encodeURIComponent(activeDocument.document_id)}?quiz_id=${encodeURIComponent(attempt.quiz_id)}`} className="flex items-center justify-between py-3 text-xs no-underline"><span className="text-[#475467]">응시 {attempt.attempt_id.slice(0, 8)}</span><span className="font-semibold text-[#1F2937]">{Math.round(attempt.score * 100)}%</span></Link>)}</div>}</div>
            <div className="rounded-2xl border border-[#EAECF0] bg-white p-5"><h2 className="text-sm font-semibold">학습 활동</h2>{learning.activities.length === 0 ? <p className="mt-4 text-xs text-[#667085]">저장된 활동 기록이 없습니다.</p> : <div className="mt-3 max-h-[320px] divide-y divide-[#F2F4F7] overflow-y-auto">{learning.activities.map((activity) => <div key={activity.activity_id} className="py-3"><div className="flex items-center justify-between gap-3"><span className="text-xs font-medium">{activity.summary_ko || activity.kind}</span><time className="shrink-0 text-[10px] text-[#667085]">{new Date(activity.created_at).toLocaleString("ko-KR")}</time></div><div className="mt-1 text-[10px] text-[#667085]">{activity.kind}{activity.turn_id ? ` · ${activity.turn_id}` : ""}</div></div>)}</div>}</div>
          </section>
        </>}
      </main>
    </div>
  );
}

const MNEMOSYNE_MODEL_PURPOSES = [
  { id: "mnemosyne_chat", label: "일반 대화", detail: "문서에 한정되지 않은 학습 질문에 답합니다." },
  { id: "mnemosyne_reading", label: "문서 읽기", detail: "선택한 문장과 문서 근거를 설명합니다." },
  { id: "mnemosyne_quiz", label: "퀴즈 만들기", detail: "현재 학습 자료에서 연습 문제를 만듭니다." },
  { id: "mnemosyne_assessment", label: "답안 평가", detail: "제출한 답을 평가하고 피드백을 작성합니다." },
  { id: "mnemosyne_mastery", label: "숙련도 학습", detail: "개념별 학습 목표와 숙련도 점검을 돕습니다." },
  { id: "mnemosyne_solve", label: "심화 풀이", detail: "여러 단계의 문서 기반 문제를 풀이합니다." },
] as const;

type MnemosynePurposeID = (typeof MNEMOSYNE_MODEL_PURPOSES)[number]["id"];
type PurposeSaveNotice = { purpose: string; kind: "success" | "error" } | null;

function MnemosynePurposeModelSettings() {
  const {
    catalog,
    taskKinds,
    catalogEditable,
    settingsLoading,
    settingsError,
    reloadSettings,
    saveRegistry,
    applying,
  } = useSettings();
  const [savingPurpose, setSavingPurpose] = useState<MnemosynePurposeID | "">("");
  const [notice, setNotice] = useState<PurposeSaveNotice>(null);

  const purposes = MNEMOSYNE_MODEL_PURPOSES.filter((purpose) =>
    taskKinds.some((kind) => kind.id === purpose.id),
  );
  const modelRows = flattenModels(catalog, ["llm", "task"]).filter(
    (row) => Boolean(row.model?.model?.trim()),
  );

  const valueFor = (purposeID: MnemosynePurposeID): string => {
    const choice = catalog.services.task.overrides?.[purposeID];
    if (!choice || choice.mode === "inherit") return "inherit";
    if (choice.mode === "reference" && choice.selection?.profile_id && choice.selection.model_id) {
      return `llm:${choice.selection.profile_id}:${choice.selection.model_id}`;
    }
    if (choice.mode === "profiles" && choice.active_profile_id && choice.active_model_id) {
      return `task:${choice.active_profile_id}:${choice.active_model_id}`;
    }
    return "inherit";
  };

  const savePurpose = async (purposeID: MnemosynePurposeID, value: string) => {
    let task: NonNullable<RegistryEdit["task"]>;
    if (value === "inherit") {
      task = { task_kind: purposeID, mode: "inherit" };
    } else {
      const row = modelRows.find((item) => item.key === value);
      if (!row?.model) {
        setNotice({ purpose: "선택한 모델을 현재 catalog에서 찾지 못했습니다.", kind: "error" });
        return;
      }
      task = row.service === "llm"
        ? {
            task_kind: purposeID,
            mode: "reference",
            selection: { profile_id: row.profile.id, model_id: row.model.id },
          }
        : {
            task_kind: purposeID,
            mode: "profiles",
            active_profile_id: row.profile.id,
            active_model_id: row.model.id,
          };
    }

    setSavingPurpose(purposeID);
    setNotice(null);
    try {
      const saved = await saveRegistry({ kind: "task_choice", task });
      setNotice(saved
        ? { purpose: `${MNEMOSYNE_MODEL_PURPOSES.find((item) => item.id === purposeID)?.label ?? "목적별 모델"} 설정을 서버가 저장했습니다.`, kind: "success" }
        : { purpose: "서버가 저장을 확인하지 않았습니다. 설정은 변경되지 않았습니다.", kind: "error" });
    } catch {
      setNotice({ purpose: "서버가 저장을 확인하지 않았습니다. 설정은 변경되지 않았습니다.", kind: "error" });
    } finally {
      setSavingPurpose("");
    }
  };

  return (
    <section className="mt-4 rounded-2xl border border-[#EAECF0] bg-white p-5">
      <div>
        <h2 className="text-sm font-semibold">학습 목적별 모델</h2>
        <p className="mt-1 text-xs leading-5 text-[#667085]">목적마다 모델을 지정할 수 있습니다. 기본값인 현재 대화 모델을 사용하면 해당 대화의 모델 설정을 따릅니다.</p>
      </div>
      {settingsError && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg bg-[#FEF3F2] p-3 text-xs text-[#B42318]"><span role="alert">모델 catalog를 불러오지 못했습니다. {settingsError}</span><button type="button" onClick={() => void reloadSettings()} className="underline">다시 불러오기</button></div>}
      {settingsLoading && <p role="status" className="mt-4 text-xs text-[#667085]">모델 설정을 불러오는 중…</p>}
      {!settingsLoading && catalogEditable === false && <p className="mt-4 rounded-lg bg-[#FFFAEB] p-3 text-xs leading-5 text-[#7A2E0E]">현재 계정에는 목적별 모델을 관리할 권한이 없습니다.</p>}
      {!settingsLoading && catalogEditable === true && purposes.length === 0 && <p role="status" className="mt-4 rounded-lg bg-[#FFFAEB] p-3 text-xs leading-5 text-[#7A2E0E]">서버 설정에서 Mnemosyne 학습 목적 목록을 확인할 수 없습니다.</p>}
      {!settingsLoading && catalogEditable === true && purposes.length > 0 && <div className="mt-4 divide-y divide-[#F2F4F7]">
        {purposes.map((purpose) => {
          const selected = valueFor(purpose.id);
          const selectedAvailable = selected === "inherit" || modelRows.some((row) => row.key === selected);
          return <label key={purpose.id} className="grid gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_minmax(16rem,0.9fr)] sm:items-center">
            <span><span className="block text-xs font-semibold text-[#344054]">{purpose.label}</span><span className="mt-1 block text-[11px] leading-5 text-[#667085]">{purpose.detail}</span></span>
            <select aria-label={`${purpose.label} 모델`} value={selected} disabled={applying || savingPurpose !== ""} onChange={(event) => void savePurpose(purpose.id, event.target.value)} className="w-full rounded-lg border border-[#D0D5DD] bg-white px-3 py-2 text-xs outline-none focus:border-[#315DA8] disabled:opacity-60">
              <option value="inherit">현재 대화 모델 사용</option>
              {!selectedAvailable && <option value={selected} disabled>저장된 모델을 사용할 수 없음 · 다시 선택</option>}
              {modelRows.map((row) => <option key={row.key} value={row.key}>{row.model!.name || row.model!.model} · {modelProvider(catalog, row.service, row.profile, row.model)?.name || "제공자 정보 없음"}</option>)}
            </select>
          </label>;
        })}
      </div>}
      {!settingsLoading && catalogEditable === true && modelRows.length === 0 && <p className="mt-3 text-[11px] leading-5 text-[#667085]">사용 가능한 catalog 모델이 없습니다. 현재 대화 모델 사용은 계속 선택할 수 있습니다.</p>}
      {savingPurpose && <p role="status" className="mt-3 text-xs text-[#667085]">선택한 모델을 서버에 저장 중…</p>}
      {notice && <p role={notice.kind === "error" ? "alert" : "status"} className={`mt-3 rounded-lg px-3 py-2 text-xs ${notice.kind === "error" ? "bg-[#FEF3F2] text-[#B42318]" : "bg-[#ECFDF3] text-[#027A48]"}`}>{notice.purpose}</p>}
    </section>
  );
}

function MnemosyneSettingsContent() {
  const api = useMnemosyneApi();
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [readinessError, setReadinessError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [baseURL, setBaseURL] = useState("");
  const [model, setModel] = useState("");
  const [responseLanguage, setResponseLanguage] = useState("ko");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setReadinessError("");
    try {
      try {
        const serverSettings = await api.publicSettings();
        setSettings(serverSettings);
        setBaseURL(serverSettings.provider.base_url);
        setModel(serverSettings.provider.model);
        setResponseLanguage(serverSettings.response_language);
      } catch (caught) { setError(caught); }
      try {
        setReadiness(await api.readiness());
      } catch (caught) {
        setReadiness(null);
        setReadinessError(errorMessage(caught));
      }
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!settings) return;
    setSaving(true);
    setError(null);
    setNotice("");
    try {
      const provider: PublicSettings["provider"] & { api_key?: string } = { adapter: "openai-compatible", base_url: baseURL.trim(), model: model.trim(), credential_configured: settings.provider.credential_configured };
      if (apiKey.trim()) provider.api_key = apiKey;
      const saved = await api.updateSettings({ provider: { adapter: provider.adapter, base_url: provider.base_url, model: provider.model, ...(provider.api_key ? { api_key: provider.api_key } : {}) }, response_language: responseLanguage.trim() || "ko" }, settings.server_revision);
      setSettings(saved);
      setBaseURL(saved.provider.base_url);
      setModel(saved.provider.model);
      setResponseLanguage(saved.response_language);
      setApiKey("");
      setNotice("서버가 설정 저장을 확인했습니다. API 키 값은 다시 표시하지 않습니다.");
    } catch (caught) { setError(caught); }
    finally { setSaving(false); }
  };

  const revoke = async () => {
    if (!window.confirm("이 브라우저의 서버 페어링을 폐기할까요?")) return;
    setNotice("");
    try {
      const result = await api.revokeSession();
      if (!result.revoked) throw new Error("서버가 세션 폐기를 확인하지 않았습니다.");
      setNotice("이 브라우저의 서버 세션을 폐기했습니다.");
      setSettings(null);
      setReadiness(null);
    } catch (caught) { setError(caught); }
  };

  return (
    <div className="min-h-screen bg-[#F5F6F8] text-[#1F2937]"><MnemosyneNav active="settings" />
      <main className="mx-auto max-w-[1000px] px-5 py-8 lg:px-8">
        <div><h1 className="text-2xl font-semibold tracking-tight">서버·모델 설정</h1><p className="mt-2 text-sm text-[#667085]">자격증명은 서버에 전송해 저장하며, 조회할 때는 설정 여부만 표시합니다.</p></div>
        {notice && <p role="status" className="mt-5 rounded-lg border border-[#B7E4C7] bg-[#ECFDF3] px-4 py-3 text-sm text-[#027A48]">{notice}</p>}
        {error !== null && <div className="mt-5"><ErrorPanel error={error} onRetry={() => void load()} api={api} /></div>}
        {loading && <div className="mt-6 flex items-center justify-center gap-2 rounded-2xl border border-[#EAECF0] bg-white py-14 text-sm text-[#667085]"><LoaderCircle size={16} className="animate-spin" />서버 설정을 불러오는 중</div>}
        {!loading && settings && <>
          <section className="mt-6 rounded-2xl border border-[#EAECF0] bg-white p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold">서버 준비 상태</h2><p className="mt-1 text-xs text-[#667085]">연결 주소 {api.baseURL.origin} · 계약 {MNEMOSYNE_CONTRACT_VERSION}</p></div><ReadinessLine readiness={readiness} checking={loading} /></div>{readinessError && <p role="status" className="mt-3 text-xs leading-5 text-[#7A2E0E]">서버 준비 정보를 확인하지 못했습니다. {readinessError}</p>}{readiness && <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">{Object.entries(readiness.components).map(([name, status]) => <div key={name} className="rounded-lg bg-[#F8FAFC] px-3 py-2"><div className="text-[10px] uppercase text-[#667085]">{name}</div><div className={`mt-1 text-xs font-medium ${status === "ready" ? "text-[#027A48]" : status === "failed" ? "text-[#B42318]" : "text-[#B54708]"}`}>{status}</div></div>)}</div>}
            <p className="mt-3 text-xs text-[#667085]">준비된 기능: {readiness?.capabilities.join(" · ") || "확인할 수 없음"}</p><button type="button" onClick={() => void revoke()} className="mt-4 rounded-lg border border-[#D0D5DD] px-3 py-2 text-xs text-[#B42318]">이 브라우저 페어링 폐기</button>
          </section>
          <form onSubmit={(event) => void save(event)} className="mt-4 rounded-2xl border border-[#EAECF0] bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-sm font-semibold">OpenAI-compatible 모델</h2><p className="mt-1 text-xs text-[#667085]">모델 선택과 기본 응답 언어를 서버 설정에 저장합니다.</p></div><span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${settings.provider.credential_configured ? "bg-[#ECFDF3] text-[#027A48]" : "bg-[#FFFAEB] text-[#B54708]"}`}>{settings.provider.credential_configured ? "API 키 설정됨" : "API 키 미설정"}</span></div>
            <div className="mt-5 grid gap-4 md:grid-cols-2"><label className="text-xs font-medium text-[#475467]">Provider base URL<input type="url" required value={baseURL} onChange={(event) => setBaseURL(event.target.value)} className="mt-1.5 block w-full rounded-lg border border-[#D0D5DD] px-3 py-2.5 text-sm font-normal outline-none focus:border-[#315DA8]" placeholder="https://api.example.com/v1" /></label><label className="text-xs font-medium text-[#475467]">모델 ID<input required value={model} onChange={(event) => setModel(event.target.value)} className="mt-1.5 block w-full rounded-lg border border-[#D0D5DD] px-3 py-2.5 text-sm font-normal outline-none focus:border-[#315DA8]" placeholder="모델 이름" /></label><label className="text-xs font-medium text-[#475467]">기본 응답 언어<input required value={responseLanguage} onChange={(event) => setResponseLanguage(event.target.value)} pattern="^(und|[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)$" className="mt-1.5 block w-full rounded-lg border border-[#D0D5DD] px-3 py-2.5 text-sm font-normal outline-none focus:border-[#315DA8]" /></label><label className="text-xs font-medium text-[#475467]">API 키<input type="password" autoComplete="new-password" spellCheck={false} value={apiKey} onChange={(event) => setApiKey(event.target.value)} className="mt-1.5 block w-full rounded-lg border border-[#D0D5DD] px-3 py-2.5 text-sm font-normal outline-none focus:border-[#315DA8]" placeholder={settings.provider.credential_configured ? "변경할 때만 입력" : "서버에 저장할 키"} /><span className="mt-1 block text-[10px] font-normal text-[#667085]">입력값은 브라우저 저장소에 쓰지 않으며, 저장 후 화면에서 지웁니다. 조회 결과는 설정 여부만 사용합니다.</span></label></div>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[#F2F4F7] pt-4"><span className="text-[11px] text-[#667085]">설정 revision {settings.server_revision} · 충돌 시 최신 설정을 다시 불러와야 합니다.</span><button disabled={saving} className="rounded-lg bg-[#315DA8] px-4 py-2.5 text-xs font-semibold text-white disabled:opacity-50">{saving ? "서버에 저장 중…" : "설정 저장"}</button></div>
          </form>
          <MnemosynePurposeModelSettings />
          <section className="mt-4 rounded-2xl border border-[#EAECF0] bg-white p-5"><h2 className="text-sm font-semibold">문서 언어와 응답 언어</h2><p className="mt-2 text-xs leading-5 text-[#667085]">문서 언어는 PDF마다 서버 분석 결과로 보관합니다. 위 응답 언어는 새 Tutor 요청 기본값입니다. 인용문·수식·코드는 원문을 유지합니다.</p></section>
        </>}
        {!loading && !settings && !error && <div className="mt-5 rounded-2xl border border-[#EAECF0] bg-white p-5"><h2 className="text-sm font-semibold">개인 서버 페어링</h2><p className="mt-1 text-xs text-[#667085]">서버의 일회용 코드를 사용해 이 브라우저를 연결하세요.</p><PairingPanel api={api} onPaired={load} /></div>}
      </main>
    </div>
  );
}

export function MnemosyneSettings() {
  return <SettingsProvider><MnemosyneSettingsContent /></SettingsProvider>;
}
