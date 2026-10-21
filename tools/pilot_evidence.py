"""Render source-locked pilot crops and queue graph samples; never grade content."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from ocop_contracts.pdf_loader import checked_sources
from ocop_contracts.registry import sha256_file

RELATIONS={'RESPONSIBLE_FOR','REQUIRES_EVIDENCE','OWNED_BY','RECOGNIZES','DECLARED_BY',
           'HAS_OPTION','REPLACES','AMENDS','BASED_ON'}


def render(root, output, pages, *, clip=None):
    import fitz
    sources,_=checked_sources(root,root/'configs/ocop_sources.json',root/'configs/ocop_sources.lock.json')
    sources={s.source_id:s for s in sources}
    output.mkdir(parents=True,exist_ok=True)
    records=[]
    for sid,number in sorted(set(pages)):
        source=sources[sid]
        file=root/source.path
        with fitz.open(file) as document:
            page=document[number-1]
            box=fitz.Rect(clip) if clip else page.rect
            if not page.rect.contains(box):
                raise ValueError('crop outside source page')
            target=output/f'{sid}-p{number:03d}.png'
            page.get_pixmap(dpi=150,clip=box,alpha=False).save(target)
        records.append({'source_id':sid,'pdf_page':number,'source_sha256':sha256_file(file),
                        'bbox':list(box),'dpi':150,'crop':str(target),'crop_sha256':sha256_file(target)})
    (output/'crops.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
    return records


def queue_samples(graph, output):
    nodes={r['node_id']:r for r in map(json.loads,(graph/'nodes.jsonl').read_text(encoding='utf-8').splitlines())}
    edges=list(map(json.loads,(graph/'edges.jsonl').read_text(encoding='utf-8').splitlines()))
    counts=Counter(); samples=[]
    for edge in sorted(edges,key=lambda r:r['edge_id']):
        kind=edge['relation_type']
        if kind not in RELATIONS or edge.get('check')!='passed' or counts[kind]>=10:
            continue
        counts[kind]+=1
        samples.append({'edge':edge,'source':nodes[edge['source_entity_id']],
                        'target':nodes[edge['target_entity_id']], 'semantic_assessment':None})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in samples),encoding='utf-8')
    return dict(counts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--page',action='append',default=[],metavar='SOURCE_ID:PAGE')
    parser.add_argument('--selection',type=Path)
    parser.add_argument('--graph',type=Path)
    parser.add_argument('--clip',type=float,nargs=4)
    args=parser.parse_args()
    if args.graph:
        print(json.dumps(queue_samples(args.graph,args.output)))
        return
    pages=[(value.rsplit(':',1)[0],int(value.rsplit(':',1)[1])) for value in args.page]
    if args.selection:
        pages.extend((p['source_id'],p['pdf_page']) for p in json.loads(args.selection.read_text(encoding='utf-8'))['pages'])
    if not pages:
        parser.error('provide --page or --selection')
    print(json.dumps({'rendered':len(render(args.root.resolve(),args.output,pages,clip=args.clip))}))


if __name__=='__main__':
    main()
