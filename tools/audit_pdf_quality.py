"""Source-backed OCOP table/layout evaluation. Does not OCR, mutate corpus, or publish facts.

Examples:
  python tools/audit_pdf_quality.py --source VN.OCOP.QD26.2026 --pages 18,28,29,30,148 --gold tests/fixtures/ocop_pdf_table_gold.jsonl
  python tools/audit_pdf_quality.py --source VN.OCOP.QD26.2026 --pages all --output data/review/ocop/pdf_table_audit.json

Gold annotations are human-provided page/table labels; more detected regions
must NEVER be treated as a higher accuracy score without ground truth.
"""
from __future__ import annotations
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from ai_core.processing.ocop.pdf_loader import checked_sources
from ai_core.processing.ocop.table_parser import raster_tables,native_tables


def _gold(path:Path|None)->dict:
    if path is None:return {}
    gold={}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        row=json.loads(line)
        gold[(row['source_id'],int(row['pdf_page']))]=row
    return gold


def evaluate(rows:list[dict],annotations:dict)->dict:
    counted=Counter()
    for rec in rows:
        a=annotations.get((rec['source_id'],rec['pdf_page']))
        if not a:continue
        counted['annotated_pages']+=1
        actual=bool(rec['table_count']);expected=bool(a['has_table'])
        if actual and expected:counted['TP']+=1
        elif actual:counted['FP']+=1
        elif expected:counted['FN']+=1
        else:counted['TN']+=1
        if expected and actual and a.get('expected_columns') is not None:
            counted['column_annotated_pages']+=1
            if any(t['col_count']==a['expected_columns'] for t in rec['tables']):
                counted['column_exact_match_pages']+=1
    def ratio(num,den):return round(num/den,4) if den else None
    precision=ratio(counted['TP'],counted['TP']+counted['FP'])
    recall=ratio(counted['TP'],counted['TP']+counted['FN'])
    return {'counts':dict(counted),'table_presence_precision':precision,
            'table_presence_recall':recall,'table_presence_f1':
            (round(2*precision*recall/(precision+recall),4) if precision is not None and recall is not None and precision+recall else None),
            'column_exact_match_rate':ratio(counted['column_exact_match_pages'],counted['column_annotated_pages']),
            'limitations':'page/table structure only; not table cell text, OCR CER, VietGAP score accuracy'}


def audit(root:Path,source_id:str,pages:list[int]|None=None,*,dpi:int=130,gold:dict|None=None)->dict:
    import fitz
    from PIL import Image
    sources,_=checked_sources(root,root/'configs/ocop_sources.json',root/'configs/ocop_sources.lock.json')
    target=next((x for x in sources if x.source_id==source_id),None)
    if target is None:raise ValueError(f'unknown source id: {source_id}')
    old={}
    for file in (root/'data/processed/ocop/pages').glob('*.pages.jsonl'):
        for line in file.open(encoding='utf-8'):
            record=json.loads(line)
            if record.get('source_id')==source_id:
                old[record['pdf_page']]=record
    records=[]
    with fitz.open(root/target.path) as pdf:
        selected=pages or list(range(1,len(pdf)+1))
        for number in selected:
            if not 1<=number<=len(pdf):raise ValueError(f'page out of range: {number}')
            page=pdf[number-1]
            pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)
            image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            native=bool(page.get_text().strip()) and not any(
                r.width*r.height>.7*page.rect.width*page.rect.height
                for entry in page.get_images(full=False) for r in page.get_image_rects(entry[0]))
            tables=native_tables(page) if native else raster_tables(image,page,[])
            rows=[{'row_count':t.get('row_count'),'col_count':t.get('col_count'),
                'cell_count':len(t.get('cells') or []),'method':t.get('method')} for t in tables]
            prev=old.get(number,{})
            records.append({'source_id':source_id,'pdf_page':number,
                'table_count':len(tables),'tables':rows,
                'previous_table_count':len(prev.get('tables') or []),
                'previous_table_cell_count':sum(len(t.get('cells') or []) for t in prev.get('tables') or []),
                'new_table_cell_count':sum(t['cell_count'] for t in rows)})
    result={'source_id':source_id,'pages_checked':len(records),
        'old_table_pages':sum(x['previous_table_count']>0 for x in records),
        'new_table_pages':sum(x['table_count']>0 for x in records),
        'old_detected_cells':sum(x['previous_table_cell_count'] for x in records),
        'new_candidate_cells':sum(x['new_table_cell_count'] for x in records),
        'performance_note':'table detection candidates only; more cells does not imply more correct cells',
        'evaluation':evaluate(records,gold or {}),'pages':records}
    return result


def main():
    cli=argparse.ArgumentParser(description='OCOP scanned table benchmark (no OCR or corpus writes)')
    cli.add_argument('--root',type=Path,default=ROOT)
    cli.add_argument('--source',default='VN.OCOP.QD26.2026')
    cli.add_argument('--pages',default='18,28,29,30,148',help='comma-separated 1-based PDF pages or all')
    cli.add_argument('--dpi',type=int,default=130)
    cli.add_argument('--gold',type=Path)
    cli.add_argument('--output',type=Path)
    args=cli.parse_args()
    pages=None if args.pages=='all' else [int(x.strip()) for x in args.pages.split(',')]
    res=audit(args.root.resolve(),args.source,pages,dpi=args.dpi,gold=_gold(args.gold))
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in res.items() if k!='pages'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
