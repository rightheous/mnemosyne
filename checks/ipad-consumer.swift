// Codable/geometry fixture probe only. It does not import Pumice, PDFKit or UIKit.
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
struct Event: Decodable {let event_id:String; let turn_id:UUID; let seq:Int; let type:EventType; let payload:EventPayload}
struct GeometryCase: Decodable {let name:String; let geometry:Geometry; let point_pdf:[Double]; let scale:Double; let offset:[Double]; let expected_viewport:[Double]}
struct UnicodeProbe: Decodable {let text:String; let start_scalar:Int; let end_scalar:Int; let quote:String}
struct Question: Decodable {let question_id:UUID; let prompt:String; let citations:[Citation]}
struct Quiz: Decodable {let quiz_id:UUID; let questions:[Question]}
struct Answer: Decodable {let question_id:UUID; let answer:String}
struct Attempt: Decodable {let attempt_id:UUID; let quiz_id:UUID; let answers:[Answer]}
struct SavedAttempt: Decodable {let attempt_id:UUID; let quiz_id:UUID; let score:Double}
struct Learning: Decodable {let learning_revision:Int; let quiz_attempts:[SavedAttempt]}
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
func transform(_ p:[Double],_ g:Geometry,_ scale:Double,_ offset:[Double],inverse:Bool=false)->[Double] {
    let x0=g.crop_box[0],y0=g.crop_box[1],w=g.crop_box[2]-x0,h=g.crop_box[3]-y0,f=g.user_unit*scale
    if inverse {
        let X=(p[0]-offset[0])/f,Y=(p[1]-offset[1])/f
        let u:Double,v:Double
        switch g.rotation_degrees {
        case 0:(u,v)=(X,h-Y)
        case 90:(u,v)=(Y,X)
        case 180:(u,v)=(w-X,Y)
        case 270:(u,v)=(w-Y,h-X)
        default: fatalError("Invalid fixture rotation")
        }
        return [u+x0,v+y0]
    }
    let u=p[0]-x0,v=p[1]-y0
    let X:Double,Y:Double
    switch g.rotation_degrees {
    case 0:(X,Y)=(u,h-v)
    case 90:(X,Y)=(v,u)
    case 180:(X,Y)=(w-u,v)
    case 270:(X,Y)=(h-v,w-u)
    default:fatalError("Invalid fixture rotation")
    }
    return [offset[0]+X*f,offset[1]+Y*f]
}

do {
    let source=URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent()
    let data=try Data(contentsOf:source.appendingPathComponent("contracts/fixtures/study-session.json"))
    let f=try JSONDecoder().decode(Fixture.self,from:data)
    try check(f.contract_version=="0.1.0-draft.1","Contract mismatch")
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
        for (index,event) in stream.enumerated() {
            try check(!terminal && event.seq==index+1,"Event sequence/terminal")
            try check(event.event_id==event.turn_id.uuidString.lowercased()+":"+String(event.seq),"Event ID")
            if event.type == .annotate {try check(event.payload.requires_confirmation==true,"Annotation proposal")}
            if event.type == .highlight || event.type == .flash {try check(event.payload.persistent==false && (event.payload.ttl_ms ?? 0)>0,"Temporary Reader effect")}
            terminal = [.done,.cancelled,.error].contains(event.type)
        }
        try check(terminal,"Missing terminal")
    }
    var lastSeq=5,proposalCount=0
    for event in [f.reconnect.duplicate_delivery]+f.reconnect.replayed_events {
        if event.seq<=lastSeq {continue}
        try check(event.seq==lastSeq+1,"Resume gap")
        lastSeq=event.seq
        if event.type == .annotate {proposalCount+=1}
    }
    try check(lastSeq==f.events.count && proposalCount==1,"Resume dedup")
    try check(f.attempt.quiz_id==f.quiz.quiz_id && f.attempt.answers[0].question_id==f.quiz.questions[0].question_id,"Quiz relation")
    try check(f.learning_state.quiz_attempts[0].attempt_id==f.attempt.attempt_id,"Saved attempt")
    print("{\"result\":\"PASS\",\"consumer\":\"ipad-swift-codable-fixture\",\"geometryCases\":\(f.geometry_cases.count),\"events\":\(f.events.count),\"actualDeviceVerified\":false}")
} catch {
    fputs("FAIL: \(error)\n",stderr)
    exit(1)
}
