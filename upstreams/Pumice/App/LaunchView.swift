import SwiftUI
import UniformTypeIdentifiers

struct LaunchView: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "book.pages.fill")
                .font(.system(size: 46, weight: .medium))
                .foregroundStyle(Color(red: 49 / 255, green: 93 / 255, blue: 168 / 255))
                .padding(20)
                .background(Color.white, in: RoundedRectangle(cornerRadius: 18))
            Text("므네모시네")
                .font(.system(size: 30, weight: .bold, design: .rounded))
            Text("문서와 함께하는 개인 학습 공간")
                .font(.subheadline).foregroundStyle(.secondary)
            ProgressView().padding(.top, 8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 245 / 255, green: 246 / 255, blue: 248 / 255).ignoresSafeArea())
    }
}

struct MnemosyneRootView: View {
    @StateObject private var model: MnemosyneAppModel

    init(model: MnemosyneAppModel = MnemosyneAppModel()) {
        _model = StateObject(wrappedValue: model)
    }

    var body: some View {
        NavigationSplitView {
            List {
                Section("공부 공간") {
                    ForEach(MnemosyneSection.allCases) { section in
                        Button {
                            model.selectedSection = section
                        } label: {
                            Label(section.title, systemImage: icon(for: section))
                                .foregroundStyle(model.selectedSection == section ? Color.mnemosyneAccent : Color.primary)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
                Section("연결") {
                    Label(model.connectionSummary,
                          systemImage: model.connectionState == .online ? "checkmark.circle.fill" : "network")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .accessibilityLabel("서버 상태: \(model.connectionSummary)")
                }
                Section("필기 동기화") {
                    Label(model.syncSummary,
                          systemImage: model.syncConflictedMutationIds.isEmpty
                            ? "arrow.triangle.2.circlepath" : "exclamationmark.triangle.fill")
                        .font(.footnote)
                        .foregroundStyle(model.syncConflictedMutationIds.isEmpty ? Color.secondary : Color.orange)
                    if !model.syncConflictedMutationIds.isEmpty {
                        Text("충돌한 변경 \(model.syncConflictedMutationIds.count)건은 보존했습니다. Reader의 충돌 검토 기능이 연결되면 확인할 수 있습니다.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("므네모시네")
            .navigationSplitViewColumnWidth(min: 220, ideal: 260)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { Task { await model.synchronizeNow() } } label: {
                        Label("동기화", systemImage: "arrow.triangle.2.circlepath")
                    }
                    .disabled(!model.isPaired || model.busyMessage != nil)
                }
            }
        } detail: {
            Group {
                switch model.selectedSection {
                case .library: MnemosyneLibraryView()
                case .study: MnemosyneStudyView()
                case .settings: MnemosyneSettingsView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.mnemosyneCanvas)
        }
        .tint(.mnemosyneAccent)
        .environmentObject(model)
        .task { await model.connectSavedServer() }
        .overlay(alignment: .top) {
            if let message = model.busyMessage {
                HStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text(message).font(.footnote.weight(.medium))
                }
                .padding(.horizontal, 16).padding(.vertical, 10)
                .background(.regularMaterial, in: Capsule())
                .padding(.top, 8)
                .accessibilityLiveRegion(.polite)
            }
        }
        .alert("므네모시네", isPresented: Binding(
            get: { model.alertMessage != nil },
            set: { if !$0 { model.dismissAlert() } }
        )) {
            Button("확인", role: .cancel) { model.dismissAlert() }
        } message: {
            Text(model.alertMessage ?? "")
        }
        .alert("주석 제안", isPresented: Binding(
            get: { model.pendingAnnotationEvent != nil },
            set: { if !$0 { model.rejectPendingAnnotation() } }
        )) {
            Button("취소", role: .cancel) { model.rejectPendingAnnotation() }
            Button("주석 저장") { model.approvePendingAnnotation() }
        } message: {
            Text("튜터가 문서에 영구 주석을 제안했습니다. 저장하면 이 기기의 outbox에 추가됩니다.")
        }
        .sheet(item: Binding(get: { model.activeQuiz }, set: { if $0 == nil { model.dismissQuiz() } })) { quiz in
            MnemosyneQuizView(quiz: quiz)
                .environmentObject(model)
                .presentationDetents([.medium, .large])
        }
    }

    private func icon(for section: MnemosyneSection) -> String {
        switch section {
        case .library: "books.vertical"
        case .study: "chart.bar.xaxis"
        case .settings: "gearshape"
        }
    }
}

private struct MnemosyneLibraryView: View {
    @EnvironmentObject private var model: MnemosyneAppModel
    @State private var showImporter = false
    @State private var showSubjectPrompt = false
    @State private var subjectName = ""
    @State private var pendingDelete: MnemosyneDocument?
    @State private var showDeleteConfirmation = false

    var body: some View {
        VStack(spacing: 0) {
            header
            subjectPicker
            GeometryReader { geometry in
                if geometry.size.width >= 760 {
                    HStack(spacing: 0) {
                        documentList.frame(width: min(340, geometry.size.width * 0.4))
                        Divider()
                        documentWorkspace
                    }
                } else {
                    VStack(spacing: 0) {
                        documentList.frame(maxHeight: min(240, geometry.size.height * 0.32))
                        Divider()
                        documentWorkspace
                    }
                }
            }
        }
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.pdf], allowsMultipleSelection: false) { result in
            switch result {
            case let .success(urls):
                if let url = urls.first { Task { await model.uploadPDF(from: url) } }
            case let .failure(error): model.presentError(error.localizedDescription)
            }
        }
        .alert("과목 추가", isPresented: $showSubjectPrompt) {
            TextField("과목 이름", text: $subjectName)
            Button("취소", role: .cancel) { subjectName = "" }
            Button("추가") {
                let name = subjectName
                subjectName = ""
                Task { await model.createSubject(name: name) }
            }
        } message: { Text("문서를 정리할 과목을 만듭니다.") }
        .confirmationDialog("문서를 삭제할까요?", isPresented: $showDeleteConfirmation, presenting: pendingDelete) { document in
            Button("삭제", role: .destructive) { Task { await model.deleteDocument(document) } }
            Button("취소", role: .cancel) {}
        } message: { document in
            Text("\(document.title)을(를) 서버에서 삭제합니다. 확인된 문서만 삭제됩니다.")
        }
        .task { if model.isPaired { await model.refreshLibraryFromUI() } }
    }

    private var header: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                Text("라이브러리").font(.largeTitle.bold())
                Text("원본 PDF와 문서 분석 상태").font(.subheadline).foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)
            Button { showSubjectPrompt = true } label: {
                Label("과목 추가", systemImage: "folder.badge.plus")
            }
            .buttonStyle(.bordered)
            .disabled(!model.isPaired)
            Button { showImporter = true } label: {
                Label("PDF 가져오기", systemImage: "square.and.arrow.down")
            }
            .buttonStyle(.borderedProminent)
            .disabled(!model.isPaired)
        }
        .padding(.horizontal, 20).padding(.top, 20).padding(.bottom, 14)
    }

    private var subjectPicker: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                subjectChip("전체", id: nil)
                ForEach(model.subjects) { subject in subjectChip(subject.name, id: subject.subjectId) }
            }
            .padding(.horizontal, 20).padding(.vertical, 10)
        }
        .overlay(alignment: .bottom) { Divider() }
    }

    private func subjectChip(_ title: String, id: UUID?) -> some View {
        let selected = model.selectedSubjectId == id
        return Button(title) { Task { await model.selectSubject(id) } }
            .buttonStyle(.bordered)
            .tint(selected ? .mnemosyneAccent : .secondary)
            .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private var documentList: some View {
        Group {
            if !model.isPaired {
                ContentUnavailableView("서버에 연결해 주세요", systemImage: "network", description: Text("서버 설정에서 주소를 입력하고 이 iPad를 pairing하세요."))
            } else if model.documents.isEmpty {
                ContentUnavailableView("문서가 없습니다", systemImage: "doc.text", description: Text("PDF를 가져오면 서버가 분석 상태를 표시합니다."))
            } else {
                List(selection: $model.selectedDocumentId) {
                    ForEach(model.documents) { document in
                        Button {
                            model.selectedDocumentId = document.documentId
                        } label: {
                            MnemosyneDocumentRow(document: document,
                                localState: model.downloadStates[document.documentId])
                        }
                        .buttonStyle(.plain)
                        .contextMenu {
                            Button(role: .destructive) {
                                pendingDelete = document
                                showDeleteConfirmation = true
                            } label: { Label("삭제", systemImage: "trash") }
                        }
                        .tag(document.documentId)
                    }
                }
                .listStyle(.plain)
                .refreshable { await model.refreshLibraryFromUI() }
            }
        }
        .background(Color.white)
    }

    @ViewBuilder
    private var documentWorkspace: some View {
        if let document = model.selectedDocument {
            MnemosyneDocumentWorkspace(document: document)
        } else {
            ContentUnavailableView("문서를 선택하세요", systemImage: "doc.text.magnifyingglass",
                                   description: Text("읽기와 튜터가 같은 문서 context를 사용합니다."))
        }
    }
}

private struct MnemosyneDocumentRow: View {
    let document: MnemosyneDocument
    let localState: String?

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "doc.richtext").font(.title3).foregroundStyle(.mnemosyneAccent)
            VStack(alignment: .leading, spacing: 5) {
                Text(document.title).font(.body.weight(.semibold)).lineLimit(2)
                HStack(spacing: 8) {
                    Label(document.parseState.label, systemImage: document.parseState.icon)
                    Text("·")
                    Text(document.indexState == .ready ? "튜터 준비 완료" : "튜터 분석 \(document.indexState.label)")
                }
                .font(.caption).foregroundStyle(.secondary)
                if let localState {
                    Label(localState, systemImage: localState == "기기에 저장됨" ? "checkmark.circle" : "arrow.down.circle")
                        .font(.caption2).foregroundStyle(localState == "기기에 저장됨" ? Color.green : Color.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 8)
        .contentShape(Rectangle())
    }
}

private struct MnemosyneDocumentWorkspace: View {
    @EnvironmentObject private var model: MnemosyneAppModel
    let document: MnemosyneDocument
    @State private var tutorExpanded = true
    @State private var tutorPrompt = ""

    var body: some View {
        GeometryReader { geometry in
            if geometry.size.width >= 980 {
                HStack(spacing: 0) {
                    readerPane.frame(maxWidth: .infinity, maxHeight: .infinity)
                    Divider()
                    tutorPane.frame(width: min(380, geometry.size.width * 0.38))
                }
            } else {
                VStack(spacing: 0) {
                    readerPane.frame(maxWidth: .infinity, maxHeight: .infinity)
                    Divider()
                    tutorPane.frame(height: tutorExpanded ? max(220, geometry.size.height * 0.38) : 58)
                }
            }
        }
        .background(Color.mnemosyneCanvas)
    }

    private var readerPane: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(document.title).font(.headline).lineLimit(1)
                    Text("\(document.pageCount)페이지 · 원본 \(document.sourceSha256.prefix(12))…")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { Task { await model.openDocument(document) } } label: {
                    Label("PDF 열기", systemImage: "book")
                }
                .buttonStyle(.borderedProminent)
                .disabled(!model.hasReaderFacade || !document.originalAvailable || model.busyMessage != nil)
                Menu {
                    Button("문서 학습 기록") { model.selectedSection = .study; Task { await model.refreshLearning() } }
                } label: { Image(systemName: "ellipsis.circle") }
                .accessibilityLabel("문서 동작")
            }

            if !document.isTutorReady {
                readinessNotice
            }

            if !model.hasReaderFacade {
                ContentUnavailableView("문서를 열 수 없습니다", systemImage: "doc.text.viewfinder",
                    description: Text(model.readerSetupMessage ?? "이 기기에서 문서 읽기를 사용할 수 없습니다. 다시 실행해 주세요."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(.white, in: RoundedRectangle(cornerRadius: 12))
            } else if model.activeReaderDocumentID == document.documentId,
                      model.activeReaderVersionID == document.versionId,
                      let url = model.activeReaderURL,
                      let controller = model.readerController,
                      let engine = model.readerEngine {
                VStack(spacing: 0) {
                    HStack(spacing: 12) {
                        Text("검증된 원본 · 로컬 sidecar 필기")
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        Button { model.undoReader() } label: { Label("되돌리기", systemImage: "arrow.uturn.backward") }
                        Button { model.redoReader() } label: { Label("다시 실행", systemImage: "arrow.uturn.forward") }
                        Button("닫기") { model.closeReader() }
                    }
                    .buttonStyle(.borderless)
                    .padding(.horizontal, 10).padding(.vertical, 8)
                    Divider()
                    PDFReaderView(pdfURL: url, controller: controller,
                                  onPageChanged: { index in model.readerPageChanged(index) },
                                  mnemosyneEngine: engine)
                        .onAppear { Task { await model.readerViewDidAppear(for: document) } }
                        .onDisappear { model.readerViewDidDisappear() }
                        .background(.white)
                }
                .clipShape(RoundedRectangle(cornerRadius: 12))
            } else {
                ContentUnavailableView("PDF를 열어 주세요", systemImage: "book.pages",
                    description: Text("서버 원본의 전체 SHA-256을 확인한 뒤 기기에 보관합니다. 오프라인에서도 저장된 원본을 열 수 있습니다."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(.white, in: RoundedRectangle(cornerRadius: 12))
            }
        }
        .padding(16)
        .background(Color.mnemosyneCanvas)
    }

    private var readinessNotice: some View {
        Label("읽기 가능 · 튜터 준비 \(document.indexState.label)", systemImage: "info.circle")
            .font(.footnote).foregroundStyle(.secondary)
            .padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.white, in: RoundedRectangle(cornerRadius: 8))
    }

    private var tutorPane: some View {
        VStack(spacing: 0) {
            Button { withAnimation(.easeInOut(duration: 0.2)) { tutorExpanded.toggle() } } label: {
                HStack {
                    Image(systemName: "sparkles").foregroundStyle(.mnemosyneAccent)
                    Text("문서 튜터").font(.headline)
                    Spacer()
                    Text(model.tutorStatus).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                    Image(systemName: tutorExpanded ? "chevron.down" : "chevron.up").font(.caption.weight(.bold))
                }
                .padding(.horizontal, 16).frame(height: 56)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if tutorExpanded {
                Divider()
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        if model.tutorText.isEmpty {
                            Text("현재 페이지, 선택 문장, 하이라이트와 노트를 context로 보냅니다.")
                                .foregroundStyle(.secondary)
                            Label("한국어 답변 · 검증된 문서 근거", systemImage: "checkmark.seal")
                                .font(.footnote).foregroundStyle(.secondary)
                            if !document.isTutorReady {
                                Label("분석이 완료되면 문서 튜터를 사용할 수 있습니다.", systemImage: "hourglass")
                                    .font(.footnote).foregroundStyle(.orange)
                            }
                            if !model.hasReaderFacade {
                                Label("Reader context 연결을 기다리는 중입니다.", systemImage: "link.badge.plus")
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        } else {
                            Text(model.tutorText).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                        }
                        if !model.tutorCitations.isEmpty {
                            VStack(alignment: .leading, spacing: 10) {
                                Text("검증된 문서 근거")
                                    .font(.subheadline.weight(.semibold))
                                ForEach(model.tutorCitations, id: \.citationId) { citation in
                                    VStack(alignment: .leading, spacing: 5) {
                                        Label("원문 p. \(citation.anchor.pageIndex + 1)",
                                              systemImage: "checkmark.seal.fill")
                                            .font(.caption.weight(.semibold))
                                            .foregroundStyle(.mnemosyneAccent)
                                        Text(citation.anchor.quote)
                                            .font(.callout)
                                            .textSelection(.enabled)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                    .padding(11)
                                    .background(Color.mnemosyneCanvas, in: RoundedRectangle(cornerRadius: 9))
                                }
                            }
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(.white, in: RoundedRectangle(cornerRadius: 12))
                        }
                        if let assessment = model.lastAssessment {
                            Label("서버 평가 \(Int(assessment.score * 100))%", systemImage: "checkmark.seal.fill")
                                .font(.footnote.weight(.semibold))
                            Text(assessment.feedbackKo).font(.callout)
                        }
                    }
                    .padding(16)
                }
                Spacer(minLength: 0)
                if model.canResumeTutor(for: document) {
                    Button {
                        model.resumeTutor(for: document)
                    } label: {
                        Label("이전 튜터 응답 이어보기", systemImage: "arrow.clockwise")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .padding(.horizontal, 12).padding(.top, 10)
                } else if model.hasUnfinishedTutorTurn && !model.isTutorRunning {
                    Label("다른 문서의 튜터 응답을 먼저 이어받아 주세요.", systemImage: "arrow.uturn.backward")
                        .font(.footnote).foregroundStyle(.orange)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 12).padding(.top, 10)
                }
                HStack(alignment: .bottom, spacing: 9) {
                    TextField("문서에 관해 질문하기", text: $tutorPrompt, axis: .vertical)
                        .lineLimit(1...4)
                        .textFieldStyle(.roundedBorder)
                        .disabled(!document.isTutorReady || model.isTutorRunning || model.hasUnfinishedTutorTurn ||
                                  model.activeReaderDocumentID != document.documentId ||
                                  model.activeReaderVersionID != document.versionId)
                        .accessibilityLabel("문서 튜터 질문")
                    Button {
                        Task { await model.askTutor(message: tutorPrompt) }
                    } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.title)
                            .foregroundStyle(Color.mnemosyneAccent)
                    }
                    .buttonStyle(.plain)
                    .disabled(tutorPrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                              !document.isTutorReady || model.isTutorRunning || model.hasUnfinishedTutorTurn ||
                              model.activeReaderDocumentID != document.documentId ||
                              model.activeReaderVersionID != document.versionId)
                    .accessibilityLabel("튜터에게 질문 보내기")
                    Button {
                        Task { await model.generateQuiz(prompt: tutorPrompt) }
                    } label: {
                        Image(systemName: "questionmark.square")
                            .font(.title3)
                            .foregroundStyle(Color.mnemosyneAccent)
                    }
                    .buttonStyle(.plain)
                    .disabled(tutorPrompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                              document.parseState != .ready || model.busyMessage != nil ||
                              model.activeReaderDocumentID != document.documentId ||
                              model.activeReaderVersionID != document.versionId)
                    .accessibilityLabel("현재 페이지 퀴즈 만들기")
                    if model.isTutorRunning {
                        Button("취소") { Task { await model.cancelTutor() } }
                    }
                }
                .padding(12).background(Color.white)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
    }
}

private struct MnemosyneStudyView: View {
    @EnvironmentObject private var model: MnemosyneAppModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 5) {
                    Text("학습 기록").font(.largeTitle.bold())
                    Text(model.selectedDocument?.title ?? "문서의 숙련도와 복습을 확인합니다")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                if let state = model.learningState {
                    progressCard(state)
                    if !state.mastery.isEmpty {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("숙련도").font(.title2.bold())
                            ForEach(state.mastery) { mastery in
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack { Text(mastery.labelKo); Spacer(); Text("\(Int(mastery.score * 100))%") }
                                        .font(.subheadline)
                                    ProgressView(value: mastery.score).tint(.mnemosyneAccent)
                                    Text("근거 시도 \(mastery.evidenceAttemptIds.count)회")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                        .mnemosyneCard()
                    }
                    if !state.memory.isEmpty { memorySection(state) }
                    if !state.activities.isEmpty {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("최근 활동").font(.title2.bold())
                            ForEach(state.activities.reversed()) { activity in
                                HStack(alignment: .top, spacing: 10) {
                                    Image(systemName: "clock.arrow.circlepath").foregroundStyle(.secondary)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(activity.summaryKo)
                                        Text("\(activity.kind) · \(activity.createdAt)")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                        .mnemosyneCard()
                    }
                } else {
                    ContentUnavailableView("서버 학습 기록이 없습니다", systemImage: "chart.bar.xaxis",
                        description: Text(model.selectedDocument == nil
                            ? "먼저 라이브러리에서 문서를 선택하세요."
                            : "서버에서 저장된 진도, 숙련도, 기억 카드와 복습 정보를 불러옵니다."))
                        .frame(minHeight: 260)
                }
            }
            .padding(24).frame(maxWidth: 1000, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .task { await model.refreshLearning() }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { Task { await model.refreshLearning() } } label: {
                    Label("새로 고침", systemImage: "arrow.clockwise")
                }
                .disabled(model.selectedDocument == nil)
            }
        }
    }

    private func progressCard(_ state: MnemosyneLearningState) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("진도", systemImage: "book.closed")
                Spacer()
                Text("학습 revision \(state.learningRevision)").font(.caption).foregroundStyle(.secondary)
            }
            Text("마지막 위치 p. \(state.progress.lastPageIndex + 1)")
            Text("읽은 페이지 \(state.progress.pagesRead.count) · 학습 시간 \(state.progress.readingSeconds / 60)분")
                .font(.footnote).foregroundStyle(.secondary)
            Text("다음 복습 · \(state.progress.nextReviewAt)")
                .font(.footnote).foregroundStyle(.secondary)
            Text("퀴즈 시도 \(state.quizAttempts.count)회")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .mnemosyneCard()
    }

    private func memorySection(_ state: MnemosyneLearningState) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("기억 카드 · 복습").font(.title2.bold())
            ForEach(state.memory) { memory in MnemosyneMemoryCard(memory: memory) }
        }
        .mnemosyneCard()
    }
}

private struct MnemosyneMemoryCard: View {
    @EnvironmentObject private var model: MnemosyneAppModel
    let memory: MnemosyneLearningState.Memory
    @State private var isRevealed = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(memory.frontKo).font(.headline)
            if isRevealed { Text(memory.backKo).font(.body).textSelection(.enabled) }
            else {
                Button("정답 보기") { isRevealed = true }.buttonStyle(.bordered)
            }
            HStack {
                Text("복습 \(memory.reviewCount)회 · 마감 \(memory.dueAt)")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
            }
            if isRevealed {
                HStack {
                    ForEach(0...3, id: \.self) { grade in
                        Button(["다시", "어려움", "알겠음", "쉬움"][grade]) {
                            Task { await model.reviewMemory(memory, grade: grade); isRevealed = false }
                        }
                        .buttonStyle(.bordered)
                    }
                }
                .font(.caption)
            }
        }
        .padding(12).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.mnemosyneCanvas, in: RoundedRectangle(cornerRadius: 10))
    }
}

private struct MnemosyneSettingsView: View {
    @EnvironmentObject private var model: MnemosyneAppModel

    var body: some View {
        Form {
            Section("서버") {
                TextField("https://내-서버.example", text: $model.serverURLText)
                    .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    .accessibilityLabel("서버 주소")
                Text("HTTPS 주소 또는 사설 IPv4 네트워크 주소를 입력합니다. 계정 API 키는 iPad에 저장하지 않습니다.")
                    .font(.footnote).foregroundStyle(.secondary)
                Button { Task { await model.connectAndRefresh() } } label: {
                    Label("연결 확인", systemImage: "network")
                }
                .disabled(model.serverURLText.isEmpty || model.busyMessage != nil)
                Label(model.connectionSummary,
                      systemImage: model.connectionState == .online ? "checkmark.circle.fill" : "exclamationmark.circle")
                    .font(.subheadline)
                if let ready = model.serverReadyState {
                    Label(ready ? "서버 준비됨" : "서버 시작 중 또는 준비 실패",
                          systemImage: ready ? "checkmark.seal.fill" : "hourglass")
                        .font(.subheadline).foregroundStyle(ready ? Color.green : Color.orange)
                }
            }

            if model.connectionState == .online && !model.isPaired {
                Section("이 iPad 연결") {
                    TextField("서버에서 발급한 일회용 코드", text: $model.pairingCode)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .accessibilityLabel("일회용 pairing 코드")
                    TextField("기기 이름", text: $model.deviceName)
                    Button { Task { await model.pairDevice() } } label: {
                        Label("기기 연결", systemImage: "ipad.and.arrow.forward")
                    }
                    .disabled(model.pairingCode.count < 8 || model.busyMessage != nil)
                }
            }

            if model.isPaired {
                Section("서버 준비 상태") {
                    readinessRow("데이터베이스", model.readiness?.components.database)
                    readinessRow("원본 저장소", model.readiness?.components.storage)
                    readinessRow("문서 분석기", model.readiness?.components.parser)
                    readinessRow("검색 색인", model.readiness?.components.index)
                    readinessRow("Tutor 제공자", model.readiness?.components.provider)
                    if let readiness = model.readiness {
                        Text("상태: \(readiness.status.rawValue) · 스트림 재개 보장 \(readiness.eventResumeSeconds)초")
                            .font(.footnote).foregroundStyle(.secondary)
                        Text("준비된 기능: \(readiness.capabilities.map(\.rawValue).joined(separator: ", "))")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                    if let settings = model.publicSettings {
                        LabeledContent("Tutor 제공자", value: settings.provider.adapter)
                        LabeledContent("모델", value: settings.provider.model)
                        LabeledContent("서버 자격증명", value: settings.provider.credentialConfigured ? "서버에 설정됨" : "설정 필요")
                    }
                    Button("이 기기 연결 해제", role: .destructive) { Task { await model.unpairDevice() } }
                }
            }

            Section("앱 상태") {
                LabeledContent("PDF 읽기", value: model.hasReaderFacade ? "사용 가능" : "사용할 수 없음")
                LabeledContent("동기화", value: model.syncWorker == nil ? "연결 안 됨" : "연결됨")
                Text("문서 언어는 서버 감지 결과를 사용하고 튜터 답변 언어는 한국어가 기본입니다. 원문 인용, 수식, 코드는 그대로 표시합니다.")
                    .font(.footnote).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(maxWidth: 820).frame(maxWidth: .infinity, alignment: .center)
        .navigationTitle("서버 설정")
    }

    @ViewBuilder
    private func readinessRow(_ label: String, _ state: MnemosyneReadiness.ComponentState?) -> some View {
        HStack {
            Text(label)
            Spacer()
            if let state {
                Label(state.rawValue, systemImage: state == .ready ? "checkmark.circle.fill" : "clock")
                    .font(.subheadline).foregroundStyle(state == .ready ? Color.green : Color.secondary)
            } else { Text("확인 전").foregroundStyle(.secondary) }
        }
    }
}

private struct MnemosyneQuizView: View {
    @EnvironmentObject private var model: MnemosyneAppModel
    let quiz: MnemosyneQuiz
    @State private var answers: [UUID: String] = [:]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(quiz.title).font(.title2.bold())
                    ForEach(Array(quiz.questions.enumerated()), id: \.element.id) { index, question in
                        VStack(alignment: .leading, spacing: 10) {
                            Text("\(index + 1). \(question.prompt)").font(.headline)
                            if question.kind == "single_choice" {
                                ForEach(question.choices) { choice in
                                    Button {
                                        answers[question.questionId] = choice.choiceId
                                    } label: {
                                        HStack {
                                            Image(systemName: answers[question.questionId] == choice.choiceId
                                                  ? "largecircle.fill.circle" : "circle")
                                            Text(choice.text)
                                            Spacer()
                                        }
                                        .padding(10).background(Color.mnemosyneCanvas, in: RoundedRectangle(cornerRadius: 8))
                                    }
                                    .buttonStyle(.plain)
                                }
                            } else {
                                TextField("답변", text: Binding(
                                    get: { answers[question.questionId] ?? "" },
                                    set: { answers[question.questionId] = $0 }
                                ), axis: .vertical)
                                .lineLimit(2...6).textFieldStyle(.roundedBorder)
                            }
                            ForEach(question.citations, id: \.citationId) { citation in
                                Label("근거 · p. \(citation.anchor.pageIndex + 1) · \(citation.anchor.quote)",
                                      systemImage: "quote.opening")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .padding(14).background(.white, in: RoundedRectangle(cornerRadius: 12))
                    }
                    if let assessment = model.lastAssessment {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("서버 평가 · \(Int(assessment.score * 100))%").font(.headline)
                            Text(assessment.feedbackKo)
                        }
                        .mnemosyneCard()
                    }
                }
                .padding(20)
            }
            .background(Color.mnemosyneCanvas)
            .navigationTitle("퀴즈 · 평가")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("닫기") { model.dismissQuiz() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("서버에 제출") { Task { await model.submitQuizAnswers(answers) } }
                        .disabled(model.learningState == nil)
                }
            }
        }
        .task { if model.learningState == nil { await model.refreshLearning() } }
    }
}

private extension MnemosyneDocument.ParseState {
    var label: String {
        switch self {
        case .pending: "대기"
        case .running: "분석 중"
        case .ready: "읽기 가능"
        case .failed: "실패"
        }
    }
    var icon: String {
        switch self {
        case .pending: "clock"
        case .running: "arrow.triangle.2.circlepath"
        case .ready: "checkmark.circle"
        case .failed: "exclamationmark.triangle"
        }
    }
}

private extension MnemosyneDocument.IndexState {
    var label: String {
        switch self {
        case .pending: "대기"
        case .running: "분석 중"
        case .ready: "준비 완료"
        case .failed: "분석 실패"
        }
    }
}

private extension View {
    func mnemosyneCard() -> some View {
        self.padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(.white, in: RoundedRectangle(cornerRadius: 12))
    }
}

private extension Color {
    static let mnemosyneCanvas = Color(red: 245 / 255, green: 246 / 255, blue: 248 / 255)
    static let mnemosyneAccent = Color(red: 49 / 255, green: 93 / 255, blue: 168 / 255)
}
