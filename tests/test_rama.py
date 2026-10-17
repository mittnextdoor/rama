"""RAMA: the borrower's close, verified metrics, the fund view, rules R1-R14, the card checks and publication. No model
or network call: the classifier is off, PRISM isn't installed, and the cards are given."""
import os
import shutil
import tempfile
import unittest
from unittest import mock


class RamaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="rama-test-")
        cls.env = mock.patch.dict(os.environ, {"RAMA_WORK": os.path.join(cls.dir, "work"), "RAMA_STATE": os.path.join(cls.dir, "state.json"),
                                               "BOB_RUNS_DIR": os.path.join(cls.dir, "runs"), "PRISMTRACE_API_KEY": "", "PRISMTRACE_PROJECT_ID": "",
                                               "PRISM_API_KEY": "", "PRISM_PROJECT_ID": "", "BOB_HACKATHON": "0", "NICRRON_API_KEY": ""})
        cls.env.start()
        import importlib
        from rama import close as CL, pipeline as P
        importlib.reload(CL)
        importlib.reload(P)
        cls.CL, cls.P = CL, P
        CL.reset()
        cls.first = CL.run(ask_model=False)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_the_close_records_the_known_vendor_and_leaves_the_rest_to_a_person(self):
        c = self.first
        self.assertEqual([(a["kind"], a["to"]) for a in c["applied"]], [("create", "Power & Cooling")])
        self.assertIn("line:S1000-09-007", c["applied"][0]["citations"])
        checks = sorted(f["check"] for f in c["final"]["findings"] if f["severity"] == "blocker")
        self.assertEqual(checks, ["pik_split", "unrecorded"])
        split = next(f for f in c["final"]["findings"] if f["check"] == "pik_split")
        self.assertEqual((split["fix"]["accrued_cents"], split["fix"]["cash_cents"], split["fix"]["pik_cents"]), (575000000, 400000000, 175000000))
        self.assertTrue(any(r.startswith("record:") for r in split["refs"]) and any(r.startswith("line:") for r in split["refs"]))
        self.assertFalse([f for f in c["final"]["findings"] if f["check"] == "lender_difference"])   # explained by the split
        self.assertTrue(all(r["difference"] == 0 for r in c["final"]["recons"]))
        self.assertNotIn("QuickBooks", str(c["final"]["findings"]))

    def test_metrics_are_held_until_their_evidence_ties_then_verified(self):
        from rama import metrics as MX
        m = MX.by_key(MX.compute(dict(self.first, _september_lines=[])))
        self.assertTrue(m["cash"]["verified"])
        self.assertFalse(m["ebitda_run_rate"]["verified"])
        self.assertFalse(m["net_debt_ebitda_x"]["verified"])
        split = next(f for f in self.first["final"]["findings"] if f["check"] == "pik_split")
        fee = next(f for f in self.first["final"]["findings"] if f["check"] == "unrecorded")
        self.assertEqual(fee["amount_cents"], -1480000)                # the unsupported fee
        self.CL.resolve(split, {"action": "accept_pik_split"})
        self.CL.resolve(fee, {"action": "leave_open", "note": "no support"})
        after = self.CL.run(ask_model=False)
        self.assertEqual([f["check"] for f in after["final"]["findings"] if f["severity"] == "blocker"], ["unrecorded"])   # stays in plain sight
        self.assertEqual(next(w for w in after["final"]["workpapers"] if "L2" in w["account"])["status"], "tied")
        self.assertFalse(MX.by_key(MX.compute(dict(after, _september_lines=[])))["ebitda_run_rate"]["verified"])     # not accepted: held
        m2 = MX.by_key(MX.compute(dict(after, _september_lines=[]), accepted=[fee["key"]]))
        self.assertTrue(all(x["verified"] for x in m2.values()))
        self.assertAlmostEqual(m2["net_debt_ebitda_x"]["value"], 6.32, places=2)
        self.assertAlmostEqual(m2["ebitda_interest_x"]["value"], 2.273, places=3)
        self.assertEqual(m2["l2_principal_lender"]["value"], 603.5)
        self.assertEqual(m2["l2_pik_to_date"]["value"], 31.5)


class RuleTests(unittest.TestCase):
    def setUp(self):
        from rama import fund as F
        self.metrics = {"company": {}, "metrics": [
            {"key": "l2_principal_lender", "value": 603.5, "verified": True}, {"key": "net_debt_ebitda_x", "value": 6.32, "verified": True},
            {"key": "ebitda_interest_x", "value": 2.273, "verified": True}, {"key": "l2_pik_to_date", "value": 31.5, "verified": True}],
            "tenant_mix": [{"tenant": "Hyperscaler Tenant A", "proxy": "ORCL", "share": 0.6}, {"tenant": "Hyperscaler Tenant B", "proxy": "MSFT", "share": 0.3},
                           {"tenant": "Enterprise customers", "proxy": None, "share": 0.1}]}
        self.fund = F.build(self.metrics)
        self.cap = {
            "ORCL": {"sp_rating": "BBB-", "sp_outlook": "Stable", "sp_last_action": "Downgrade", "sp_last_action_date": "2026-07-09", "ebitda_ltm_usd_m": 34433.0,
                     "net_debt_ebitda_x": 3.498, "ebitda_interest_x": 7.397, "_raw": {"net_debt_ebitda_x": "3.498", "ebitda_interest_x": "7.397"}},
            "MSFT": {"sp_rating": "AAA", "sp_outlook": "Stable", "sp_last_action": "New Rating", "sp_last_action_date": "2008-09-22", "ebitda_ltm_usd_m": 1.0,
                     "net_debt_ebitda_x": 0.258, "ebitda_interest_x": 65.3, "_raw": {"net_debt_ebitda_x": "0.258", "ebitda_interest_x": "65.3"}},
            "CRWV": {"sp_rating": "B+", "sp_outlook": "Positive", "sp_last_action": "CreditWatch/Outlook", "sp_last_action_date": "2026-04-09",
                     "ebitda_ltm_usd_m": 3789.0, "net_debt_ebitda_x": 8.222, "ebitda_interest_x": 2.987, "_raw": {"net_debt_ebitda_x": "8.222", "ebitda_interest_x": "2.987"}},
            "NBIS": {"sp_rating": "NR", "sp_outlook": "NR", "sp_last_action": "Not Rated", "sp_last_action_date": "2022-04-13", "ebitda_ltm_usd_m": 258.0,
                     "net_debt_ebitda_x": 4.681, "ebitda_interest_x": 1.921, "_raw": {"net_debt_ebitda_x": "4.681", "ebitda_interest_x": "1.921"}},
            "APLD": {"sp_rating": "B+", "sp_outlook": "Positive", "sp_last_action": "New Rating", "sp_last_action_date": "2025-11-10", "ebitda_ltm_usd_m": -124.1,
                     "net_debt_ebitda_x": None, "ebitda_interest_x": None, "_raw": {"net_debt_ebitda_x": "NM", "ebitda_interest_x": "NM"}},
        }

    def rules(self, cap=None):
        from rama import rules as R
        return {r["id"]: r for r in R.evaluate(self.fund, self.metrics, self.cap if cap is None else cap)}

    def test_the_demo_rules_fire_on_the_planted_conditions(self):
        r = self.rules()
        self.assertEqual(r["R3"]["status"], "fired")
        self.assertEqual((r["R3"]["figures"]["rating"], r["R3"]["figures"]["days_since_action"]), ("BBB-", 99))
        self.assertEqual(r["R2"]["figures"]["top_tenant"], "ORCL")
        self.assertAlmostEqual(r["R2"]["figures"]["look_through_usd_m"], 420 + 603.5 * 0.6, places=3)
        self.assertEqual([x["loan"] for x in r["R7"]["figures"]["loans"] if x["fires"]], ["L2", "L3"])
        apld = next(x for x in r["R7"]["figures"]["loans"] if x["proxy"] == "APLD")
        self.assertEqual((apld["fires"], apld["stress"]), (False, ["negative LTM EBITDA"]))   # stressed, matures after the window
        self.assertEqual(r["R11"]["figures"]["count"], 3)
        self.assertEqual(r["R12"]["figures"]["net_calls_12m_usd_m"], 45.0)
        self.assertAlmostEqual(r["R13"]["figures"]["headroom"], 0.1154, places=4)
        self.assertEqual(r["R14"]["subject"], "Loan L2: max net debt/EBITDA")
        self.assertAlmostEqual(r["R5"]["figures"]["ltv"], round(603.5 / (925 * 2.65 / 4.0), 4))
        self.assertEqual(r["R5"]["threshold"]["ltv_at_origination"], 0.65)
        self.assertEqual(r["R1"]["status"], "fired")
        self.assertEqual(r["R1"]["figures"]["non_accrual_loans"], ["L4"])
        self.assertAlmostEqual(r["R1"]["figures"]["ratio_of_nav"], round((31.5 + 7.75 + 260.0) / self.fund["nav_usd_m"], 4))

    def test_missing_market_data_is_not_evaluated_never_estimated(self):
        r = self.rules(cap={})
        self.assertEqual(r["R3"]["status"], "not_evaluated")
        for rid in ("R6", "R8", "R9", "R10"):
            self.assertEqual(r[rid]["status"], "not_evaluated")
            self.assertTrue(r[rid]["missing"])

    def test_unverified_borrower_figures_are_held(self):
        from rama import fund as F
        held = dict(self.metrics, metrics=[dict(m, verified=False) for m in self.metrics["metrics"]])
        self.fund = F.build(held)
        r = self.rules()
        tests = [t for t in r["R14"]["figures"]["tests"] if t["loan"] == "L2"]
        self.assertTrue(tests and all(t["verified"] is False for t in tests))
        self.assertNotIn("L2", r["R14"]["loans"])                      # an unverified L2 never fires the rule


class CardCheckTests(unittest.TestCase):
    def setUp(self):
        self.rule = {"id": "R12", "name": "LP liquidity", "subject": "Hudson State Teachers' Pension (synthetic LP)", "status": "fired",
                     "figures": {"unfunded_usd_m": 95.0, "calls_12m_usd_m": 57.0, "distributions_12m_usd_m": 12.0, "net_calls_12m_usd_m": 45.0},
                     "threshold": {"liquidity_floor_usd_m": 40.0, "basis": "LP policy"},
                     "inputs": [{"label": "Unfunded commitment", "source": "LP capital account (synthetic)", "as_of": "2026-09-30"}]}

    def test_a_number_the_rule_did_not_compute_is_caught(self):
        from rama import cards as C
        self.assertEqual(C.check_numbers("Net calls of $45.0M exceed the $40.0M floor as of 2026-09-30.", self.rule), [])
        self.assertEqual(C.check_numbers("Net calls of $47.5M exceed the floor.", self.rule), ["47.5"])

    def test_the_blocklist_catches_advice(self):
        from rama import cards as C
        self.assertTrue(C.BLOCKLIST.search("you should reduce your commitment"))
        self.assertTrue(C.BLOCKLIST.search("Consider rebalancing"))
        self.assertIsNone(C.BLOCKLIST.search("Net calls exceed the LP's liquidity floor."))


class PublicationTests(unittest.TestCase):
    def test_only_approved_publishable_cards_reach_the_destination(self):
        d = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"RAMA_STATE": os.path.join(d, "state.json"), "BOB_RUNS_DIR": os.path.join(d, "runs"),
                                          "PRISMTRACE_API_KEY": "", "PRISMTRACE_PROJECT_ID": ""}):
            import importlib
            from rama import pipeline as P
            importlib.reload(P)
            s = P._blank()
            base = {"rule_name": "x", "subject": "s", "facts": [], "sources": [], "loans": [], "exposure_usd_m": None, "title": "t", "body": "b"}
            s["cards"] = [dict(base, id="a", rule_id="R1", publishable=True, review={"status": "pending"}),
                          dict(base, id="b", rule_id="R2", publishable=True, review={"status": "rejected"}),
                          dict(base, id="c", rule_id="R3", publishable=False, review={"status": "pending"}, title=None, body=None)]
            P.save(s)
            dest = P.approve_package()
            self.assertEqual([c["id"] for c in dest["published"]], ["a"])
            self.assertEqual(P.load()["package"]["status"], "approved")
        shutil.rmtree(d, ignore_errors=True)
