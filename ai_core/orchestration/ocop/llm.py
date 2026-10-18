"""Shared Ollama qwen3.5:2b adapter. No hidden model download."""
from __future__ import annotations
import json,urllib.error,urllib.request
from ai_core.system.telemetry import traced

class OllamaClient:
    def __init__(self,model:str="qwen3.5:2b",url:str="http://127.0.0.1:11434",timeout:float=75):
        self.model=model;self.url=url.rstrip("/");self.timeout=timeout
    @traced("ocop.llm.ollama_chat")
    def chat(self,system:str,user:str,*,format_json:bool=False,max_tokens:int=1024)->str:
        data={"model":self.model,"stream":False,
              "messages":[{"role":"system","content":system},{"role":"user","content":user}],
              "options":{"temperature":0.1,"num_ctx":8192,"num_predict":max_tokens}}
        if format_json:data["format"]="json"
        req=urllib.request.Request(self.url+"/api/chat",data=json.dumps(data,ensure_ascii=False).encode(),
                                   headers={"Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as response:
                out=json.load(response)
            return str(out["message"]["content"])
        except (urllib.error.URLError,TimeoutError,OSError,KeyError,ValueError) as exc:
            raise RuntimeError("Configured Ollama model unavailable") from exc
    def route(self,question:str)->dict:
        system=("Bạn là router cho OCOP. Chỉ trả JSON với intent và slots. "
                "Không ra lệnh tools. Không suy đoán tenant_id/dossier_id.")
        try:
            return json.loads(self.chat(system,question,format_json=True,max_tokens=180))
        except (json.JSONDecodeError,RuntimeError):return {}
