"""The model API. Structured output comes through the Messages API's structured outputs (output_config.format, a JSON
schema): the answer is JSON in the agent's output shape, then validated again here against the full schema and checked
by the agent's own rules.

What each model accepts differs, and a request a model doesn't accept is refused with a 400 (Claude API reference,
October 2026), so the request is shaped per model:
  - forced tool use (tool_choice "tool"/"any") is refused by Claude Sonnet 5.5, Opus 5.5 and Fable 5.1, so it's never
    sent: structured outputs work on Claude Haiku 4.5 and every newer model;
  - sampling (temperature) is taken only by the Claude 4.6/4.5 line, Haiku 4.5 and the Claude 4 models; Claude Sonnet
    5.5, Sonnet 5 and Haiku 5.5 refuse a non-default value and Opus 4.7 onward refuse any, so it's sent only to the first;
  - effort is taken by Opus 4.5 onward, Sonnet 4.6 and every Claude 5 model, never by Haiku 4.5;
  - Claude 5 models think by default and thinking counts toward max_tokens, so their max_tokens has a floor;
  - structured outputs take no numeric, length or item-count limits, and every object needs additionalProperties false:
    the schema sent leaves those limits out (they're still enforced here, after the answer arrives).

Errors are typed: a retryable one (rate limited, overloaded, a timeout, a 5xx) carries how long to wait; anything else
stops, including a refusal and an answer cut off at max_tokens. The key travels only in the request header."""
import json
import time
import urllib.error
import urllib.request

API = "https://api.anthropic.com/v1/messages"
SAMPLING = ("claude-haiku-4-5", "claude-sonnet-4-5", "claude-sonnet-4-6", "claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-1",
            "claude-sonnet-4-2", "claude-opus-4-2")          # the last two: the Claude 4 models (claude-sonnet-4-20250514, ...)
EFFORT = ("claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-4-6", "claude-opus-5", "claude-sonnet-5",
          "claude-haiku-5", "claude-fable", "claude-mythos")
THINKS_BY_DEFAULT = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable", "claude-mythos")
THINKING_FLOOR = 4096                                         # max_tokens for a model whose thinking shares it
UNSUPPORTED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength", "pattern",
               "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties"}


def output_schema(schema):
    """The agent's output schema as structured outputs take it: the limits left out, a list of types as anyOf, and every
    object closed (additionalProperties false)."""
    if isinstance(schema, list):
        return [output_schema(x) for x in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: output_schema(v) if k in ("items", "anyOf", "allOf", "$defs") else
           {p: output_schema(x) for p, x in v.items()} if k == "properties" else v
           for k, v in schema.items() if k not in UNSUPPORTED}
    if isinstance(out.get("type"), list):
        kinds = out.pop("type")
        out["anyOf"] = [{"type": k, **({"enum": out["enum"]} if "enum" in out and k != "null" else {})} for k in kinds]
        out.pop("enum", None)
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
    return out


def shape(body, model, temperature=None, effort=None):
    """The per-model parts of a request (see the module's note): sampling, effort and a max_tokens floor for thinking."""
    if temperature is not None and model.startswith(SAMPLING):
        body["temperature"] = temperature
    if effort and model.startswith(EFFORT):
        body.setdefault("output_config", {})["effort"] = effort
    if model.startswith(THINKS_BY_DEFAULT):
        body["max_tokens"] = max(int(body["max_tokens"]), THINKING_FLOOR)
    return body


class ProviderError(Exception):
    def __init__(self, message, retryable=False, retry_after=None):
        super().__init__(message)
        self.retryable, self.retry_after = retryable, retry_after


class AnthropicProvider:
    name = "anthropic"

    def _post(self, body, key, timeout):
        from bob import trace as BT
        req = urllib.request.Request(API, method="POST", data=json.dumps(body).encode(),
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with BT.step(f"llm {body['model']}", "llm", {"messages": body["messages"][-2:], "tools": [t["name"] for t in body.get("tools") or []]}) as st:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read())
            except urllib.error.HTTPError as e:
                retry = e.code in (408, 409, 429, 500, 502, 503, 504, 529)
                after = e.headers.get("retry-after") if e.headers else None
                why = ""
                try:                                          # the API's own reason (never the key: it isn't in the answer)
                    why = (json.loads(e.read() or b"{}").get("error") or {}).get("message") or ""
                except (ValueError, OSError, AttributeError):
                    pass
                st.error(f"HTTP {e.code}: {why[:300]}")
                raise ProviderError(f"model API answered {e.code}" + (f": {why[:300]}" if why else ""), retryable=retry,
                                    retry_after=float(after) if after else None) from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                st.error(f"unreachable: {type(e).__name__}")
                raise ProviderError(f"model API unreachable: {type(e).__name__}", retryable=True) from None
            usage = data.get("usage") or {}
            st.llm(data.get("model") or body["model"], usage.get("input_tokens"), usage.get("output_tokens"))
            st.out({"stop_reason": data.get("stop_reason"), "content": [b.get("text") or b.get("name") for b in data.get("content") or []]})
            return data

    def complete(self, *, key, model, system, user, tool, max_tokens, temperature, timeout, effort=None):
        body = shape({"model": model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}],
                      "output_config": {"format": {"type": "json_schema", "schema": output_schema(tool["input_schema"])}}},
                     model, temperature, effort)
        data = self._post(body, key, timeout)
        stop = data.get("stop_reason")
        if stop == "refusal":
            raise ProviderError("the model declined to answer (refusal)", retryable=False)
        if stop == "max_tokens":
            raise ProviderError("the answer was cut off at max_tokens: raise the agent's max_output_tokens", retryable=False)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        try:
            output = json.loads(text)
        except ValueError:
            raise ProviderError("the model didn't return the structured answer", retryable=False) from None
        usage = data.get("usage") or {}
        return output, {"input_tokens": int(usage.get("input_tokens") or 0), "output_tokens": int(usage.get("output_tokens") or 0),
                        "model": data.get("model") or model}

    def converse(self, *, key, model, system, messages, tools, max_tokens, temperature, timeout, effort=None):
        """One turn of a conversation that may use tools (the assistant, product/assistant): the model answers with text,
        or asks the server to run tools. The server runs them and calls again; the model never runs anything itself.
        The caller passes the whole assistant turn back unchanged (thinking blocks included) and only appends."""
        body = shape({"model": model, "max_tokens": max_tokens, "system": system, "messages": messages, "tools": tools},
                     model, temperature, effort)
        data = self._post(body, key, timeout)
        if data.get("stop_reason") == "refusal":
            raise ProviderError("the model declined to answer (refusal)", retryable=False)
        usage = data.get("usage") or {}
        return {"content": data.get("content") or [], "stop_reason": data.get("stop_reason"), "model": data.get("model") or model,
                "input_tokens": int(usage.get("input_tokens") or 0), "output_tokens": int(usage.get("output_tokens") or 0)}


class ScriptedProvider:
    """For tests: answers from a function of the request (or raises a ProviderError). Nothing leaves the machine."""
    name = "scripted"

    def __init__(self, respond):
        self.respond, self.calls = respond, []

    def complete(self, **req):
        self.calls.append({k: v for k, v in req.items() if k != "key"})
        out = self.respond(req)
        if isinstance(out, Exception):
            raise out
        output, usage = out if isinstance(out, tuple) else (out, None)
        return output, usage or {"input_tokens": len(req["user"]) // 4, "output_tokens": len(json.dumps(output)) // 4, "model": req["model"]}

    def converse(self, **req):
        """respond(req) returns the content blocks ([{"type": "text"...}, {"type": "tool_use"...}]) or an exception."""
        self.calls.append({k: v for k, v in req.items() if k != "key"})
        out = self.respond(req)
        if isinstance(out, Exception):
            raise out
        return {"content": out, "stop_reason": "tool_use" if any(b.get("type") == "tool_use" for b in out) else "end_turn",
                "model": req["model"], "input_tokens": len(json.dumps(req["messages"])) // 4, "output_tokens": len(json.dumps(out)) // 4}


class NicrronProvider:
    """Nicrron's OpenAI-compatible endpoint (nicrron.ai/docs/quickstart, read 2026-10-17): POST {base}/chat/completions
    with a bearer key, OpenAI's messages, tools and usage. Used for every agent in hackathon mode (bob/config.py).

    What's documented: the base URL, model ids (provider/model, or nicrron/auto and the other routing slugs), messages,
    the models fallback array, caching at temperature 0. What isn't: structured output and tool calling, so NICRRON_STRUCTURED
    picks how the answer's shape is asked for: "prompt" (the default: the JSON schema goes in the system prompt and the
    JSON in the answer is parsed; code validates it against the full schema afterwards, as for every provider),
    "json_schema" (OpenAI's response_format json_schema, strict) or "json_object". A 400 on either of the last two is
    reported with the setting to change; nothing falls back to another provider. Tool calling (the assistant's converse)
    uses OpenAI's tools and tool_calls, translated from and to the Anthropic content blocks the rest of the code speaks.
    Every call, including each failed attempt, is a step of the current Bob run (bob/trace.py)."""
    name = "nicrron"

    def __init__(self, settings=None):
        from bob import config as bobconfig
        self.s = settings or bobconfig.nicrron()

    def model_for(self, model):
        """A Nicrron model id as configured (provider/model or nicrron/...); an agent whose model is an Anthropic id
        (claude-...) gets the hackathon's model (NICRRON_MODEL)."""
        return model if "/" in str(model or "") else self.s["model"]

    def _post(self, body, key, timeout):
        from bob import trace as BT
        req = urllib.request.Request(self.s["base_url"] + "/chat/completions", method="POST", data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with BT.step(f"llm {body['model']}", "llm", {"messages": body["messages"][-2:], "response_format": body.get("response_format"),
                                                      "tools": [t["function"]["name"] for t in body.get("tools") or []]}) as st:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = json.loads(r.read())
            except urllib.error.HTTPError as e:
                retry = e.code in (408, 409, 429, 500, 502, 503, 504, 529)
                after = e.headers.get("retry-after") if e.headers else None
                why = ""
                try:
                    err = json.loads(e.read() or b"{}").get("error") or {}
                    why = err.get("message") if isinstance(err, dict) else str(err)
                except (ValueError, OSError, AttributeError):
                    pass
                hint = (" (set NICRRON_STRUCTURED=prompt: the endpoint refused response_format)" if e.code == 400 and body.get("response_format")
                        and "response_format" in (why or "").lower() else "")
                st.error(f"HTTP {e.code}: {(why or '')[:300]}")
                raise ProviderError(f"Nicrron answered {e.code}" + (f": {why[:300]}" if why else "") + hint, retryable=retry,
                                    retry_after=float(after) if after else None) from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                st.error(f"unreachable: {type(e).__name__}")
                raise ProviderError(f"Nicrron unreachable: {type(e).__name__}", retryable=True) from None
            usage = data.get("usage") or {}
            st.llm(data.get("model") or body["model"], usage.get("prompt_tokens"), usage.get("completion_tokens"))
            choice = (data.get("choices") or [{}])[0]
            st.out({"finish_reason": choice.get("finish_reason"), "content": (choice.get("message") or {}).get("content"),
                    "tool_calls": [t.get("function", {}).get("name") for t in (choice.get("message") or {}).get("tool_calls") or []],
                    "cache": data.get("x_nicrron_cache")})
            return data

    @staticmethod
    def _content_text(content):
        if isinstance(content, list):
            return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        return content or ""

    @staticmethod
    def _json_in(text):
        """The one JSON object in an answer (as is, or inside a ```json fence, or around other words)."""
        t = (text or "").strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else t[3:]
            t = t.rsplit("```", 1)[0].strip()
        try:
            return json.loads(t)
        except ValueError:
            pass
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            raise ProviderError("the model didn't return the structured answer", retryable=False)
        try:
            return json.loads(t[a:b + 1])
        except ValueError:
            raise ProviderError("the model didn't return the structured answer", retryable=False) from None

    def complete(self, *, key, model, system, user, tool, max_tokens, temperature, timeout, effort=None):
        model = self.model_for(model)
        schema = output_schema(tool["input_schema"])
        mode = self.s["structured"]
        sys_text = system
        if mode != "json_schema":
            sys_text += ("\n\nAnswer with exactly one JSON object and nothing else (no prose, no code fence). It must match this JSON schema:\n"
                         + json.dumps(schema, sort_keys=True))
        body = {"model": model, "messages": [{"role": "system", "content": sys_text}, {"role": "user", "content": user}], "max_tokens": int(max_tokens)}
        if temperature is not None:
            body["temperature"] = temperature
        if mode == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": tool["name"], "schema": schema, "strict": True}}
        elif mode == "json_object":
            body["response_format"] = {"type": "json_object"}
        data = self._post(body, key, timeout)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        if msg.get("refusal"):
            raise ProviderError("the model declined to answer (refusal)", retryable=False)
        if choice.get("finish_reason") == "length":
            raise ProviderError("the answer was cut off at max_tokens: raise the agent's max_output_tokens", retryable=False)
        output = self._json_in(self._content_text(msg.get("content")))
        usage = data.get("usage") or {}
        return output, {"input_tokens": int(usage.get("prompt_tokens") or 0), "output_tokens": int(usage.get("completion_tokens") or 0),
                        "model": data.get("model") or model}

    # ---- Anthropic content blocks <-> OpenAI messages (the assistant's tool conversation)
    @staticmethod
    def _to_openai(system, messages, tools):
        out = [{"role": "system", "content": system}]
        for m in messages:
            c = m.get("content")
            if isinstance(c, str):
                out.append({"role": m["role"], "content": c})
                continue
            if m["role"] == "assistant":
                text = "".join(b.get("text", "") for b in c if b.get("type") == "text")
                calls = [{"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                         for b in c if b.get("type") == "tool_use"]
                msg = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)                           # thinking blocks aren't part of OpenAI's shape and are left out
            else:
                for b in c:
                    if b.get("type") == "tool_result":
                        body = b.get("content")
                        out.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                                    "content": body if isinstance(body, str) else json.dumps(body, default=str)})
                    elif b.get("type") == "text":
                        out.append({"role": "user", "content": b.get("text", "")})
        fns = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}} for t in tools or []]
        return out, fns

    def converse(self, *, key, model, system, messages, tools, max_tokens, temperature, timeout, effort=None):
        model = self.model_for(model)
        msgs, fns = self._to_openai(system, messages, tools)
        body = {"model": model, "messages": msgs, "max_tokens": int(max_tokens)}
        if fns:
            body["tools"] = fns
        if temperature is not None:
            body["temperature"] = temperature
        data = self._post(body, key, timeout)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        if msg.get("refusal"):
            raise ProviderError("the model declined to answer (refusal)", retryable=False)
        content = []
        text = self._content_text(msg.get("content"))
        if text:
            content.append({"type": "text", "text": text})
        for t in msg.get("tool_calls") or []:
            fn = t.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                raise ProviderError(f"the model's tool call {fn.get('name')} carried malformed arguments", retryable=False) from None
            content.append({"type": "tool_use", "id": t.get("id") or f"call_{len(content)}", "name": fn.get("name"), "input": args})
        stop = {"length": "max_tokens", "tool_calls": "tool_use"}.get(choice.get("finish_reason"), "tool_use" if msg.get("tool_calls") else "end_turn")
        usage = data.get("usage") or {}
        return {"content": content, "stop_reason": stop, "model": data.get("model") or model,
                "input_tokens": int(usage.get("prompt_tokens") or 0), "output_tokens": int(usage.get("completion_tokens") or 0)}


_override = {}


def provider(name):
    """The provider for an agent. Hackathon mode (BOB_HACKATHON=1) routes every agent through Nicrron whatever the
    configuration names, and never through a direct provider call; tests' overrides still win."""
    if "any" in _override:
        return _override["any"]
    from bob import config as bobconfig
    if bobconfig.hackathon():
        return NicrronProvider()
    if name == "anthropic":
        return AnthropicProvider()
    if name == "nicrron":
        return NicrronProvider()
    raise ProviderError(f"no provider {name!r}")


def use_for_tests(p):
    """Route every agent through p (tests only); None restores the real providers."""
    if p is None:
        _override.clear()
    else:
        _override["any"] = p


def backoff(attempt, retry_after=None):
    time.sleep(min(retry_after if retry_after else 2 ** attempt, 20))
