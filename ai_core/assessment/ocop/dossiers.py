"""Tenant-isolated filesystem dossier metadata for local development.

No public index or public graph writes. The API layer must authenticate callers.
"""
from __future__ import annotations
import hashlib,json,os,re
from pathlib import Path

ID_RE=re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")

def _validate(tenant_id:str,dossier_id:str):
    if not ID_RE.fullmatch(tenant_id) or not ID_RE.fullmatch(dossier_id):
        raise ValueError("invalid tenant_id/dossier_id")

class DossierStore:
    def __init__(self,root:Path):self.root=Path(root)
    def _path(self,tenant_id:str,dossier_id:str)->Path:
        _validate(tenant_id,dossier_id)
        tenant_key=hashlib.sha256(tenant_id.encode()).hexdigest()
        return self.root/tenant_key/(dossier_id+".json")
    def put(self,tenant_id:str,dossier_id:str,documents:list[dict],*,authorization_checked:bool=False):
        if not authorization_checked:raise PermissionError("caller must authorize tenant before storing dossier")
        target=self._path(tenant_id,dossier_id);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        payload={"tenant_id":tenant_id,"dossier_id":dossier_id,"documents":documents}
        temp=target.with_suffix(".json.tmp")
        with temp.open("w",encoding="utf-8") as f:
            json.dump(payload,f,ensure_ascii=False,sort_keys=True)
        os.chmod(temp,0o600);os.replace(temp,target)
        return {"dossier_id":dossier_id,"document_count":len(documents)}
    def get(self,tenant_id:str,dossier_id:str,*,authorization_checked:bool=False):
        if not authorization_checked:raise PermissionError("caller must authorize tenant before reading dossier")
        path=self._path(tenant_id,dossier_id)
        if not path.exists():return None
        payload=json.loads(path.read_text(encoding="utf-8"))
        if payload["tenant_id"]!=tenant_id or payload["dossier_id"]!=dossier_id:raise PermissionError("tenant mismatch")
        return payload

    def upload_pdf(self,tenant_id:str,dossier_id:str,pdf_bytes:bytes,*,
                   authorization_checked:bool=False,max_bytes:int=25*1024*1024)->dict:
        """Quarantine raw dossier PDF under tenant-scoped private files (no indexing).

        Authentication/virus scanning remains an API deployment responsibility;
        only explicit trusted callers may set authorization_checked=True.
        """
        if not authorization_checked:
            raise PermissionError("caller must authorize tenant before upload")
        if not 1<=len(pdf_bytes)<=max_bytes or not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("unsupported PDF payload/size")
        target=self._path(tenant_id,dossier_id)
        storage=target.parent/(dossier_id+"_uploads")
        storage.mkdir(parents=True,exist_ok=True,mode=0o700)
        sha=hashlib.sha256(pdf_bytes).hexdigest()
        pdf_path=storage/(sha+".pdf")
        if not pdf_path.exists():
            tmp=storage/(sha+".upload.tmp")
            with tmp.open("wb") as fh:
                fh.write(pdf_bytes)
            os.chmod(tmp,0o600)
            os.replace(tmp,pdf_path)
        return {"dossier_id":dossier_id,"sha256":sha,"status":"quarantined_unscanned"}
