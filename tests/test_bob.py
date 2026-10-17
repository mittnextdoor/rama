"""Bob's hackathon build (MONEY TALKS 2): the Nicrron provider's request and answer handling against a fake endpoint, the
hackathon switch (no direct provider call), PRISM's payloads and delivery handling against a fake host, the engine's steps
under a run, and the evaluation harness on a few cases. Nothing here reaches the network."""
import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock


class _Resp(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(json.dumps(body).encode())
        self.status, self.headers = status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {"retry-after": "1"} if code == 429 else {}, io.BytesIO(json.dumps(body).encode()))


class NicrronProviderTests(unittest.TestCase):
    def setUp(self):
        from bob import trace
        self.env = mock.patch.dict(os.environ, {"BOB_HACKATHON": "1", "NICRRON_API_KEY": "sk-af-test-key-0123456789", "NICRRON_MODEL": "anthropic/claude-haiku-5-5",
                                                "NICRRON_STRUCTURED": "prompt", "BOB_RUNS_DIR": tempfile.mkdtemp()}, clear=False)
        self.env.start()
        self.trace = trace

    def tearDown(self):
        self.env.stop()

    def _answer(self, content, finish="stop", model="anthropic/claude-haiku-5-5", tool_calls=None):
        msg = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return {"id": "c1", "model": model, "choices": [{"index": 0, "finish_reason": finish, "message": msg}], "usage": {"prompt_tokens": 120, "completion_tokens": 30}}

    def test_hackathon_mode_routes_every_agent_through_nicrron_with_its_own_key(self):
        from product.reasoning import config, providers, secrets
        p = providers.provider("anthropic")
        self.assertEqual(p.name, "nicrron")
        cfg = config.agent("classifier")
        key, source = secrets.credential(cfg)
        self.assertEqual((key, source), ("sk-af-test-key-0123456789", "environment (NICRRON_API_KEY)"))
        self.assertEqual(secrets.expects(cfg), "NICRRON_API_KEY")
        self.assertIn("[redacted]", secrets.redact("bad sk-af-test-key-0123456789 leaked"))
        with mock.patch.dict(os.environ, {"NICRRON_API_KEY": "", "NHB_ANTHROPIC_API_KEY": "sk-ant-should-not-be-used-0123456789"}):
            self.assertEqual(secrets.credential(cfg), (None, None))       # an Anthropic key never stands in for Nicrron's

    def test_complete_sends_an_openai_request_and_parses_the_json_answer(self):
        from product.reasoning import providers
        sent = {}

        def fake_open(req, timeout=None):
            sent["url"], sent["headers"], sent["body"] = req.full_url, dict(req.header_items()), json.loads(req.data)
            return _Resp(self._answer("```json\n{\"items\": [{\"id\": \"n0\", \"ok\": true}]}\n```"))
        schema = {"type": "object", "additionalProperties": False, "required": ["items"], "properties": {"items": {"type": "array", "maxItems": 5, "items": {"type": "object"}}}}
        with mock.patch.object(urllib.request, "urlopen", fake_open):
            with self.trace.run(kind="test", task="t", session_id="s") as r:
                out, usage = providers.provider("anthropic").complete(key="sk-af-test-key-0123456789", model="claude-haiku-4-5-20251001", system="Be exact.",
                                                                        user="data", tool={"name": "record", "input_schema": schema}, max_tokens=400, temperature=0, timeout=5)
                r.finish("ok")
        self.assertEqual(sent["url"], "https://api.nicrron.ai/v1/chat/completions")
        self.assertEqual(sent["headers"]["Authorization"], "Bearer sk-af-test-key-0123456789")
        self.assertEqual(sent["body"]["model"], "anthropic/claude-haiku-5-5")           # an Anthropic id maps to the hackathon's model
        self.assertEqual([m["role"] for m in sent["body"]["messages"]], ["system", "user"])
        self.assertIn("JSON schema", sent["body"]["messages"][0]["content"])
        self.assertNotIn("maxItems", sent["body"]["messages"][0]["content"])              # the schema goes without unsupported limits
        self.assertNotIn("response_format", sent["body"])
        self.assertEqual(out, {"items": [{"id": "n0", "ok": True}]})
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (120, 30))
        llm = [s for s in r.spans if s["span_type"] == "llm"]
        self.assertEqual((len(llm), llm[0]["model"], llm[0]["token_count_input"], llm[0]["status"]), (1, "anthropic/claude-haiku-5-5", 120, "ok"))

    def test_json_schema_mode_sends_response_format_and_a_refusal_names_the_setting(self):
        from product.reasoning import providers
        with mock.patch.dict(os.environ, {"NICRRON_STRUCTURED": "json_schema"}):
            sent = {}

            def fake_open(req, timeout=None):
                sent["body"] = json.loads(req.data)
                raise _http_error(400, {"error": {"message": "response_format is not supported for this model"}})
            with mock.patch.object(urllib.request, "urlopen", fake_open):
                with self.assertRaises(providers.ProviderError) as cm:
                    providers.provider("anthropic").complete(key="k", model="x/y", system="s", user="u", tool={"name": "t", "input_schema": {"type": "object"}},
                                                             max_tokens=10, temperature=None, timeout=5)
            self.assertEqual(sent["body"]["response_format"]["type"], "json_schema")
            self.assertIn("NICRRON_STRUCTURED=prompt", str(cm.exception))
            self.assertFalse(cm.exception.retryable)

    def test_rate_limits_are_retryable_and_each_failed_attempt_is_a_step(self):
        from product.reasoning import providers
        calls = {"n": 0}

        def fake_open(req, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _http_error(429, {"error": {"message": "slow down"}})
            return _Resp(self._answer("{\"a\": 1}"))
        with mock.patch.object(urllib.request, "urlopen", fake_open), mock.patch.object(providers, "backoff", lambda *a, **k: None):
            with self.trace.run(kind="test", task="t", session_id="s") as r:
                p = providers.provider("anthropic")
                with self.assertRaises(providers.ProviderError) as cm:
                    p.complete(key="k", model="x/y", system="s", user="u", tool={"name": "t", "input_schema": {"type": "object"}}, max_tokens=10, temperature=None, timeout=5)
                self.assertTrue(cm.exception.retryable)
                self.assertEqual(cm.exception.retry_after, 1.0)
                out, _ = p.complete(key="k", model="x/y", system="s", user="u", tool={"name": "t", "input_schema": {"type": "object"}}, max_tokens=10, temperature=None, timeout=5)
                r.finish("ok")
        self.assertEqual(out, {"a": 1})
        self.assertEqual([s["status"] for s in r.spans if s["span_type"] == "llm"], ["error", "ok"])
        self.assertIn("429", r.spans[0]["error_message"])

    def test_cut_off_and_refusal_stop_without_retry(self):
        from product.reasoning import providers
        with mock.patch.object(urllib.request, "urlopen", lambda req, timeout=None: _Resp(self._answer("{\"a\":", finish="length"))):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.provider("anthropic").complete(key="k", model="x/y", system="s", user="u", tool={"name": "t", "input_schema": {"type": "object"}}, max_tokens=10, temperature=None, timeout=5)
        self.assertIn("max_tokens", str(cm.exception))
        with mock.patch.object(urllib.request, "urlopen", lambda req, timeout=None: _Resp({"choices": [{"message": {"refusal": "no"}}]})):
            with self.assertRaises(providers.ProviderError) as cm:
                providers.provider("anthropic").complete(key="k", model="x/y", system="s", user="u", tool={"name": "t", "input_schema": {"type": "object"}}, max_tokens=10, temperature=None, timeout=5)
        self.assertIn("refusal", str(cm.exception))

    def test_converse_translates_tool_blocks_both_ways(self):
        from product.reasoning import providers
        sent = {}

        def fake_open(req, timeout=None):
            sent["body"] = json.loads(req.data)
            return _Resp(self._answer(None, finish="tool_calls", tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "find_transactions", "arguments": "{\"q\": \"shell\"}"}}]))
        messages = [{"role": "user", "content": "What did we pay Shell?"},
                    {"role": "assistant", "content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "Looking."},
                                                      {"type": "tool_use", "id": "call_0", "name": "month_status", "input": {}}]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_0", "content": "{\"status\": \"open\"}"}]}]
        tools = [{"name": "month_status", "description": "d", "input_schema": {"type": "object", "properties": {}}},
                 {"name": "find_transactions", "description": "d", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}]
        with mock.patch.object(urllib.request, "urlopen", fake_open):
            r = providers.provider("anthropic").converse(key="k", model="claude-sonnet-5-5", system="sys", messages=messages, tools=tools, max_tokens=100, temperature=None, timeout=5)
        body = sent["body"]
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user", "assistant", "tool"])
        self.assertEqual(body["messages"][2]["tool_calls"][0]["function"], {"name": "month_status", "arguments": "{}"})
        self.assertEqual(body["messages"][3]["tool_call_id"], "call_0")
        self.assertEqual([t["function"]["name"] for t in body["tools"]], ["month_status", "find_transactions"])
        self.assertEqual(r["stop_reason"], "tool_use")
        self.assertEqual(r["content"], [{"type": "tool_use", "id": "call_1", "name": "find_transactions", "input": {"q": "shell"}}])

    def test_outside_hackathon_mode_the_configured_provider_is_used(self):
        from product.reasoning import providers
        with mock.patch.dict(os.environ, {"BOB_HACKATHON": "0"}):
            self.assertEqual(providers.provider("anthropic").name, "anthropic")
            self.assertEqual(providers.provider("nicrron").name, "nicrron")


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"BOB_RUNS_DIR": self.dir, "PRISM_API_KEY": "", "PRISM_PROJECT_ID": "",
                                                "PRISMTRACE_API_KEY": "", "PRISMTRACE_PROJECT_ID": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_steps_nest_and_a_run_is_written_locally_without_prism(self):
        from bob import trace
        with trace.run(kind="test", task="close it", session_id="sess-1", fixture={"id": "fx", "version": "1"}) as r:
            with trace.step("read_ledger", "tool", {"period": "2026-02"}) as s:
                s.out({"lines": 3})
                with trace.step("match_statement Checking", "tool") as s2:
                    s2.out({"pairs": 2})
            with trace.step("apply_fix create", "tool") as s3:
                s3.error("read back doesn't show what was sent")
            rec = r.finish("1 of 1 ties", status="success")
        self.assertEqual([s["name"] for s in r.spans], ["match_statement Checking", "read_ledger", "apply_fix create"])
        self.assertEqual(r.spans[0]["parent_span_id"], r.spans[1]["span_id"])
        self.assertEqual((r.spans[2]["status"], r.spans[2]["error_message"]), ("error", "read back doesn't show what was sent"))
        self.assertEqual([t["step_type"] for t in r.steps], ["tool_call", "tool_call", "tool_call", "final_answer"])
        self.assertEqual(rec["prism"], {"sent": False, "why": "PRISMTRACE_API_KEY (or PRISM_API_KEY) and PRISMTRACE_PROJECT_ID aren't set"})
        self.assertTrue(os.path.exists(os.path.join(self.dir, r.id + ".json")))
        self.assertEqual(trace.runs()[0]["session_id"], "sess-1")
        self.assertEqual(trace.load(r.id)["fixture"], {"id": "fx", "version": "1"})

    def test_an_agent_called_on_its_own_gets_its_own_run_and_inside_a_run_joins_it(self):
        from bob import trace
        with trace.ensure_run(kind="assistant", task="what changed?", session_id="assistant-thread-7", agent_id="bob-assistant") as r:
            with trace.step("tool list_changes", "tool", {"month": "2026-09"}) as s:
                s.out({"changes": 2})
        self.assertEqual((r.outcome, r.session_id, r.agent_id), ("success", "assistant-thread-7", "bob-assistant"))
        self.assertEqual(trace.load(r.id)["agent_id"], "bob-assistant")
        self.assertEqual(r.trace_payload({"project_id": "p", "agent_id": "bob-close", "agent_name": "Bob"})["agent_id"], "bob-assistant")
        with trace.run(kind="close", task="close", session_id="c-1") as outer:
            with trace.ensure_run(kind="agent-classifier", task="t", session_id="other", agent_id="bob-classifier") as inner:
                with trace.step("llm m", "llm"):
                    pass
            outer.finish("done")
        self.assertIs(inner, outer)
        self.assertEqual([s["name"] for s in outer.spans], ["llm m"])

    def test_prisms_documented_variable_names_are_read(self):
        from bob import config
        with mock.patch.dict(os.environ, {"PRISMTRACE_API_KEY": "pt-sk-x", "PRISMTRACE_PROJECT_ID": "proj", "PRISMTRACE_HOST": "https://h/"}):
            p = config.prism()
        self.assertEqual((p["key"], p["project_id"], p["host"], p["configured"]), ("pt-sk-x", "proj", "https://h", True))

    def test_an_exception_finishes_the_run_as_an_error(self):
        from bob import trace
        with self.assertRaises(ValueError):
            with trace.run(kind="test", task="t", session_id="s") as r:
                with trace.step("boom", "tool"):
                    raise ValueError("bad")
        self.assertEqual((r.outcome, r.spans[0]["status"]), ("error", "error"))
        self.assertIn("ValueError", r.output)

    def test_payloads_carry_the_documented_fields_and_delivery_records_prisms_answers(self):
        from bob import trace
        with mock.patch.dict(os.environ, {"PRISM_API_KEY": "pt-sk-test", "PRISM_PROJECT_ID": "proj-1"}):
            posted = []

            def fake_open(req, timeout=None):
                posted.append((req.full_url, dict(req.header_items()), json.loads(req.data)))
                return _Resp({"id": f"stored-{len(posted)}", "session_id": "sess"})
            with mock.patch.object(urllib.request, "urlopen", fake_open):
                with trace.run(kind="eval", task="close", session_id="batch-1", fixture={"id": "fx", "version": "1"}, meta={"case_id": "c1"}) as r:
                    with trace.step("llm x/y", "llm") as s:
                        s.llm("x/y", 10, 5)
                        s.out("answer")
                    rec = r.finish("done", status="error")
            urls = [p[0] for p in posted]
            self.assertEqual(urls, ["https://prism.blockconvey.com/api/traces", "https://prism.blockconvey.com/api/spans/ingest", "https://prism.blockconvey.com/api/trajectories"])
            self.assertTrue(all(h["X-prismtrace-key"] == "pt-sk-test" for _, h, _ in posted))
            t = posted[0][2]
            self.assertEqual((t["project_id"], t["trace_id"], t["session_id"], t["model"], t["token_count_input"]), ("proj-1", r.id, "batch-1", "x/y", 10))
            self.assertEqual(t["input_messages"], [{"role": "user", "content": "close"}])
            self.assertEqual(t["metadata"]["fixture_id"], "fx")
            sp = posted[1][2]
            self.assertEqual((sp["trace_id"], sp["project_id"], sp["session_id"], sp["spans"][0]["span_type"], sp["spans"][0]["model"]), (r.id, "proj-1", "batch-1", "llm", "x/y"))
            tj = posted[2][2]
            self.assertEqual((tj["request_id"], tj["conversation_id"], tj["final_status"], tj["steps"][-1]["step_type"]), (r.id, "batch-1", "error", "final_answer"))
            self.assertTrue(rec["prism"]["received"])
            self.assertEqual(rec["prism"]["trace"]["body"]["id"], "stored-1")

    def test_a_rejected_delivery_is_recorded_not_claimed(self):
        from bob import trace
        with mock.patch.dict(os.environ, {"PRISM_API_KEY": "pt-sk-test", "PRISM_PROJECT_ID": "proj-1"}):
            def fake_open(req, timeout=None):
                raise _http_error(401, {"detail": "invalid key"})
            with mock.patch.object(urllib.request, "urlopen", fake_open):
                with trace.run(kind="eval", task="t", session_id="b") as r:
                    rec = r.finish("x")
            self.assertFalse(rec["prism"]["received"])
            self.assertEqual(rec["prism"]["trace"]["status"], 401)


class EvalTests(unittest.TestCase):
    def test_the_engine_reports_its_steps_and_the_duplicate_import_is_set_aside(self):
        from bob import engine, trace
        from bob.eval import expect, fixtures
        with mock.patch.dict(os.environ, {"BOB_RUNS_DIR": tempfile.mkdtemp(), "PRISM_API_KEY": "", "NICRRON_API_KEY": "", "NHB_AGENT_CLASSIFIER_API_KEY": "",
                                          "NHB_ANTHROPIC_API_KEY": "", "NHB_NO_KEYCHAIN": "1"}):
            case = {"id": "single-duplicate_import", "plants": ["duplicate_import"]}
            econn, scope, ad, inputs, exp, folder = fixtures.build(case)
            try:
                with trace.run(kind="eval", task="t", session_id="b") as r:
                    result = engine.close_month(ad, scope, inputs, ask_model=False)
                    r.finish("x")
            finally:
                econn.close()
            self.assertEqual(expect.verify(result, exp), [])
            names = [s["name"] for s in r.spans]
            for want in ("read_ledger initial", "read_documents initial", "match_statement Checking", "reconcile Checking", "rematch_client_entries",
                         "check_ledger", "build_workpapers", "tie_and_check initial", "prepare_statements"):
                self.assertIn(want, names)
            self.assertGreaterEqual(sum(1 for s in r.steps if s["step_type"] == "tool_call"), 6)
            dup = next(f for f in result["final"]["findings"] if f["check"] == "statement_incomplete")
            self.assertIn("imported twice", dup["detail"])
            self.assertEqual(result["applied"], [])
            with mock.patch.dict(os.environ, {"BOB_V1": "1"}):              # the baseline's behaviour, reproducible
                econn, scope, ad, inputs, exp, folder = fixtures.build(case)
                try:
                    result = engine.close_month(ad, scope, inputs, ask_model=False)
                finally:
                    econn.close()
            self.assertTrue(any(p.startswith("forbidden write") for p in expect.verify(result, exp)))

    def test_a_changed_description_meets_the_vendors_history(self):
        from bob import engine
        from bob.eval import expect, fixtures
        with mock.patch.dict(os.environ, {"NICRRON_API_KEY": "", "NHB_AGENT_CLASSIFIER_API_KEY": "", "NHB_ANTHROPIC_API_KEY": "", "NHB_NO_KEYCHAIN": "1"}):
            econn, scope, ad, inputs, exp, folder = fixtures.build({"id": "t", "plants": ["refund_unrecorded", "vendor_description_varies"]})
            try:
                result = engine.close_month(ad, scope, inputs, ask_model=False)
            finally:
                econn.close()
        self.assertEqual(expect.verify(result, exp), [])
        self.assertEqual(sorted(a["to"] for a in result["applied"]), ["Materials", "Materials"])
        self.assertTrue(all(any(c.startswith("ledger:") for c in a["citations"]) for a in result["applied"]))

    def test_every_case_builds_and_is_compatible(self):
        from bob.eval import fixtures
        cases = fixtures.cases()
        self.assertGreaterEqual(len(cases), 50)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        for c in cases:
            self.assertTrue(fixtures.compatible(c["plants"]), c["id"])


if __name__ == "__main__":
    unittest.main()
