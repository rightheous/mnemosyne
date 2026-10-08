// Fixture-only consumer; UNIT-05 must adapt the actual web runtime after source audit.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = p => fs.readFileSync(path.join(root, p));
const fixture = JSON.parse(read('contracts/fixtures/study-session.json'));
const api = JSON.parse(read('contracts/openapi.yaml'));
assert.equal(fixture.contract_version, api.info.version);
assert.equal(crypto.createHash('sha256').update(read(`contracts/fixtures/${fixture.original_file}`)).digest('hex'), fixture.document.source_sha256);
const scalarSlice = (text, start, end) => Array.from(text).slice(start, end).join('');
assert.equal(scalarSlice(fixture.unicode_probe.text, fixture.unicode_probe.start_scalar, fixture.unicode_probe.end_scalar), fixture.unicode_probe.quote);
assert.notEqual(fixture.unicode_probe.text.slice(fixture.unicode_probe.start_scalar, fixture.unicode_probe.end_scalar), fixture.unicode_probe.quote);
for (const citation of fixture.citations) {
  const anchor = citation.anchor;
  const page = fixture.pages[anchor.page_index];
  assert.equal(anchor.version_id, page.version_id);
  assert.equal(scalarSlice(page.text, anchor.start_scalar, anchor.end_scalar), anchor.quote);
  assert.deepEqual(anchor.rects, page.segments.map(s => s.rect));
}

function toViewport([x,y], g, scale, [ox,oy]) {
  const [x0,y0,x1,y1] = g.crop_box;
  const u=x-x0, v=y-y0, w=x1-x0, h=y1-y0;
  let X,Y;
  switch(g.rotation_degrees) {
    case 0: [X,Y]=[u,h-v]; break;
    case 90: [X,Y]=[v,u]; break;
    case 180: [X,Y]=[w-u,v]; break;
    case 270: [X,Y]=[h-v,w-u]; break;
    default: throw new Error('Unsupported rotation');
  }
  return [ox+X*g.user_unit*scale, oy+Y*g.user_unit*scale];
}
function fromViewport([x,y],g,scale,[ox,oy]) {
  const [x0,y0,x1,y1]=g.crop_box, w=x1-x0, h=y1-y0;
  const X=(x-ox)/(g.user_unit*scale), Y=(y-oy)/(g.user_unit*scale);
  let u,v;
  switch(g.rotation_degrees) {
    case 0:[u,v]=[X,h-Y];break;
    case 90:[u,v]=[Y,X];break;
    case 180:[u,v]=[w-X,Y];break;
    case 270:[u,v]=[w-Y,h-X];break;
  }
  return [u+x0,v+y0];
}
for(const c of fixture.geometry_cases) {
  const p=toViewport(c.point_pdf,c.geometry,c.scale,c.offset);
  assert.deepEqual(p,c.expected_viewport);
  assert.deepEqual(fromViewport(p,c.geometry,c.scale,c.offset),c.point_pdf);
}
for(const page of fixture.pages) {
  const [x,y,w,h]=page.segments[0].rect;
  const corners=[[x,y],[x+w,y],[x,y+h],[x+w,y+h]].map(p=>toViewport(p,page.geometry,1,[0,0]));
  const xs=corners.map(p=>p[0]),ys=corners.map(p=>p[1]);
  const transformed=[Math.min(...xs),Math.min(...ys),Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys)];
  assert.ok(transformed[2]>0 && transformed[3]>0);
  assert.ok(Math.abs(transformed[2]-(page.geometry.rotation_degrees===90 ? h:w))<1e-8);
}

// Incremental decoder keeps UTF-8 Korean intact even when a byte chunk splits a glyph.
class FixtureSSEDecoder {
  decoder=new TextDecoder('utf-8',{fatal:true}); buffer=''; events=[];
  push(bytes,final=false) {
    this.buffer+=this.decoder.decode(bytes,{stream:!final});
    for(;;) {
      const boundary=/\r?\n\r?\n/.exec(this.buffer);
      if(!boundary)break;
      const frame=this.buffer.slice(0,boundary.index);
      this.buffer=this.buffer.slice(boundary.index+boundary[0].length);
      let id,type;const data=[];
      for(const line of frame.split(/\r?\n/)) {
        if(line.startsWith(':'))continue;
        const sep=line.indexOf(':'); if(sep<0)continue;
        const key=line.slice(0,sep),value=line.slice(sep+1).replace(/^ /,'');
        if(key==='id')id=value;
        else if(key==='event')type=value;
        else if(key==='data')data.push(value);
      }
      if(!data.length)continue;
      const event=JSON.parse(data.join('\n'));
      assert.equal(id,event.event_id);assert.equal(type,event.type);
      this.events.push(event);
    }
  }
}
for(const wire of [read('contracts/fixtures/tutor.sse'),Buffer.from(read('contracts/fixtures/tutor.sse').toString().replaceAll('\n','\r\n'))]) {
  const stream=new FixtureSSEDecoder();
  for(let i=0;i<wire.length;i+=7)stream.push(wire.subarray(i,i+7));
  stream.push(new Uint8Array(),true);
  assert.deepEqual(stream.events,fixture.events);
}

// Simulate resume checkpoint and dedup without claiming browser durable storage.
const checkpoint={lastSeq:5,approvedAnnotationEvents:[]};
const dispatched=[];
for(const e of [fixture.reconnect.duplicate_delivery,...fixture.reconnect.replayed_events]) {
  if(e.seq<=checkpoint.lastSeq)continue;
  assert.equal(e.seq,checkpoint.lastSeq+1);
  checkpoint.lastSeq=e.seq;dispatched.push(e.type);
  if(e.type==='reader.annotate') {
    assert.equal(e.payload.requires_confirmation,true);
    // Presentation of a proposal does not create an annotation.
    assert.equal(checkpoint.approvedAnnotationEvents.length,0);
  }
  if(e.type==='reader.highlight'||e.type==='reader.flash')assert.equal(e.payload.persistent,false);
}
assert.equal(checkpoint.lastSeq,fixture.events.at(-1).seq);
assert.equal(dispatched.filter(x=>x==='reader.annotate').length,1);
assert.equal(fixture.attempt.answers[0].question_id,fixture.quiz.questions[0].question_id);
assert.equal(fixture.learning_state.quiz_attempts[0].attempt_id,fixture.attempt.attempt_id);
assert.equal(fixture.assessment.learning_revision,fixture.learning_state.learning_revision);
assert.deepEqual(new Set(fixture.annotation_snapshot.annotations.map(a=>a.kind)),new Set(['highlight','note','bookmark','ink']));
console.log(JSON.stringify({result:'PASS',consumer:'web-node-fixture',geometryCases:fixture.geometry_cases.length,events:fixture.events.length,sseChunkBytes:7,wireVariants:2,actualBrowserVerified:false}));
