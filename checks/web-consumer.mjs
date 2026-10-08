// Common fixture plus source-owned native WebSocket adapter probe.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {consumeNativeFrame} from '../upstreams/DeepTutor/web/features/mnemosyne/register.ts';

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

// Compare canonical transforms to the actual upstream PDF.js viewport.
// Requires the existing web npm ci; no new viewer or dependency is introduced.
const {getDocument}=await import('../upstreams/DeepTutor/web/node_modules/pdfjs-dist/legacy/build/pdf.mjs');
const pdfTask=getDocument({data:new Uint8Array(read(`contracts/fixtures/${fixture.original_file}`)),useSystemFonts:false,disableFontFace:true});
const pdf=await pdfTask.promise;
for(const page of fixture.pages) {
  const native=await pdf.getPage(page.page_index+1);
  assert.deepEqual(native.view,page.geometry.crop_box);
  assert.equal(native.rotate,page.geometry.rotation_degrees);
  const point=[native.view[0]+32,native.view[1]+50];
  const viewport=native.getViewport({scale:1.25,offsetX:7,offsetY:13});
  assert.deepEqual(viewport.convertToViewportPoint(...point),toViewport(point,page.geometry,1.25,[7,13]));
  assert.deepEqual(viewport.convertToPdfPoint(...toViewport(point,page.geometry,1.25,[7,13])),point);
}
await pdfTask.destroy();

// Every native frame advances the cursor. The semantic subset may contain gaps.
for(const key of ['events','cancelled_events','error_events']) {
  const frames=fixture.wire[key];
  const decoded=[];
  frames.forEach((frame,index)=>{
    assert.equal(frame.seq,index+1);
    const event=consumeNativeFrame(frame);
    if(event)decoded.push(event);
  });
  assert.deepEqual(decoded,fixture[key]);
}
const invalid=structuredClone(fixture.wire.events.at(-1));
invalid.metadata.status='failed';
assert.throws(()=>consumeNativeFrame(invalid),/Terminal status/);

// Simulate resume checkpoint and dedup without claiming browser durable storage.
const checkpoint={lastSeq:Number(fixture.reconnect.last_event_id.split(':').at(-1)),approvedAnnotationEvents:[]};
const dispatched=[];
for(const e of [fixture.reconnect.duplicate_delivery,...fixture.reconnect.replayed_events]) {
  if(e.seq<=checkpoint.lastSeq)continue;
  assert.ok(e.seq>checkpoint.lastSeq);
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
console.log(JSON.stringify({result:'PASS',consumer:'web-node-fixture',geometryCases:fixture.geometry_cases.length,pdfjsPages:fixture.pages.length,events:fixture.events.length,nativeFrames:fixture.wire.events.length,actualBrowserVerified:false}));
