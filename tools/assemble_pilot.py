"""Assemble source-locked partial OCR runs for pilot inspection; never a full dataset."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from ocop_contracts.dataset import dataset_file, digest_json
from ocop_contracts.pdf_loader import checked_sources
from ocop_ocr.review import create_dataset


def assemble(root, inputs, output):
    _,locked=checked_sources(root,root/'configs/ocop_sources.json',root/'configs/ocop_sources.lock.json')
    hashes={s['source_id']:s['sha256'] for s in locked['sources']}
    if (output/'manifest.json').exists():
        raise FileExistsError('choose a new pilot directory; review history must not be replaced')
    by_source=defaultdict(dict); versions=set(); expected={}
    for folder in inputs:
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if manifest.get('input_snapshot_sha256')!=locked['aggregate_sha256']:
            raise ValueError('pilot input does not match approved source lock')
        versions.add(manifest['parser_version'])
        for source in manifest['sources']:
            sid=source['source_id'];expected[sid]=source['page_count_expected']
            for line in dataset_file(folder,source['artifact']).read_text(encoding='utf-8').splitlines():
                page=json.loads(line)
                if page.get('quarantined') or page.get('source_sha256')!=hashes[sid] or page['source_id']!=sid:
                    raise ValueError('invalid/quarantined pilot page')
                old=by_source[sid].get(page['pdf_page'])
                if old and digest_json(old)!=digest_json(page):
                    raise ValueError('conflicting outputs for the same pilot page')
                by_source[sid][page['pdf_page']]=page
    if len(versions)!=1:
        raise ValueError('pilot raw parser versions differ; rerun with the same OCR code')
    count=sum(len(pages) for pages in by_source.values())
    if not 1<=count<=80:
        raise ValueError('pilot assembly is limited to 80 pages and never produces a complete corpus')
    raw=output/'_raw';raw.mkdir(parents=True,exist_ok=True)
    manifest={'schema_version':2,'complete':False,'input_snapshot_sha256':locked['aggregate_sha256'],
              'parser_version':next(iter(versions)),'sources':[], 'counts':{'pages':count},
              'input_runs':[str(p) for p in inputs]}
    for sid,pages in sorted(by_source.items()):
        name=hashlib.sha256(sid.encode()).hexdigest()[:12]+'.pages.jsonl'
        (raw/name).write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for _,p in sorted(pages.items())),encoding='utf-8')
        manifest['sources'].append({'source_id':sid,'source_sha256':hashes[sid],
                                   'page_count_expected':expected[sid],'artifact':name})
    (raw/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return create_dataset(raw,output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--input',type=Path,action='append',required=True,help='Raw parser directory with manifest.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=assemble(args.root.resolve(),args.input,args.output)
    print(json.dumps({'complete':result['complete'],'pages':result['counts']['pages'],
                      'dataset_digest':result['dataset_digest']}))


if __name__=='__main__':
    main()
