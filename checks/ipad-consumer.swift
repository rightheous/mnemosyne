// Codable fixture and actual PumiceCore geometry/facade compilation probe.
// PDFKit/Pencil UI and physical iPad validation are separate checks.
import Foundation

struct Geometry: Decodable {
    let media_box: [Double]
    let crop_box: [Double]
    let rotation_degrees: Int
    let user_unit: Double
}
struct Document: Decodable {
    let document_id: UUID
    let version_id: String
    let source_sha256: String
    let content_language: String
    let page_count: Int
}
struct Anchor: Decodable {
    let document_id: UUID
    let version_id: String
    let page_index: Int
    let parse_revision: String
    let text_sha256: String
    let start_scalar: Int
    let end_scalar: Int
    let quote: String
    let rects: [[Double]]
}
struct Page: Decodable {
    let document_id: UUID
    let version_id: String
    let page_index: Int
    let display_page_number: Int
    let display_label: String
    let text: String
    let text_sha256: String
    let geometry: Geometry
}
struct Citation: Decodable {
    let citation_id: UUID
    let verification_id: UUID
    let verified: Bool
    let anchor: Anchor
}
struct StrokePoint: Decodable {let x:Double; let y:Double; let pressure:Double; let t_ms:Int}
struct Stroke: Decodable {let stroke_id:UUID; let tool:String; let color:String; let width_pt:Double; let points:[StrokePoint]}
enum AnnotationKind: String, Decodable {case highlight, note, bookmark, ink}
struct AnnotationPayload: Decodable {
    let anchor: Anchor?
    let color: String?
    let position: [Double]?
    let body: String?
    let label: String?
    let strokes: [Stroke]?
}
struct Annotation: Decodable {
    let annotation_id: UUID
    let document_id: UUID
    let version_id: String
    let page_index: Int
    let kind: AnnotationKind
    let server_revision: Int?
    let deleted: Bool?
    let payload: AnnotationPayload?
}
struct Snapshot: Decodable {let snapshot_revision:Int; let annotations:[Annotation]; let next_cursor:String}
struct Target: Decodable {let document_id:UUID; let version_id:String; let page_index:Int}
enum EventType: String, Decodable {
    case started="turn.started", delta="assistant.delta", citation="citation.verified"
    case goto="reader.goto", highlight="reader.highlight", flash="reader.flash", annotate="reader.annotate"
    case quiz="quiz.show", question="question.show", learning="learning.updated"
    case done="turn.done", error="turn.error", cancelled="turn.cancelled"
}
struct EventPayload: Decodable {
    let citation: Citation?
    let target: Target?
    let annotation: Annotation?
    let requires_confirmation: Bool?
    let suggested_mutation_id: UUID?
    let persistent: Bool?
    let ttl_ms: Int?
    let text: String?
    let quiz_id: UUID?
    let question_id: UUID?
}
struct Event: Decodable {let event_id:String; let turn_id:String; let seq:Int; let type:EventType; let payload:EventPayload}
struct GeometryCase: Decodable {let name:String; let geometry:Geometry; let point_pdf:[Double]; let scale:Double; let offset:[Double]; let expected_viewport:[Double]}
struct UnicodeProbe: Decodable {let text:String; let start_scalar:Int; let end_scalar:Int; let quote:String}
struct Question: Decodable {let question_id:UUID; let prompt:String; let citations:[Citation]}
struct Quiz: Decodable {let quiz_id:UUID; let questions:[Question]}
struct Answer: Decodable {let question_id:UUID; let answer:String}
struct Attempt: Decodable {let attempt_id:UUID; let quiz_id:UUID; let answers:[Answer]}
struct SavedAttempt: Decodable {let attempt_id:UUID; let quiz_id:UUID; let score:Double}
struct Learning: Decodable {let learning_revision:Int; let quiz_attempts:[SavedAttempt]}
struct ProgressMutation: Decodable {let client_mutation_id:UUID; let version_id:String; let base_learning_revision:Int; let page_index:Int; let reading_seconds:Int}
struct Reconnect: Decodable {let last_event_id:String; let replayed_events:[Event]; let duplicate_delivery:Event}
struct Fixture: Decodable {
    let contract_version:String
    let document:Document
    let pages:[Page]
    let citations:[Citation]
    let annotation_snapshot:Snapshot
    let events:[Event]
    let cancelled_events:[Event]
    let error_events:[Event]
    let geometry_cases:[GeometryCase]
    let unicode_probe:UnicodeProbe
    let quiz:Quiz
    let attempt:Attempt
    let learning_state:Learning
    let reconnect:Reconnect
}

enum CheckError: Error {case failed(String)}
func check(_ condition: Bool, _ message:String) throws {
    if !condition {throw CheckError.failed(message)}
}
func scalarSlice(_ text:String,_ start:Int,_ end:Int)->String {
    String(String.UnicodeScalarView(Array(text.unicodeScalars)[start..<end]))
}
func transform(_ p:[Double],_ g:Geometry,_ scale:Double,_ offset:[Double],inverse:Bool=false) -> [Double] {
    let box=g.crop_box
    let geometry=try! MnemosyneGeometry(cropBox:CGRect(x:box[0],y:box[1],width:box[2]-box[0],height:box[3]-box[1]),rotation:g.rotation_degrees,userUnit:g.user_unit)
    let point=CGPoint(x:p[0],y:p[1]), origin=CGPoint(x:offset[0],y:offset[1])
    let result=inverse ? geometry.pdfPoint(fromViewport:point,scale:scale,offset:origin) : geometry.viewportPoint(fromPDF:point,scale:scale,offset:origin)
    return [result.x,result.y]
}

@main struct FixtureMain {
static func main() {

do {
    let source=URL(fileURLWithPath:CommandLine.arguments.count>1 ? CommandLine.arguments[1] : FileManager.default.currentDirectoryPath)
    let data=try Data(contentsOf:source.appendingPathComponent("contracts/fixtures/study-session.json"))
    let progressData=try Data(contentsOf:source.appendingPathComponent("contracts/fixtures/progress-mutation.json"))
    let progress=try JSONDecoder().decode(ProgressMutation.self,from:progressData)
    let f=try JSONDecoder().decode(Fixture.self,from:data)
    let rootJSON=try JSONSerialization.jsonObject(with:data) as! [String:Any]
    let wire=rootJSON["wire"] as! [String:Any]
    for key in ["events","cancelled_events","error_events"] {
        let frames=wire[key] as! [[String:Any]]
        var extensions:[Event]=[]
        for (index,frame) in frames.enumerated() {
            let decoded=try decodeMnemosyneTurnFrame(JSONSerialization.data(withJSONObject:frame))
            try check(decoded.sequence==index+1,"Native sequence")
            if let semantic=decoded.semanticEvent {
                extensions.append(try JSONDecoder().decode(Event.self,from:semantic))
            }
        }
        let expected=key=="events" ? f.events : key=="cancelled_events" ? f.cancelled_events : f.error_events
        try check(extensions.map {$0.event_id}==expected.map {$0.event_id},"Native extension subset")
    }
    try check(f.contract_version=="0.2.0","Contract mismatch")
    try check(progress.version_id==f.document.version_id && progress.page_index < f.document.page_count && progress.reading_seconds <= 300,"Progress mutation contract")
    try check(f.document.page_count==f.pages.count,"Page count")
    for page in f.pages {try check(page.display_page_number==page.page_index+1,"Page base")}
    for c in f.citations {
        let a=c.anchor,p=f.pages[a.page_index]
        try check(c.verified && a.version_id==p.version_id,"Citation version")
        try check(scalarSlice(p.text,a.start_scalar,a.end_scalar)==a.quote,"Quote scalar range")
    }
    let probe=f.unicode_probe
    try check(scalarSlice(probe.text,probe.start_scalar,probe.end_scalar)==probe.quote,"Supplementary scalar")
    for c in f.geometry_cases {
        let actual=transform(c.point_pdf,c.geometry,c.scale,c.offset)
        try check(actual==c.expected_viewport,"Geometry forward \(c.name)")
        try check(transform(actual,c.geometry,c.scale,c.offset,inverse:true)==c.point_pdf,"Geometry inverse \(c.name)")
    }
    try check(Set(f.annotation_snapshot.annotations.map {$0.kind.rawValue})==Set(["ink","note","bookmark","highlight"]),"Annotation kinds")
    for annotation in f.annotation_snapshot.annotations where annotation.kind == .ink {
        try check(annotation.payload?.strokes?.first?.width_pt==2,"Physical pen width")
    }
    for stream in [f.events,f.cancelled_events,f.error_events] {
        try check(stream.first?.type == .started,"Stream start")
        var terminal=false
        var previousSeq=0
        for event in stream {
            try check(!terminal && event.seq>previousSeq,"Event sequence/terminal")
            previousSeq=event.seq
            try check(event.event_id==event.turn_id+":"+String(event.seq),"Event ID")
            if event.type == .annotate {try check(event.payload.requires_confirmation==true,"Annotation proposal")}
            if event.type == .highlight || event.type == .flash {try check(event.payload.persistent==false && (event.payload.ttl_ms ?? 0)>0,"Temporary Reader effect")}
            terminal = [.done,.cancelled,.error].contains(event.type)
        }
        try check(terminal,"Missing terminal")
    }
    var lastSeq=Int(f.reconnect.last_event_id.split(separator:":").last!)!,proposalCount=0
    for event in [f.reconnect.duplicate_delivery]+f.reconnect.replayed_events {
        if event.seq<=lastSeq {continue}
        try check(event.seq>lastSeq,"Resume gap")
        lastSeq=event.seq
        if event.type == .annotate {proposalCount+=1}
    }
    try check(lastSeq==f.events.last!.seq && proposalCount==1,"Resume dedup")
    try check(f.attempt.quiz_id==f.quiz.quiz_id && f.attempt.answers[0].question_id==f.quiz.questions[0].question_id,"Quiz relation")
    try check(f.learning_state.quiz_attempts[0].attempt_id==f.attempt.attempt_id,"Saved attempt")
    print("{\"result\":\"PASS\",\"consumer\":\"ipad-swift-codable-fixture\",\"geometryCases\":\(f.geometry_cases.count),\"events\":\(f.events.count),\"actualDeviceVerified\":false}")
} catch {
    fputs("FAIL: \(error)\n",stderr)
    exit(1)
}

}
}
