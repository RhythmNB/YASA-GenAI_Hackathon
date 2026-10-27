"""Shared generator: the ONE place every agent and engine calls a model.

Meterless engines take an injected generator instead of calling a model
themselves. Point it at Meterless Nightshift through configuration:

  LLM_MODE=nightshift   call Nightshift (OpenAI-compatible API)
  LLM_MODE=sample       no model at all; agents pass a deterministic fallback
                        so judges can run the system without credentials

Every call is written to the trace with the model that actually answered.
"""
import os
import time

from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
DEFAULT_MODEL = "meterless/fast"
PLACEHOLDER_KEYS = {"", "rt-local", "your-nightshift-runtime-key"}


def nightshift_token():
    """Find the Nightshift runtime token without ever printing it.

    Order: NIGHTSHIFT_API_KEY, METERLESS_TOKEN, then the token file the Windows
    app keeps at %LOCALAPPDATA%\\ai.meterless.runtime\\proxy-token.
    """
    for var in ("NIGHTSHIFT_API_KEY", "METERLESS_TOKEN"):
        val = (os.getenv(var) or "").strip()
        if val not in PLACEHOLDER_KEYS:
            return val
    local = os.getenv("LOCALAPPDATA")
    if local:
        path = os.path.join(local, "ai.meterless.runtime", "proxy-token")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
    raise RuntimeError(
        "No Nightshift token found. Open Nightshift (Setup > Providers > endpoint card) "
        "or set METERLESS_TOKEN in your environment."
    )


def llm_mode():
    return os.getenv("LLM_MODE", "sample").strip().lower()


class Generator:
    def __init__(self, tracer=None):
        self.tracer = tracer
        self.mode = llm_mode()
        self.model = None
        self.client = None
        if self.mode == "nightshift":
            from openai import OpenAI

            headers = {}
            app = os.getenv("NIGHTSHIFT_APP")
            if app:
                headers["meterless-app"] = app
            self.client = OpenAI(
                base_url=os.getenv("NIGHTSHIFT_BASE_URL", DEFAULT_BASE_URL),
                api_key=nightshift_token(),
                default_headers=headers or None,
                timeout=180,
                max_retries=2,
            )
            self.model = os.getenv("NIGHTSHIFT_MODEL", DEFAULT_MODEL)
        elif self.mode != "sample":
            raise ValueError(f"Unknown LLM_MODE '{self.mode}'. Use 'nightshift' or 'sample'.")

    def __call__(self, prompt, system_prompt=None, agent="unknown", sample_response=None):
        """Return {"text": str, "model": str}.

        sample_response: string or zero-arg callable used when LLM_MODE=sample.
        """
        started = time.time()
        if self.mode == "nightshift":
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            res = self.client.chat.completions.create(
                model=self.model, messages=messages, temperature=0.2,
                # Nemotron routes reason at length before answering unless told not to;
                # that hidden pass took 20-90 s per call. The flag turns it off and
                # leaves the prompts, rules and review untouched.
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            text = res.choices[0].message.content or ""
            model = getattr(res, "model", None) or self.model
        else:
            if sample_response is None:
                raise RuntimeError(f"{agent}: sample mode needs a sample_response")
            text = sample_response() if callable(sample_response) else sample_response
            model = "sample/deterministic"

        if self.tracer:
            self.tracer.event(
                "llm_call",
                agent=agent,
                mode=self.mode,
                model=model,
                latency_ms=round((time.time() - started) * 1000),
                prompt_chars=len(prompt),
                response_chars=len(text),
            )
        return {"text": text, "model": model}
