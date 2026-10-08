#!/usr/bin/env python3
"""Contract/fixture checks, not a backend or an upstream adapter."""
import argparse
import copy
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

try:
    import yaml
    from jsonschema import Draft202012Validator, FormatChecker
    from openapi_spec_validator import OpenAPIV31SpecValidator
    from referencing import Registry, Resource
except ImportError:
    raise SystemExit('Install checks/requirements.txt in a temporary virtual environment.')

ROOT = Path(__file__).resolve().parents[1]
C = ROOT / 'contracts'
V = '0.1.0-draft.1'
COUNTS = {'schema_instances': 0, 'negative_cases': 0, 'sync_steps': 0}

def read(path):
    def reject_constant(value):
        raise ValueError(f'Non-JSON constant: {value}')
    return json.loads(path.read_text(), parse_constant=reject_constant)

def ensure(condition, message):
    if not condition:
        raise ValueError(message)

def sha(value):
    return hashlib.sha256(value).hexdigest()

schema_files = ['models.schema.json', 'annotations.schema.json', 'events.schema.json']
registry = Registry()
for filename in schema_files:
    schema = read(C / filename)
    Draft202012Validator.check_schema(schema)
    ensure(schema['x-contract-version'] == V, 'Schema version differs')
    registry = registry.with_resource((C / filename).as_uri(), Resource.from_contents(schema))

def validate(filename, data, definition=None):
    target = (C / filename).as_uri() + (f'#/$defs/{definition}' if definition else '')
    Draft202012Validator({'$ref': target}, registry=registry, format_checker=FormatChecker()).validate(data)
    COUNTS['schema_instances'] += 1

def negative(name, callback):
    try:
        callback()
    except Exception as error:
        # Only intended validation classes count; programming defects must fail the run.
        from jsonschema.exceptions import ValidationError
        if not isinstance(error, (ValueError, ValidationError)):
            raise
        COUNTS['negative_cases'] += 1
        return
    raise ValueError(f'Invalid input accepted: {name}')

F = read(C / 'fixtures/study-session.json')
DOC = F['document']
PAGES = {page['page_index']: page for page in F['pages']}

def target_ok(target):
    ensure(target['document_id'] == DOC['document_id'], 'Wrong document')
    ensure(target['version_id'] == DOC['version_id'], 'Wrong version')
    ensure(target['page_index'] in PAGES, 'Wrong physical page')

def point_ok(point, page):
    x0, y0, x1, y1 = page['geometry']['crop_box']
    x, y = point
    ensure(all(math.isfinite(x) for x in point), 'Non-finite point')
    ensure(x0 <= x <= x1 and y0 <= y <= y1, 'Point outside CropBox')

def rect_ok(rect, page):
    x, y, w, h = rect
    ensure(w > 0 and h > 0, 'Invalid rect size')
    point_ok((x, y), page)
    point_ok((x + w, y + h), page)

def anchor_ok(anchor):
    target_ok(anchor)
    page = PAGES[anchor['page_index']]
    ensure(anchor['parse_revision'] == page['parse_revision'], 'Wrong parser revision')
    ensure(anchor['text_sha256'] == page['text_sha256'], 'Wrong text hash')
    start, end = anchor['start_scalar'], anchor['end_scalar']
    ensure(0 <= start < end <= len(page['text']), 'Invalid scalar range')
    ensure(page['text'][start:end] == anchor['quote'], 'Quote differs from parser text')
    matching = [s['rect'] for s in page['segments'] if s['start_scalar'] == start and s['end_scalar'] == end]
    # This small fixture selects whole segments. Real parser adapters must handle partial spans.
    ensure(anchor['rects'] == matching, 'Rects differ from matching fixture segments')
    for rect in anchor['rects']:
        rect_ok(rect, page)

def annotation_ok(annotation):
    target_ok(annotation)
    if annotation.get('deleted'):
        ensure(annotation['payload'] is None, 'Tombstone retains payload')
        return
    payload = annotation['payload']
    page = PAGES[annotation['page_index']]
    if annotation['kind'] == 'highlight':
        anchor_ok(payload['anchor'])
        ensure(payload['anchor']['page_index'] == annotation['page_index'], 'Highlight page differs')
    elif annotation['kind'] == 'note':
        point_ok(payload['position'], page)
        if payload['anchor'] is not None:
            anchor_ok(payload['anchor'])
            ensure(payload['anchor']['page_index'] == annotation['page_index'], 'Note anchor page differs')
    elif annotation['kind'] == 'ink':
        seen = set()
        for stroke in payload['strokes']:
            ensure(stroke['stroke_id'] not in seen, 'Duplicate stroke ID')
            seen.add(stroke['stroke_id'])
            last_time = -1
            for point in stroke['points']:
                point_ok((point['x'], point['y']), page)
                ensure(point['t_ms'] >= last_time, 'Stroke time reverses')
                last_time = point['t_ms']

def mutation_ok(mutation):
    ensure(mutation['document_id'] == DOC['document_id'] and mutation['version_id'] == DOC['version_id'], 'Mutation target mismatch')
    if mutation['operation'] == 'upsert':
        annotation = mutation['annotation']
        ensure(annotation['annotation_id'] == mutation['annotation_id'], 'Mutation annotation ID mismatch')
        ensure(annotation['document_id'] == mutation['document_id'] and annotation['version_id'] == mutation['version_id'], 'Mutation annotation document mismatch')
        annotation_ok(annotation)

def to_view(point, geometry, scale, offset):
    x0, y0, x1, y1 = geometry['crop_box']
    u, v = point[0] - x0, point[1] - y0
    w, h = x1 - x0, y1 - y0
    X, Y = {0: (u, h-v), 90: (v, u), 180: (w-u, v), 270: (h-v, w-u)}[geometry['rotation_degrees']]
    factor = geometry['user_unit'] * scale
    return [offset[0] + X*factor, offset[1] + Y*factor]

def from_view(point, geometry, scale, offset):
    x0, y0, x1, y1 = geometry['crop_box']
    w, h = x1-x0, y1-y0
    factor = geometry['user_unit'] * scale
    X, Y = (point[0]-offset[0])/factor, (point[1]-offset[1])/factor
    u, v = {0: (X, h-Y), 90: (Y, X), 180: (w-X, Y), 270: (w-Y, h-X)}[geometry['rotation_degrees']]
    return [u+x0, v+y0]

def events_ok(events):
    ensure(events and events[0]['type'] == 'turn.started', 'Missing started')
    terminal = False
    citations = {}
    turn_id = events[0]['turn_id']
    for seq, event in enumerate(events, 1):
        validate('events.schema.json', event)
        ensure(not terminal, 'Event after terminal')
        ensure(event['turn_id'] == turn_id and event['seq'] == seq, 'Event gap/wrong turn')
        ensure(event['event_id'] == f'{turn_id}:{seq}', 'Event ID mismatch')
        kind, payload = event['type'], event['payload']
        if kind == 'citation.verified':
            citation = payload['citation']
            anchor_ok(citation['anchor'])
            citations[citation['citation_id']] = citation
        elif kind.startswith('reader.'):
            ensure(payload['citation_id'] in citations, 'Reader action before verified citation')
            citation = citations[payload['citation_id']]
            if kind == 'reader.annotate':
                annotation_ok(payload['annotation'])
                target = payload['annotation']
            else:
                target = payload['target']
                target_ok(target)
                if kind == 'reader.goto':
                    point_ok(payload['position'], PAGES[target['page_index']])
                else:
                    ensure(payload['rects'] == citation['anchor']['rects'], 'Reader rectangles differ')
            ensure(all(target[k] == citation['anchor'][k] for k in ['document_id', 'version_id', 'page_index']), 'Reader target differs from citation')
        elif kind == 'quiz.show':
            ensure(payload['quiz_id'] == F['quiz']['quiz_id'], 'Missing quiz')
        elif kind == 'question.show':
            ensure(payload['quiz_id'] == F['quiz']['quiz_id'] and payload['question_id'] in [q['question_id'] for q in F['quiz']['questions']], 'Missing question')
        terminal = kind in ['turn.done', 'turn.error', 'turn.cancelled']
    ensure(terminal, 'No terminal event')

class SyncReference:
    """Small specification state machine; never imported by a product."""
    def __init__(self, snapshot):
        self.records = {x['annotation_id']: copy.deepcopy(x) for x in snapshot['annotations']}
        self.revision = snapshot['snapshot_revision']
        self.receipts = {}
        self.log = []

    def apply(self, mutation):
        mutation_ok(mutation)
        mid = mutation['client_mutation_id']
        if mid in self.receipts:
            original, receipt = self.receipts[mid]
            if original == mutation:
                return copy.deepcopy(receipt)
            return {'client_mutation_id': mid, 'status':'rejected', 'code':'idempotency_mismatch', 'server_revision':self.revision, 'current':None}
        aid = mutation['annotation_id']
        current = self.records.get(aid)
        base = current['server_revision'] if current else 0
        if mutation['base_revision'] != base or (current and current['deleted']) or (not current and mutation['operation'] == 'delete'):
            result = {'client_mutation_id':mid,'status':'conflict','code':'conflict','server_revision':self.revision,'current':copy.deepcopy(current)}
        else:
            self.revision += 1
            if mutation['operation'] == 'delete':
                record = {**current, 'payload':None, 'deleted':True, 'deleted_at':mutation['created_at'], 'updated_at':mutation['created_at'], 'server_revision':self.revision}
            else:
                record = {**copy.deepcopy(mutation['annotation']), 'deleted':False, 'deleted_at':None, 'updated_at':mutation['created_at'], 'server_revision':self.revision}
            self.records[aid] = record
            self.log.append(copy.deepcopy(record))
            result = {'client_mutation_id':mid,'status':'applied','code':'ok','server_revision':self.revision,'current':record}
        self.receipts[mid] = (copy.deepcopy(mutation), copy.deepcopy(result))
        return result

def parse_sse(text):
    result = []
    fields = {'data': []}
    for line in text.replace('\r\n', '\n').split('\n'):
        if not line:
            if fields['data']:
                event = json.loads('\n'.join(fields['data']))
                ensure(fields.get('id') == event['event_id'] and fields.get('event') == event['type'], 'SSE envelope mismatch')
                result.append(event)
            fields = {'data': []}
        elif not line.startswith(':'):
            key, _, value = line.partition(':')
            if value.startswith(' '): value = value[1:]
            if key == 'data': fields['data'].append(value)
            elif key in ['id', 'event']: fields[key] = value
    return result

def check_ownership():
    ownership = read(ROOT / 'integration/ownership.json')
    owners = {}
    for unit, paths in ownership['owners'].items():
        for path in paths:
            ensure(path not in owners, f'Double ownership: {path}')
            ensure((ROOT/path).is_file(), f'Ownership path missing: {path}')
            owners[path] = unit
    # Include untracked non-ignored files so newly added code cannot silently escape ownership.
    output = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'], cwd=ROOT)
    actual = {x.decode() for x in output.split(b'\0') if x}
    ensure(set(owners) == actual, f'Ownership mismatch: unassigned={sorted(actual-set(owners))}; absent={sorted(set(owners)-actual)}')

def check_manifest():
    manifest = read(C/'manifest.json')
    ensure(manifest['contract_version'] == V, 'Manifest version mismatch')
    actual = {p.relative_to(C).as_posix() for p in C.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    ensure(actual == set(manifest['files']), 'Manifest file set mismatch')
    for path, digest in manifest['files'].items():
        ensure(sha((C/path).read_bytes()) == digest, f'Manifest digest differs: {path}')

def source_gate():
    state = read(ROOT/'integration/registry.json')
    ensure(state['ready_for_parallel_implementation'] is True, 'SOURCE GATE: Pumice/DeepTutor sources and real paths are pending; not ready for product jobs.')
    ensure(state['external_transport'] in ['sse','websocket'], 'Transport unselected')
    for source in state['upstreams'].values():
        ensure(all(source[k] for k in ['commit','license','build_command','test_command']), 'Upstream audit incomplete')
        ensure(source['url'] or source['local_path'], 'Upstream location absent')
        ensure(len(source['commit']) == 40, 'Need full upstream SHA')
    ensure(state['assembly_path'] and state['assembly_symbol'], 'Assembly unverified')
    seen = set()
    for unit in state['units'].values():
        ensure(unit['source_paths'] and unit['registration_symbol'], 'Unit paths/registration unverified')
        for path in unit['source_paths']:
            ensure(path not in seen, 'Source path owned twice')
            seen.add(path)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-ready', action='store_true')
    args = parser.parse_args()
    api_path = C/'openapi.yaml'
    api = read(api_path)
    ensure(yaml.safe_load(api_path.read_text()) == api, 'JSON/YAML consumers disagree')
    OpenAPIV31SpecValidator(api, base_uri=api_path.as_uri()).validate()
    ensure(api['info']['version'] == F['contract_version'] == V, 'Contract version mismatch')
    ensure(DOC['source_sha256'] == sha((C/'fixtures'/F['original_file']).read_bytes()), 'Original PDF hash differs')
    ensure(DOC['version_id'] == 'sha256:'+DOC['source_sha256'], 'Original version mismatch')
    ensure(DOC['page_count'] == len(PAGES), 'Page count differs')
    for name, definition in [('subject','Subject'),('document','Document'),('reader_context','ReaderContext'),('quiz','Quiz'),('attempt','Attempt'),('assessment','Assessment'),('learning_state','LearningState')]:
        validate('models.schema.json', F[name], definition)
    for index, page in PAGES.items():
        validate('models.schema.json', page, 'Page')
        target_ok(page)
        ensure(index == page['page_index'] and page['display_page_number'] == index+1, 'Page numbering mismatch')
        ensure(sha(page['text'].encode()) == page['text_sha256'], 'Parsed text hash mismatch')
        g = page['geometry']
        x0,y0,x1,y1 = g['crop_box']
        mx0,my0,mx1,my1 = g['media_box']
        ensure(mx0 <= x0 < x1 <= mx1 and my0 <= y0 < y1 <= my1, 'Invalid boxes')
    for citation in F['citations']:
        validate('models.schema.json', citation, 'VerifiedCitation')
        anchor_ok(citation['anchor'])
    anchor_ok(F['reader_context']['selection'])
    validate('annotations.schema.json', F['annotation_snapshot'], 'Snapshot')
    for annotation in F['annotation_snapshot']['annotations']: annotation_ok(annotation)
    validate('annotations.schema.json', F['change_page'], 'ChangePage')
    state = SyncReference(F['annotation_snapshot'])
    for step in F['sync_steps']:
        validate('annotations.schema.json', step['mutation'], 'Mutation')
        validate('annotations.schema.json', step['expected'], 'MutationResult')
        ensure(state.apply(step['mutation']) == step['expected'], f'Sync differs: {step["name"]}')
        COUNTS['sync_steps'] += 1
    ensure(state.log == F['change_page']['changes'] and state.revision == 7, 'Change log differs')
    batch = {'contract_version':V,'document_id':DOC['document_id'],'version_id':DOC['version_id'],'mutations':[x['mutation'] for x in F['sync_steps'][:2]]}
    validate('annotations.schema.json', batch, 'MutationBatch')
    validate('annotations.schema.json', {'contract_version':V,'document_id':DOC['document_id'],'version_id':DOC['version_id'],'results':[x['expected'] for x in F['sync_steps'][:2]]}, 'SyncReceipt')
    for key in ['events','cancelled_events','error_events']: events_ok(F[key])
    ensure(parse_sse((C/'fixtures/tutor.sse').read_text()) == F['events'], 'SSE fixture differs')
    last = F['reconnect']['last_event_id']
    ensure(F['reconnect']['replayed_events'] == [e for e in F['events'] if e['seq'] > int(last.split(':')[-1])], 'Resume range differs')
    applied = F['events'][:5]
    seen = {e['event_id'] for e in applied}
    for event in [F['reconnect']['duplicate_delivery']] + F['reconnect']['replayed_events']:
        if event['event_id'] not in seen:
            seen.add(event['event_id']); applied.append(event)
    ensure(applied == F['events'], 'Duplicate event applied')
    ensure(F['attempt']['quiz_id'] == F['quiz']['quiz_id'] and F['assessment']['attempt_id'] == F['attempt']['attempt_id'], 'Attempt linkage mismatch')
    ensure(F['learning_state']['quiz_attempts'][0]['attempt_id'] == F['attempt']['attempt_id'], 'Learning linkage mismatch')
    ensure(F['learning_state']['learning_revision'] == F['assessment']['learning_revision'], 'Learning revision mismatch')
    for case in F['geometry_cases']:
        actual = to_view(case['point_pdf'], case['geometry'], case['scale'], case['offset'])
        ensure(actual == case['expected_viewport'], 'Geometry forward mismatch')
        ensure(from_view(actual, case['geometry'], case['scale'], case['offset']) == case['point_pdf'], 'Geometry inverse mismatch')
    probe = F['unicode_probe']
    ensure(probe['text'][probe['start_scalar']:probe['end_scalar']] == probe['quote'], 'Unicode scalar mismatch')
    def bad_anchor(field, value):
        bad = copy.deepcopy(F['citations'][0]['anchor']); bad[field]=value; anchor_ok(bad)
    for field, value in [('quote','틀린 인용'),('version_id','sha256:'+'0'*64),('page_index',9),('parse_revision','wrong'),('text_sha256','0'*64),('end_scalar',999),('rects',[[10,20,2,2]])]:
        negative(field, lambda f=field,v=value:bad_anchor(f,v))
    bad_page=copy.deepcopy(F['pages'][0]);bad_page['geometry']['rotation_degrees']=45
    negative('rotation', lambda:validate('models.schema.json',bad_page,'Page'))
    bad_annotation=copy.deepcopy(F['annotation_snapshot']['annotations'][0]);bad_annotation['kind']='note'
    negative('kind payload mismatch', lambda:validate('annotations.schema.json',bad_annotation,'AnnotationRecord'))
    bad_mutation=copy.deepcopy(F['sync_steps'][0]['mutation']);bad_mutation['annotation']['annotation_id']='00000000-0000-0000-0000-000000009999'
    negative('mutation ID mismatch',lambda:mutation_ok(bad_mutation))
    wrong_event=copy.deepcopy(F['events']);wrong_event[3]['seq']=8
    negative('event sequence gap',lambda:events_ok(wrong_event))
    wrong_event=copy.deepcopy(F['events']);wrong_event.append(copy.deepcopy(F['events'][-1]))
    negative('event after terminal',lambda:events_ok(wrong_event))
    wrong_event=copy.deepcopy(F['events']);wrong_event[4]['payload']['rects']=[[10,20,2,2]]
    negative('unverified Reader geometry',lambda:events_ok(wrong_event))
    negative('missing terminal',lambda:events_ok(F['events'][:-1]))
    bad_tomb=copy.deepcopy(F['change_page']['changes'][1]);bad_tomb['payload']=F['annotation_snapshot']['annotations'][3]['payload']
    negative('tombstone payload',lambda:validate('annotations.schema.json',bad_tomb,'AnnotationRecord'))
    secret_settings={'server_revision':1,'provider':{'adapter':'openai-compatible','base_url':'https://provider.invalid/v1','model':'fixture','credential_configured':True,'api_key':'must-not-leak'},'response_language':'ko'}
    negative('credential in settings output',lambda:validate('models.schema.json',secret_settings,'PublicSettings'))
    wrong_doc=copy.deepcopy(DOC);wrong_doc['source_path']='../../outside.pdf'
    negative('path in document DTO',lambda:validate('models.schema.json',wrong_doc,'Document'))
    persistent_event=copy.deepcopy(F['events'][4]);persistent_event['payload']['persistent']=True
    negative('persistent temporary highlight',lambda:validate('events.schema.json',persistent_event))
    unknown_event=copy.deepcopy(F['events'][0]);unknown_event['type']='reader.execute'
    negative('unknown Reader command',lambda:validate('events.schema.json',unknown_event))
    operations=[op['operationId'] for path in api['paths'].values() for op in path.values()]
    ensure(len(operations)==len(set(operations)), 'Duplicate operation ID')
    ensure(sum('text/event-stream' in op['responses'].get('200',{}).get('content',{}) for path in api['paths'].values() for op in path.values())==1, 'Need one candidate stream')
    ensure(not any(path.startswith('/ws') for path in api['paths']), 'WebSocket route introduced')
    public=[path for path,methods in api['paths'].items() for op in methods.values() if op.get('security')==[]]
    ensure(set(public)=={'/health','/v1/session/pair'}, 'Unexpected unauthenticated API')
    for path,method in [('/v1/settings','put'),('/v1/documents/{document_id}','delete')]:
        headers={p['name'] for p in api['paths'][path][method]['parameters'] if p['in']=='header'}
        ensure({'If-Match','X-Confirm-Action','X-Mnemosyne-Contract-Version'}<=headers, 'Missing protected mutation headers')
    check_manifest(); check_ownership()
    print(json.dumps({'result':'PASS','openapi_operations':len(operations),'schemas':len(schema_files),**COUNTS,'geometry_cases':len(F['geometry_cases']),'source_ready':read(ROOT/'integration/registry.json')['ready_for_parallel_implementation']},ensure_ascii=False))
    if args.require_ready:
        source_gate()

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'FAIL: {error}', file=sys.stderr)
        sys.exit(1)
