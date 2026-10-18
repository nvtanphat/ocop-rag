"""Opt-in tenant-scoped LangGraph SQLite checkpoint setup.

In production, persist only with trusted AuthContext and explicitly user-owned
sessions. Do not persist private dossier workflows; use dedicated encrypted
storage and approval/audit for those instead. This is an opt-in local feature.
"""
from __future__ import annotations
import hashlib,os,sqlite3
from pathlib import Path


def thread_key(tenant_id:str,principal_id:str,session_id:str)->str:
    if not all(isinstance(x,str) and x and len(x)<=200 for x in (tenant_id,principal_id,session_id)):
        raise ValueError('tenant, principal and session_id are required')
    return hashlib.sha256('\0'.join([tenant_id,principal_id,session_id]).encode()).hexdigest()


class SQLiteCheckpoint:
    def __init__(self,path:Path):
        self.path=Path(path).expanduser().resolve()
        if not self.path.is_absolute():raise ValueError('checkpoint must have an absolute path')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise RuntimeError('Install langgraph-checkpoint-sqlite to enable durable workflows') from exc
        self.conn=sqlite3.connect(str(self.path),check_same_thread=False)
        self.saver=SqliteSaver(self.conn)
        if os.name=='posix':
            self.path.chmod(0o600)
    def close(self):self.conn.close()


def should_checkpoint(*,env:dict,auth,session:dict,private_tools:set[str]):
    if env.get('OCOP_LANGGRAPH_CHECKPOINT_ENABLED')!='1':return False
    from ai_core.orchestration.ocop.contracts import AuthContext
    if not isinstance(auth,AuthContext) or not isinstance(session.get('session_id'),str):return False
    if private_tools:return False
    # Never store raw user-supplied credentials/permissions in session.
    return True
