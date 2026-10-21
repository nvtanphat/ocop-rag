"""Peak detector allocations share one OS-owned slot across OCR processes."""
import json
import subprocess
import sys


def test_three_processes_serialize_only_the_peak_inference_section(tmp_path):
    script = '''
import sys,time,json
from pathlib import Path
from ocop_ocr.inference_guard import inference_slot
with inference_slot(Path(sys.argv[1])):
    with open(sys.argv[2], 'a') as stream: stream.write(json.dumps('start')+'\\n')
    time.sleep(.15)
    with open(sys.argv[2], 'a') as stream: stream.write(json.dumps('end')+'\\n')
'''
    children=[subprocess.Popen([sys.executable,'-c',script,str(tmp_path/'lock'),str(tmp_path/'events')])
              for _ in range(3)]
    try:
        for child in children:
            assert child.wait(timeout=15)==0
        assert [json.loads(s) for s in (tmp_path/'events').read_text().splitlines()]==['start','end']*3
    finally:
        for child in children:
            if child.poll() is None:
                child.kill(); child.wait(timeout=5)
