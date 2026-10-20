"""LLM adapters. Ollama serves the optional answer/router path; candidate entity/feature
extraction may instead use an OpenAI-compatible API (OCOP_EXTRACT_*). No hidden model download."""
from __future__ import annotations
import json,os,time,urllib.error,urllib.request
from pathlib import Path
from ai_core.system.telemetry import traced

_ROUTER_SYSTEM=("Bạn là router cho OCOP. Chỉ trả JSON với intent và slots. "
                "Không ra lệnh tools. Không suy đoán tenant_id/dossier_id.")

class _RouteMixin:
    def route(self,question:str)->dict:
        try:
            return json.loads(self.chat(_ROUTER_SYSTEM,question,format_json=True,max_tokens=180))
        except (json.JSONDecodeError,RuntimeError):return {}

class OllamaClient(_RouteMixin):
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

class OpenAICompatClient(_RouteMixin):
    """Chat Completions over HTTPS. The API key is read from the environment, never logged or persisted."""
    def __init__(self,model:str,base_url:str,api_key:str,timeout:float=120,reasoning_budget:int=2048,retries:int=4):
        if not api_key:raise RuntimeError("OCOP_EXTRACT_OPENAI_API_KEY is not set")
        self.model=model;self.url=base_url.rstrip("/");self._key=api_key
        self.timeout=timeout;self.reasoning_budget=reasoning_budget;self.retries=retries
    def __repr__(self)->str:return f"OpenAICompatClient(model={self.model!r}, base_url={self.url!r})"
    @traced("ocop.llm.openai_chat")
    def chat(self,system:str,user:str,*,format_json:bool=False,max_tokens:int=1024)->str:
        # Reasoning models count hidden reasoning tokens against the completion limit.
        data={"model":self.model,"temperature":0.1,"max_tokens":max_tokens+self.reasoning_budget,
              "messages":[{"role":"system","content":system},{"role":"user","content":user}]}
        if format_json:data["response_format"]={"type":"json_object"}
        req=urllib.request.Request(self.url+"/chat/completions",data=json.dumps(data,ensure_ascii=False).encode(),
                                   # Some gateways (Cloudflare 1010) reject the default Python-urllib agent.
                                   headers={"Content-Type":"application/json","Authorization":"Bearer "+self._key,
                                            "User-Agent":"ocop-graphrag/1.0"},
                                   method="POST")
        try:
            content=self._post(req)["choices"][0]["message"]["content"]
        except (urllib.error.URLError,TimeoutError,OSError,KeyError,IndexError,TypeError,ValueError) as exc:
            detail=f"HTTP {exc.code}: {_error_message(exc)}" if isinstance(exc,urllib.error.HTTPError) else type(exc).__name__
            raise RuntimeError(f"Configured OpenAI-compatible model unavailable ({detail})") from exc
        if not isinstance(content,str):raise RuntimeError("OpenAI-compatible model returned no text")
        return content
    def _post(self,req)->dict:
        # Retry rate limits and transient gateway errors with short exponential backoff.
        for attempt in range(self.retries+1):
            try:
                with urllib.request.urlopen(req,timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429,500,502,503,504) or attempt==self.retries:raise
            except (urllib.error.URLError,TimeoutError):
                if attempt==self.retries:raise
            time.sleep(2**attempt)
        raise RuntimeError("unreachable")

def _error_message(exc)->str:
    """Provider error text (e.g. quota exhausted), never the request or API key."""
    try:
        body=json.loads(exc.read() or b"{}")
        return str((body.get("error") or {}).get("message") or "")[:200]
    except (ValueError,OSError,AttributeError):
        return ""

def load_env_file(path:Path|None=None)->None:
    """Minimal .env loader; existing environment variables always win."""
    path=path or Path(__file__).resolve().parents[3]/".env"
    if not path.is_file():return
    for line in path.read_text(encoding="utf-8").splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line:continue
        key,value=line.split("=",1)
        os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))

def extraction_provider()->str:
    load_env_file()
    return os.getenv("OCOP_EXTRACT_LLM_PROVIDER","ollama").strip().lower()

def extraction_model_name()->str:
    """Model id of the extraction client, without needing credentials."""
    default="gpt-5.6-sol" if extraction_provider()=="openai" else "qwen3.5:2b"
    return os.getenv("OCOP_EXTRACT_LLM_MODEL",default)

def extraction_workers()->int:
    load_env_file()
    return int(os.getenv("OCOP_EXTRACT_LLM_WORKERS","1"))

def extraction_gleanings()->int:
    load_env_file()
    return int(os.getenv("OCOP_EXTRACT_LLM_GLEANINGS","1"))

def make_extraction_client()->OllamaClient|OpenAICompatClient:
    """Client used ONLY for candidate entity/feature extraction (--semantic-extract):
    OCOP_EXTRACT_LLM_PROVIDER=ollama (default, local qwen3.5:2b) or openai (OpenAI-compatible API)."""
    provider=extraction_provider();model=extraction_model_name()
    if provider=="openai":
        return OpenAICompatClient(model=model,
                                  base_url=os.getenv("OCOP_EXTRACT_OPENAI_BASE_URL","https://api.openai.com/v1"),
                                  api_key=os.getenv("OCOP_EXTRACT_OPENAI_API_KEY",""))
    if provider!="ollama":raise RuntimeError(f"Unsupported OCOP_EXTRACT_LLM_PROVIDER: {provider}")
    return OllamaClient(model=model,url=os.getenv("OCOP_OLLAMA_URL","http://127.0.0.1:11434"))
