"""The standard records every client file is converted into, and the column names each field is known by.

A record type lists its fields as canonical name -> kind. Kinds: id, text, date, time, money, int, bool, list.
FIELD_ALIASES maps a canonical field to the header spellings seen in exports (normalized: lower case, words joined by
'_'). A header ending in `_cents` (or 'cents') is read as integer cents; any other money header as dollars.

Adding a new export format normally means adding aliases here, not code. A layout the registry can't place is proposed
to the owner as a column mapping and, once approved, remembered for that client (see mapping.py).
"""
import re

FIELD_ALIASES = {
    "tenant_id": ["tenant_id", "tenant", "company_id", "company", "client_id", "org_id", "organization_id", "entity_id", "entity", "org"],
    "realm_id": ["realm_id", "realm", "qbo_realm", "company_realm"],
    "date": ["date", "txn_date", "transaction_date", "posted", "posted_date", "posting_date", "raw_date", "doc_date", "invoice_date", "bill_date", "payment_date", "run_date", "pay_date", "entry_date", "effective_date", "paydate", "dtposted", "timestamp", "accepted_at", "accepted_service_date", "as_of_date", "purchase_date", "acquired_date"],
    "amount": ["amount_cents", "amount", "raw_amount", "signed_cents", "signed_amount", "total", "value", "amount_usd", "cents", "amount_minor", "open_minor", "trnamt"],
    "debit": ["debit", "debit_cents", "debits", "withdrawal", "withdrawals", "money_out"],
    "credit": ["credit", "credit_cents", "credits", "deposit", "deposits", "money_in"],
    "description": ["description", "memo", "details", "narrative", "payee", "name", "reference_text"],
    "account": ["account", "account_number", "acct", "gl_account", "account_id", "account_no", "code", "account_code"],
    "account_name": ["account_name", "name"],
    "account_type": ["type", "account_type", "classification"],
    "event_id": ["event_id", "transaction_id", "txn_id", "journal_id", "je_id", "event_ref"],
    "entry_id": ["entry_id", "time_entry_id", "timesheet_id", "punch_id"],
    "object_type": ["object_type", "transaction_type", "txn_type", "type"],
    "source_id": ["source_id", "num", "doc_number", "reference", "ref", "document_number", "source_ref", "object_id"],
    "dimension": ["dimension", "class", "job", "site", "location", "department_code", "job_id"],
    "memo": ["memo", "note", "notes"],
    "version": ["version", "revision", "rev"],
    "line_id": ["line_id", "line", "line_no", "line_number", "row_id"],
    "invoice_id": ["source_key", "object_legacy_external_key", "legacy_external_key", "external_key", "invoice_key", "original_external_key", "invoice_id", "invoice", "invoice_number", "invoice_no", "inv_id"],
    "qbo_id": ["qbo_id", "quickbooks_id", "external_id"],
    "customer_id": ["customer_id", "customer", "customer_name", "client"],
    "vendor_id": ["vendor_id", "vendor", "supplier", "supplier_id", "vendor_name"],
    "service_date": ["service_date", "work_date", "completed_on", "service_effective_date"],
    "due_date": ["due_date", "due"],
    "pretax": ["pretax_cents", "pretax", "subtotal", "subtotal_cents", "net_of_tax", "net_usd", "money_net_minor", "net_minor", "net_cents"],
    "tax": ["tax_cents", "tax", "sales_tax", "sales_tax_cents", "tax_usd", "money_tax_minor", "tax_minor"],
    "total": ["total_cents", "total", "invoice_total", "amount_due", "gross_usd", "money_total_minor", "total_minor"],
    "tax_code": ["tax_code", "tax_rate_code"],
    "status": ["status", "state", "service_status"],
    "tag": ["tag", "work_type", "tax_category", "category"],
    "taxable_base": ["taxable_base_cents", "taxable_base", "taxable_amount"],
    "department": ["department", "business_unit", "division", "invoice_kind", "work_kind", "sale_type"],
    "tips": ["tips_cents", "tips", "tip", "tip_cents", "card_tips", "card_tips_cents", "gratuity", "gratuities", "gratuity_cents"],
    "labor": ["labor_cents", "labor"],
    "at_cost_materials": ["at_cost_materials_cents", "materials_cents", "at_cost_materials"],
    "building_family_count": ["building_family_count", "family_count", "units"],
    "certificate_id": ["certificate_id", "certificate", "exemption_certificate"],
    "quantity": ["quantity", "qty", "hours", "quantity_change", "qty_change"],
    "unit_cost": ["unit_cost_cents", "unit_cost", "cost_each_cents"],
    "application_id": ["application_id", "deposit_application_id"],
    "hours": ["regular_hours", "hours_worked", "hours"],
    "overtime_hours": ["overtime_hours", "ot_hours"],
    "approved_by": ["approved_by", "approver"],
    "pay_date": ["scheduled_pay_date", "pay_date", "paid_on"],
    "remittance_id": ["remittance_id", "deposit_reference"],
    "payroll_month": ["payroll_month", "wage_month"],
    "employee_withheld": ["employee_withheld_cents", "employee_withheld", "withheld_cents", "withholding_cents"],
    "employer_burden": ["employer_burden_cents", "employer_burden", "employer_tax_cents", "employer_taxes_cents"],
    "unit_rate": ["unit_rate_cents", "unit_rate", "rate", "unit_price"],
    "payment_id": ["payment_id", "payment", "payment_number", "receipt_id"],
    "method": ["method", "payment_method", "payment_type", "tender"],
    "unapplied": ["unapplied_cents", "unapplied"],
    "applied": ["applied_cents", "applied", "amount_applied"],
    "settlement_id": ["settlement_id", "payout_id", "batch_id", "settlement", "batch"],
    "gross": ["gross_cents", "gross", "gross_amount"],
    "fee": ["fee_cents", "fee", "fees", "processing_fee"],
    "refund": ["refund_cents", "refund", "refunds"],
    "reserve_withheld": ["reserve_withheld_cents", "reserve_withheld", "reserve_held"],
    "reserve_released": ["reserve_released_cents", "reserve_released"],
    "net": ["net_cents", "net", "net_amount", "net_pay_cents"],
    "bank_trace": ["bank_trace", "trace", "trace_id", "bank_reference"],
    # the synthetic settlement-activity export contract (docs/82 §4): one row per sale, refund, fee, adjustment, reserve
    "activity_id": ["activity_id", "activity_ref", "activity_reference"],
    "activity_kind": ["activity_kind", "activity_type", "entry_kind"],
    "currency": ["currency", "currency_code", "ccy"],
    "settlement_date": ["settlement_date", "payout_date", "expected_payout_date"],
    "deposit_id": ["deposit_id", "advance_id"],
    "job_id": ["job_id", "work_order_id", "job_number"],
    "lender": ["lender", "finance_company", "financing_partner"],
    "invoice_ids": ["invoice_ids", "invoices"],
    "buydown": ["buydown_cents", "buydown"],
    "net_funding": ["net_funding_cents", "net_funding", "funded_amount"],
    "fee_mode": ["fee_mode"],
    "fee_invoice_id": ["fee_invoice_id"],
    "fee_paid_date": ["fee_paid_date"],
    "bill_id": ["bill_id", "bill", "bill_number", "purchase_id"],
    "vendor_invoice": ["vendor_invoice", "vendor_invoice_number", "supplier_invoice"],
    "received_date": ["received_date", "received"],
    "payment_account": ["payment_account", "paid_from", "pay_account", "ap_account"],
    "ownership": ["ownership", "owner_flag", "business_or_personal"],
    "destination": ["destination", "deliver_to", "ship_to"],
    "credit_id": ["credit_id", "vendor_credit_id", "credit_memo"],
    "claim_id": ["claim_id", "claim"],
    "run_id": ["run_id", "payroll_id", "pay_run", "check_date_id", "run"],
    "service_start": ["service_start", "period_start", "pay_period_start"],
    "service_end": ["service_end", "period_end", "pay_period_end"],
    "employee_withheld": ["employee_withheld_cents", "employee_withheld", "withholding", "employee_taxes", "withheld", "withheld_cents",
                          "withholding_cents", "employee_withholding_cents", "employee_taxes_cents"],
    "employer_burden": ["employer_burden_cents", "employer_burden", "employer_taxes", "burden", "employer_cents", "employer", "employer_tax_cents",
                        "employer_tax", "employer_taxes_cents", "employer_payroll_tax_cents"],
    "reimbursement": ["reimbursement_cents", "reimbursement", "reimbursements"],
    "provider_fee": ["provider_fee_cents", "provider_fee"],
    "technician_base": ["technician_base_cents", "technician_base", "technician_wages", "technicians", "technician", "tech"],
    "office": ["office_cents", "office", "office_wages"],
    "commission": ["commission_cents", "commission", "commissions"],
    "wages": ["wages_cents", "wages"],
    "burden": ["burden_cents", "burden"],
    "allocation_version": ["allocation_version"],
    "provider_overtime_review": ["provider_overtime_review", "overtime_review"],
    "employee_id": ["employee_id", "employee", "worker", "technician", "worker_id"],
    "start_local": ["start_local", "start", "clock_in", "start_time"],
    "end_local": ["end_local", "end", "clock_out", "end_time"],
    "timezone": ["timezone", "tz", "time_zone"],
    "elapsed_seconds": ["elapsed_seconds", "seconds", "duration_seconds"],
    "approved": ["approved", "is_approved"],
    "earning": ["earning", "earning_type", "pay_type"],
    "rate_per_hour": ["rate_cents_per_hour", "hourly_rate", "rate_per_hour"],
    "principal": ["principal_cents", "principal"],
    "interest": ["interest_cents", "interest"],
    "cohort_id": ["cohort_id", "cohort", "plan_group"],
    "customer_count": ["customer_count", "members"],
    "plan": ["plan", "plan_name"],
    "start_date": ["start_date", "effective_from", "valid_from"],
    "end_date": ["end_date"],
    "paid": ["paid_cents", "paid", "amount_paid"],
    "visits_per_customer": ["visits_per_customer"],
    "allocation_per_visit": ["allocation_per_visit_cents", "allocation_per_visit"],
    "cancellation_terms": ["cancellation_terms"],
    "policy": ["policy"],
    "visit_id": ["visit_id", "visit"],
    "completed": ["completed", "done"],
    "earned": ["earned_cents", "earned"],
    "distributor": ["distributor", "supplier_name"],
    "submitted_date": ["submitted_date", "submitted"],
    "evidence_id": ["evidence_id", "evidence", "acknowledgement"],
    "approved_amount": ["approved_cents", "approved_amount"],
    "labor_actual": ["labor_actual_cents", "labor_actual"],
    "labor_cost_status": ["labor_cost_status"],
    "manufacturer": ["manufacturer", "oem"],
    "paid_date": ["paid_date", "date_paid"],
    "work_order": ["work_order"],
    "signed_date": ["signed_date", "signed"],
    "billable": ["billable"],
    "completed_date": ["completed_date", "completion_date"],
    "equipment_type": ["equipment_type", "equipment"],
    "tax_evidence_id": ["tax_evidence_id"],
    "quoted": ["quoted_cents", "quoted", "quote"],
    "movement_id": ["movement_id", "movement"],
    "item_id": ["item_id", "item", "sku", "product_code", "product", "item_code", "code"],
    "unit": ["unit", "uom", "unit_of_measure"],
    "value": ["value_cents", "value", "extended_cost"],
    "kind": ["kind", "movement_type", "operation", "reason"],
    "reference": ["reference", "ref", "remittance_id"],
    "retainage": ["retainage_cents", "retainage", "retention_cents", "retention", "retainage_withheld_cents"],
    "quarter": ["quarter", "period", "liability_month", "tax_month"],
    "asset_id": ["asset_id", "asset"],
    "cost": ["cost_cents", "cost"],
    "financed": ["financed_cents", "financed"],
    "cash": ["cash_cents", "cash"],
    "in_service": ["in_service", "placed_in_service", "in_service_month", "in_service_date"],
    "useful_life": ["useful_life_months", "life_months", "useful_life"],
    "salvage": ["salvage_cents", "residual_cents", "salvage", "residual_value_cents"],
    "accumulated": ["accumulated_depreciation_cents", "accumulated_depreciation"],
    "asset_account": ["asset_account", "gl_account"],
    "monthly_depreciation": ["monthly_depreciation_cents", "monthly_depreciation"],
    "schedule_id": ["schedule_id"],
    "gross_pay": ["gross_cents", "gross", "gross_pay", "gross_earned_cents", "gross_earned"],
    "refund_id": ["refund_id", "refund_number"],
    "funded": ["net_and_tax_funded_cents", "net_and_tax_funded", "total_funded", "funding", "funded"],
    "source_system": ["source_system", "system", "object_system", "original_system"],
    "record_kind": ["record_kind", "event", "event_type"],
    "new_id": ["new_id", "migrated_id"],
    "truck": ["truck", "vehicle", "van"],
    "scale_type": ["scale_type", "weighing"],
    "transaction_kind": ["transaction_kind", "trntype"],
    "tax_status": ["tax_status", "tax_classification", "tax_treatment"],
    "contract_id": ["contract_id", "contract", "agreement_id", "contract_number"],
    "service_period": ["service_period", "service_month", "release_period", "earned_period"],
    "earned_release": ["earned_release_cents", "earned_release", "release_cents", "earned_cents", "amount_earned", "recognized_cents"],
    "opening_contract": ["opening_contract_cents", "opening_contract", "contract_value", "contract_total_cents"],
    "support_source": ["support_source", "supported_by", "support", "support_document", "evidence_source"],
    # a receipt list: one row per receipt (docs/92 §4, 1.4); support for the card or bank line it's paid by, never booked itself
    "receipt_id": ["receipt_id", "receipt", "receipt_no", "receipt_number", "receipt_ref"],
    "payment_account": ["payment_account", "paid_with", "payment_method_account", "card_account", "paid_from"],
    # statement summaries: one row per account and statement period, with the balances a reconciliation ties to
    "coverage_start": ["coverage_start", "period_start", "statement_start", "statement_start_date", "statement_period_start",
                       "cycle_start", "cycle_start_date", "from_date"],
    "coverage_end": ["coverage_end", "period_end", "statement_end", "statement_end_date", "statement_period_end", "statement_date",
                     "cycle_end", "cycle_end_date", "closing_date", "to_date"],
    "statement_period": ["statement_period", "period", "statement_month", "cycle_month"],
    "opening_cents": ["opening_cents", "opening_balance_cents", "opening_balance", "opening_signed_cents", "beginning_balance_cents", "beginning_balance",
                      "starting_balance", "previous_balance", "balance_forward"],
    "closing_cents": ["closing_cents", "closing_balance_cents", "closing_balance", "closing_signed_cents", "ending_balance_cents", "ending_balance",
                      "statement_balance"],
    "total_deposits": ["total_deposits", "deposits_cents", "total_deposits_cents", "total_credits", "deposits_total", "credits_or_deposits_cents"],
    "total_withdrawals": ["total_withdrawals", "withdrawals_cents", "total_withdrawals_cents", "total_debits", "withdrawals_total",
                          "charges_or_withdrawals_cents"],
    "opening_liability_cents": ["opening_liability_cents", "opening_amount_owed_cents", "opening_amount_owed", "previous_amount_owed",
                                "previous_balance_owed", "opening_balance_owed"],
    "closing_liability_cents": ["closing_liability_cents", "closing_amount_owed_cents", "closing_amount_owed", "new_balance_owed",
                                "closing_balance_owed", "amount_owed", "balance_owed"],
}

# kind per canonical field (money unless listed)
KINDS = {
    **{f: "id" for f in ("tenant_id", "realm_id", "event_id", "source_id", "line_id", "invoice_id", "qbo_id", "customer_id",
                         "vendor_id", "payment_id", "settlement_id", "bank_trace", "deposit_id", "job_id", "fee_invoice_id",
                         "bill_id", "vendor_invoice", "credit_id", "entry_id", "claim_id", "run_id", "employee_id", "cohort_id", "visit_id",
                         "evidence_id", "certificate_id", "tax_evidence_id", "movement_id", "item_id", "reference", "asset_id",
                         "schedule_id", "account", "payment_account", "dimension", "work_order", "refund_id", "contract_id",
                         "activity_id", "receipt_id", "application_id", "remittance_id")},
    **{f: "text" for f in ("description", "account_name", "account_type", "object_type", "memo", "tax_code", "status", "tag",
                           "department", "method", "lender", "fee_mode", "ownership", "destination", "provider_overtime_review",
                           "timezone", "earning", "plan", "cancellation_terms", "policy", "distributor", "labor_cost_status",
                           "manufacturer", "equipment_type", "unit", "kind", "quarter", "service_period", "activity_kind", "currency",
                           "support_source", "approved_by", "payroll_month")},
    **{f: "date" for f in ("date", "settlement_date", "service_date", "due_date", "fee_paid_date", "received_date", "service_start", "service_end",
                           "start_date", "end_date", "submitted_date", "paid_date", "signed_date", "completed_date", "in_service",
                           "coverage_start", "coverage_end", "pay_date")},
    "useful_life": "int", "asset_account": "id",
    "statement_period": "text",
    **{f: "time" for f in ("start_local", "end_local")},
    **{f: "int" for f in ("version", "building_family_count", "allocation_version", "elapsed_seconds",
                          "customer_count", "visits_per_customer")},
    "quantity": "number", "hours": "number", "overtime_hours": "number",
    **{f: "text" for f in ("source_system", "record_kind", "truck", "scale_type", "transaction_kind", "tax_status")},
    "new_id": "id",
    **{f: "bool" for f in ("approved", "completed", "billable")},
    "invoice_ids": "list",
}


def kind_of(field):
    return KINDS.get(field, "money")


# record type -> (required fields, optional fields, identity fields). The first matching type with the best coverage wins.
TYPES = {
    "chart": (("account", "account_name", "account_type"), (), ("account",)),
    "gl_line": (("event_id", "date", "account", "amount"), ("object_type", "source_id", "dimension", "memo", "version",
                                                            "tenant_id", "realm_id", "debit", "credit"), ("event_id",)),
    "bank_line": (("date", "amount"), ("line_id", "account", "description", "tenant_id", "realm_id", "debit", "credit", "reference"), ("line_id",)),
    "invoice": (("invoice_id", "date", "total"), ("customer_id", "tenant_id", "realm_id", "qbo_id", "version", "dimension", "retainage",
                "source_system", "source_id", "record_kind", "tax_status",
                "service_date", "due_date", "pretax", "tax", "tax_code", "status", "tag", "taxable_base", "department", "labor", "tips",
                "at_cost_materials", "building_family_count", "certificate_id"), ("invoice_id",)),
    "invoice_line": (("invoice_id", "line_id", "pretax"), ("tenant_id", "realm_id", "date", "description", "quantity",
                     "unit_rate", "tax", "total", "dimension", "taxable_base", "item_id", "source_system", "source_id"), ("line_id",)),
    "payment": (("payment_id", "date", "amount"), ("method", "invoice_id", "tenant_id", "realm_id", "customer_id", "status", "unapplied"),
                ("payment_id",)),
    "application": (("payment_id", "invoice_id", "applied"), ("tenant_id", "realm_id", "date", "customer_id", "dimension"),
                    ("payment_id", "invoice_id")),
    "settlement": (("settlement_id", "gross", "net"), ("tenant_id", "realm_id", "date", "payment_id", "fee", "refund",
                   "reserve_withheld", "reserve_released", "bank_trace", "status"), ("settlement_id",)),
    "reserve_release": (("settlement_id", "date", "amount"), ("tenant_id", "realm_id"), ("settlement_id", "date")),
    "settlement_activity": (("activity_id", "date", "settlement_id", "activity_kind", "amount"),
                            ("currency", "settlement_date", "bank_trace", "tenant_id", "realm_id", "version", "description"), ("activity_id",)),
    "customer_deposit": (("deposit_id", "date", "amount"), ("tenant_id", "realm_id", "customer_id", "job_id"), ("deposit_id",)),
    "lender_funding": (("payment_id", "lender", "gross", "fee"), ("tenant_id", "realm_id", "date", "invoice_ids", "buydown",
                       "net_funding", "fee_mode", "fee_invoice_id", "fee_paid_date", "bank_trace"), ("payment_id",)),
    "bill": (("bill_id", "vendor_id", "date", "amount"), ("tenant_id", "realm_id", "vendor_invoice", "received_date", "due_date",
             "payment_account", "dimension", "description"), ("bill_id",)),
    "bill_line": (("bill_id", "line_id", "amount"), ("tenant_id", "realm_id", "date", "description", "ownership", "destination"),
                  ("line_id",)),
    "bill_payment": (("payment_id", "bill_id", "amount"), ("tenant_id", "realm_id", "date"), ("payment_id",)),
    "bill_credit": (("credit_id", "bill_id", "amount"), ("tenant_id", "realm_id", "date", "claim_id"), ("credit_id",)),
    "payroll_run": (("run_id", "date", "gross_pay"), ("net", "funded", "employee_id", "tenant_id", "realm_id", "status",
                    "service_start", "service_end", "employee_withheld", "employer_burden", "reimbursement", "provider_fee",
                    "technician_base", "office", "commission"), ("run_id",)),
    "payroll_allocation": (("run_id", "dimension", "wages"), ("tenant_id", "realm_id", "date", "burden", "total",
                           "allocation_version", "employee_id", "quantity", "line_id"), ("line_id",)),
    "commission": (("run_id", "commission"), ("tenant_id", "realm_id", "date", "provider_overtime_review"), ("run_id",)),
    "time_entry": (("entry_id", "employee_id", "start_local"), ("tenant_id", "realm_id", "date", "version", "run_id",
                   "dimension", "end_local", "timezone", "elapsed_seconds", "approved", "earning", "rate_per_hour", "gross_pay"),
                   ("entry_id",)),
    "cutoff_time": (("entry_id", "employee_id", "service_date", "gross_pay", "burden"), ("tenant_id", "realm_id", "date",
                    "run_id", "approved", "dimension"), ("entry_id",)),
    "loan_activity": (("reference", "date", "principal", "interest"), ("tenant_id", "realm_id"), ("reference", "date")),
    "membership_cohort": (("cohort_id", "paid", "visits_per_customer"), ("tenant_id", "realm_id", "date", "customer_count",
                          "plan", "start_date", "end_date", "tax", "allocation_per_visit", "cancellation_terms", "policy"),
                          ("cohort_id",)),
    "membership_visit": (("cohort_id", "visit_id", "earned"), ("tenant_id", "realm_id", "date", "completed"), ("visit_id",)),
    "deferred_schedule": (("contract_id", "service_period", "earned_release"), ("tenant_id", "realm_id", "date", "opening_contract",
                          "policy"), ("contract_id", "service_period")),
    "rebate_claim": (("claim_id", "bill_id", "amount"), ("tenant_id", "realm_id", "date", "job_id", "distributor", "status",
                     "submitted_date", "evidence_id"), ("claim_id",)),
    "warranty_claim": (("claim_id", "approved_amount"), ("tenant_id", "realm_id", "date", "labor_actual", "labor_cost_status",
                       "status", "manufacturer", "paid_date", "work_order"), ("claim_id",)),
    "st8": (("job_id", "certificate_id", "signed_date"), ("tenant_id", "realm_id", "date", "status", "customer_id"),
            ("certificate_id",)),
    "job": (("job_id", "customer_id", "status", "completed_date"), ("tenant_id", "realm_id", "date", "billable", "invoice_id",
            "department", "equipment_type", "building_family_count", "taxable_base", "tax_evidence_id", "quoted"), ("job_id",)),
    "stock_movement": (("movement_id", "item_id"), ("tenant_id", "realm_id", "date", "unit", "quantity", "kind", "value", "unit_cost", "source_id",
                       "destination"), ("movement_id",)),
    "tax_remittance": (("reference", "date", "amount"), ("tenant_id", "realm_id", "quarter"), ("reference",)),
    # a customer's deposit applied to the invoice it was taken for (on acceptance): the deposit liability settles the receivable
    "deposit_application": (("application_id", "invoice_id", "amount"), ("tenant_id", "realm_id", "date", "dimension", "deposit_id",
                            "customer_id"), ("application_id",)),
    # approved hours by day (a timesheet summary, not clock punches): the pay they earn, and when it's paid
    "approved_time": (("entry_id", "employee_id", "date", "gross_pay"), ("tenant_id", "realm_id", "hours", "overtime_hours", "rate_per_hour",
                      "department", "pay_date", "approved_by"), ("entry_id",)),
    # a payroll tax deposit with its parts: the employees' withholding and the employer's tax, for a payroll month
    "payroll_tax_remittance": (("remittance_id", "date", "amount"), ("tenant_id", "realm_id", "payroll_month", "employee_withheld",
                               "employer_burden"), ("remittance_id",)),
    "stock_quantity": (("movement_id", "date", "kind", "quantity", "unit", "item_id"), ("tenant_id", "realm_id", "truck",
                       "scale_type", "description"), ("movement_id",)),
    "product_mapping": (("item_id", "department", "start_date"), ("source_system", "memo", "tenant_id", "realm_id"),
                        ("source_system", "item_id", "start_date")),
    "migration_balance": (("invoice_id", "amount", "record_kind"), ("new_id", "source_system", "date", "tenant_id",
                          "realm_id"), ("invoice_id",)),
    "asset": (("asset_id", "cost"), ("tenant_id", "realm_id", "date", "financed", "cash", "in_service", "useful_life", "salvage", "accumulated",
               "asset_account",
              "monthly_depreciation"), ("asset_id",)),
    # what supports an opening balance: the prior return's balance sheet, a loan statement, an aging (close.opening_ties)
    "opening_support": (("account", "amount", "support_source"), ("date", "description", "tenant_id", "realm_id"),
                        ("account", "support_source")),
    "credit_memo": (("credit_id", "invoice_id", "total"), ("tenant_id", "realm_id", "date", "customer_id", "pretax", "tax",
                    "status", "version"), ("credit_id",)),
    "refund": (("refund_id", "credit_id", "amount"), ("tenant_id", "realm_id", "date", "customer_id", "method", "status"),
               ("refund_id",)),
    # a trial balance: an account and its balance (one signed column, or debit and credit), with or without a date. It
    # books nothing: it's the opening balances when a person says so (product/fileroles.py), or a check (docs/92 §4, 1.4)
    "trial_balance": (("account", "amount"), ("account_name", "debit", "credit", "date"), ("account",)),
    # a list of receipts: support, linked to the line that paid it; never read as statement lines (docs/92 §4, 1.4)
    "receipt_row": (("receipt_id", "date", "amount"), ("vendor_id", "description", "payment_account", "dimension", "tax"), ("receipt_id",)),
    # a statement summary as a table (the same records a statement's JSON or PDF gives): a bank or savings account's
    # opening and closing balance for the period, or a card's amount owed. A statement month stands in for its dates.
    "statement_control": (("account", "coverage_end", "closing_cents"), ("coverage_start", "statement_period", "opening_cents",
                          "total_deposits", "total_withdrawals", "tenant_id", "realm_id"), ("account", "coverage_end")),
    "card_cycle_control": (("coverage_end", "closing_liability_cents"), ("account", "coverage_start", "statement_period",
                           "opening_liability_cents", "tenant_id", "realm_id"), ("account", "coverage_end")),
}

# record types read from a statement summary, and the field whose month gives the period's dates when the file has no dates
STATEMENT_TYPES = {"statement_control": "statement_period", "card_cycle_control": "statement_period"}

# A one-object control document (JSON, XML) keeps its own keys, and a card statement's names its cycle's dates start and
# end (a summary table's row gets both names), so MUST's fields are looked for under these names in such a document
CONTROL_KEYS = {"card_cycle_control": {"coverage_start": "start", "coverage_end": "end"}}

# Fields a row can't do without (identity and the main date/amount). Everything else may be blank: blank is unknown.
MUST = {
    "chart": ("account",), "gl_line": ("event_id", "date", "account", "amount"), "bank_line": ("date", "amount", "account"),
    "invoice": ("invoice_id", "date", "total"), "invoice_line": ("invoice_id", "pretax"),
    "payment": ("payment_id", "date", "amount"), "application": ("payment_id", "invoice_id", "applied"),
    "settlement": ("settlement_id", "gross", "net"), "reserve_release": ("settlement_id", "date", "amount"),
    "settlement_activity": ("activity_id", "settlement_id", "activity_kind", "amount"),
    "customer_deposit": ("deposit_id", "date", "amount"), "lender_funding": ("payment_id", "gross"),
    "bill": ("bill_id", "date", "amount"), "bill_line": ("bill_id", "amount"), "bill_payment": ("payment_id", "bill_id", "amount"),
    "bill_credit": ("credit_id", "amount"), "payroll_run": ("run_id", "date", "gross_pay"), "payroll_allocation": ("run_id", "wages"),
    "commission": ("run_id",), "time_entry": ("entry_id", "employee_id"), "cutoff_time": ("entry_id",),
    "loan_activity": ("reference", "date"), "membership_cohort": ("cohort_id",), "membership_visit": ("visit_id",),
    "deferred_schedule": ("contract_id", "service_period", "earned_release"),
    "rebate_claim": ("claim_id", "amount"), "warranty_claim": ("claim_id",), "st8": ("certificate_id",), "job": ("job_id",),
    "stock_movement": ("movement_id", "item_id"), "deposit_application": ("application_id", "invoice_id", "amount"),
    "approved_time": ("entry_id", "employee_id", "date", "gross_pay"), "payroll_tax_remittance": ("remittance_id", "date", "amount"), "tax_remittance": ("reference", "date", "amount"), "asset": ("asset_id", "cost"),
    "credit_memo": ("credit_id", "invoice_id", "total"), "refund": ("refund_id", "amount"),
    "stock_quantity": ("movement_id", "date", "quantity", "unit"), "product_mapping": ("item_id", "department", "start_date"),
    "migration_balance": ("invoice_id", "amount"), "opening_support": ("account", "amount", "support_source"),
    "statement_control": ("account", "coverage_end", "closing_cents"), "card_cycle_control": ("coverage_end", "closing_liability_cents"),
    "trial_balance": ("account",), "receipt_row": ("receipt_id", "date", "amount"),
}

# An identity a file doesn't carry, built from fields it does (a supplier payment file lists the bill, not a payment
# number; a provider off-cycle report lists the worker and pay date). Counts as present for recognition.
DERIVED = {
    "bill_payment": {"payment_id": ("bill_id", "date")},
    "invoice_line": {"line_id": ("invoice_id", "item_id")},
    "payroll_run": {"run_id": ("employee_id", "date")},
    "payroll_allocation": {"line_id": ("run_id", "employee_id", "date", "dimension")},
    "tax_remittance": {"reference": ("quarter", "date")},
    "stock_quantity": {"movement_id": ("item_id", "date", "kind", "truck")},
}


def mapping_gaps(rtype, colmap):
    """The required fields a column mapping leaves without a column. An amount may come from debit and credit columns,
    an identity from the columns it's built from (DERIVED), and a statement's end date from its statement month."""
    req = TYPES[rtype][0]
    consts = set(((colmap.get("__rules") or {}).get("constants") or {}))
    colmap = {k: v for k, v in colmap.items() if not k.startswith("__")}
    missing = [f for f in req if f not in colmap and f not in consts]
    if "amount" in missing and {"debit", "credit"} <= set(colmap):
        missing.remove("amount")
    for f, parts in DERIVED.get(rtype, {}).items():
        if f in missing and parts[0] in colmap and any(x in colmap for x in parts[1:]):
            missing.remove(f)
    if "coverage_end" in missing and STATEMENT_TYPES.get(rtype) in colmap:
        missing.remove("coverage_end")
    return missing


# JSON documents (one object): type -> keys that must be present (normalized)
JSON_TYPES = {
    "statement_control": {"account", "coverage_start", "coverage_end", "opening_cents", "closing_cents"},
    "card_cycle_control": {"account", "start", "end", "opening_liability_cents", "closing_liability_cents"},
    "coverage": {"expected_bill_count", "expected_bank_line_count"},
    "ap_control": {"opening_cents", "invoices_cents", "credits_cents", "payments_cents", "ending_cents"},
    "field_summary": {"invoice_gross_cents", "payments_including_deposit_receipts_cents"},
    "native_recon": {"accounts", "difference_cents", "status"},
    "client_policy": {"tenant_id", "realm_id", "basis"},
    "client_profile": {"entity_id", "basis"},
    "source_schema": {"money", "identity"},
}

# filename hints: used to break ties and to type empty files ("no_rows") that have no header to read
# One-object documents that the controls above recognize under other names: type -> alternative key sets
JSON_ALTERNATES = {"statement_control": [{"account", "period", "opening_cents", "closing_cents"}]}

FILE_HINTS = [
    ("chart", r"chart|coa|accounts_list"), ("gl_line", r"ledger|journal|general_ledger|trial_balance|runoff|card_cycle_lines"),
    ("bank_line", r"bank|statement_\d+_lines|transactions"), ("invoice_line", r"invoice_lines|invoice_items"),
    ("invoice", r"invoice"), ("application", r"application"), ("payment", r"payments?\b|payments?\."),
    ("settlement_activity", r"settlement_activity|payout_activity"), ("settlement", r"settlement|payout"), ("reserve_release", r"reserve"), ("customer_deposit", r"customer_deposit|advance"),
    ("lender_funding", r"lender|funding|financ"), ("bill_line", r"purchase_lines|bill_lines"), ("bill_payment", r"bill_payment"),
    ("bill_credit", r"bill_credit|vendor_credit"), ("bill", r"bills?"), ("payroll_allocation", r"payroll_alloc"),
    ("payroll_run", r"payroll_run|payroll_register"), ("commission", r"commission"), ("cutoff_time", r"cutoff"),
    ("time_entry", r"time_entr|time_correction|timesheet"), ("loan_activity", r"loan"), ("membership_visit", r"membership_visit"),
    ("membership_cohort", r"membership"), ("rebate_claim", r"rebate"), ("warranty_claim", r"warranty"), ("st8", r"st8|st-8"),
    ("job", r"jobs?\b|jobs?\.|work_orders"), ("stock_movement", r"stock|inventory"), ("tax_remittance", r"tax_remit"),
    ("asset", r"asset"), ("deferred_schedule", r"deferred"), ("opening_ar", r"opening_ar"), ("credit_memo", r"credit_memo"),
    ("refund", r"refund"), ("opening_support", r"opening_support"),
]

EMPTY_ONLY = {"opening_ar"}          # known files that have never carried rows; typed by name only


LEARNED_FILE = __import__("os").path.join(__import__("os").path.dirname(__file__), "learned_layouts.json")


@__import__("functools").lru_cache(maxsize=4)
def learned(path=None):
    """Layouts learned from people's approvals and promoted into the code (product/learning.py, docs/92 §4, 4.3): a list of
    {fingerprint, headers, kind ("mapping"|"role"), record_type, role, columns, rules}. Empty when the file is absent."""
    import json
    import os
    path = path or LEARNED_FILE
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [e for e in json.load(f).get("layouts", []) if (e.get("kind") == "mapping" and e.get("record_type") in TYPES)
                or (e.get("kind") == "role" and e.get("role"))]


def norm_header(h: str) -> str:
    h = re.sub(r"[^a-z0-9]+", "_", str(h).strip().lower()).strip("_")
    return h


# files every client sends that aren't records to book, recognized by their columns when no record type fits (docs/92 §4,
# 1.4): a list is kept for names and terms; a schedule for the rules that read such terms (and Phase 5 says which treatments
# the agents don't do yet). Each is (role, detail, the columns that must be there, columns at least one of which must be).
AUTO_ROLES = [
    ("list", {"list": "vendors"}, {"vendor_id"}, {"name", "vendor_name", "terms", "payment_terms"}),
    ("list", {"list": "customers"}, {"customer_id"}, {"name", "customer_name", "terms", "billing_address"}),
    ("list", {"list": "employees"}, {"employee_id"}, {"name", "employee_name", "role", "pay_frequency", "title"}),
    ("list", {"list": "projects"}, {"job_id"}, {"contract_cents", "contract_value", "contract_value_cents", "estimated_cost_cents", "planned_completion"}),
    ("schedule", {"schedule": "loan"}, {"loan_id"}, {"opening_principal_cents", "closing_principal_cents", "principal_paid_cents", "interest_paid_cents",
                                                     "annual_interest_rate", "opening_principal"}),
    ("schedule", {"schedule": "insurance"}, {"policy_id"}, {"premium_cents", "premium", "coverage_start", "coverage_end", "total_premium_cents"}),
    # opening and supporting lists a client's handover carries (QA audit): read as the schedules they are
    ("schedule", {"schedule": "opening open items"}, {"document_id"}, {"open_cents", "aging_bucket", "days_past_due", "settled_or_credited_cents"}),
    ("schedule", {"schedule": "service contracts"}, {"contract_id"}, {"coverage_months", "deferred_cents", "earned_to_date_cents", "recognition"}),
    ("schedule", {"schedule": "processor captures"}, {"capture_id"}, {"scheduled_settlement_date", "gross_cents", "net_cents"}),
    ("schedule", {"schedule": "coverage log"}, {"coverage_id"}, {"coverage_month", "visit_completed"}),
    ("schedule", {"schedule": "work orders"}, {"work_order_id"}, {"customer_accepted", "work_performed", "sku_issued"}),
    ("schedule", {"schedule": "card refunds"}, {"refund_id"}, {"original_receipt_id"}),
    ("schedule", {"schedule": "opening unpaid payroll"}, {"employee_id"}, {"unpaid_gross_cents"}),
    ("schedule", {"schedule": "transfer authorizations"}, {"transfer_id"}, {"from_account", "to_account"}),
    ("schedule", {"schedule": "card payments"}, {"payment_id"}, {"card_account"}),
    ("schedule", {"schedule": "cost certificates"}, {"job_id"}, {"certified_cost_to_date_cents", "estimated_total_cost_cents", "engineer_certified"}),
    ("schedule", {"schedule": "asset register"}, {"asset_id"}, {"accumulated_depreciation_cents", "remaining_life_months", "monthly_depreciation_cents"}),
]


# columns that make a table a record of events, not a list: another document's id, or an amount that happened
NOT_A_LIST = {"invoice_id", "bill_id", "payment_id", "receipt_id", "amount", "amount_cents", "total", "total_cents", "earned_amount_cents",
              "accepted_date", "paid_date"}


def auto_role(headers):
    """(role, detail) for a table whose columns say it's a list or a schedule, or None. Schedules are checked first: a
    project file with certified costs is a cost-certificate schedule, not a project list. A table that names invoices or
    amounts earned (milestone acceptances, say) is never taken for a list: a person says what it is."""
    names = {norm_header(h) for h in headers}
    for role, detail, must, any_of in sorted(AUTO_ROLES, key=lambda r: r[0] != "schedule"):
        if role == "list" and names & NOT_A_LIST:
            continue
        if must <= names and names & any_of:
            return role, detail
    return None


def hint_for(filename: str):
    base = norm_header(re.split(r"[/\\]|__", filename)[-1].rsplit(".", 1)[0])     # the file's own name, not its folders
    for t, pat in FILE_HINTS:
        if re.search(pat, base):
            return t
    return None


def monetary_table(headers):
    """Unrecognized dated amounts require review even in a small table."""
    names = {norm_header(h) for h in headers}
    return bool(names & {"date", "transaction_date", "posted_date", "invoice_date", "bill_date"}) and bool(
        names & {"amount", "amount_cents", "signed_cents", "total", "total_cents", "gross", "gross_cents", "net", "net_cents"})


def type_evidence(rtype, headers, name):
    """Generic dates and amounts cannot establish a specialized transaction type."""
    keys = {norm_header(h) for h in headers}
    if rtype == "tax_remittance":
        return bool(keys & {"quarter", "tax_period", "tax_type", "tax_authority", "liability_month", "jurisdiction"}) or hint_for(name) == rtype
    if rtype == "chart" and keys & {"debit", "credit", "balance", "signed_cents", "amount", "amount_cents", "debit_cents", "credit_cents",
                                    "balance_cents", "ending_balance", "opening_balance"}:
        return False                                      # a trial balance names accounts too: its amounts make it one
    if rtype == "payment":                                # a customer's payment: never one that names a bill or a supplier,
        if keys & {"bill_id", "vendor_id", "vendor", "supplier", "supplier_id", "card_account", "employee_withheld_cents"}:
            return False                                  # and it names a customer, an invoice or how it was paid (QA audit)
        return bool(keys & {"customer_id", "customer", "customer_name", "invoice_id", "invoice", "invoice_number", "method",
                            "payment_method", "unapplied", "unapplied_cents", "tender"})
    if rtype == "deposit_application":
        return bool(keys & {"application_id", "deposit_application_id"})
    if rtype == "approved_time":
        return bool(keys & {"regular_hours", "hours_worked", "hours"}) and not keys & {"clock_in", "start_local", "start"}
    if rtype == "payroll_tax_remittance":
        return bool(keys & {"employee_withheld_cents", "employer_burden_cents", "payroll_month"})
    if rtype in ("time_entry",) and keys & {"regular_hours", "hours_worked"} and not keys & {"clock_in", "start_local", "start"}:
        return False
    if rtype == "bank_line":
        if keys & {"from_account", "to_account", "approved_by", "transfer_id", "authorized_by"}:
            return False                                  # an authorization names who approved it: never the bank's own statement
        if keys & {"account", "account_id", "account_number", "bank_account"}:
            return True
        return not (keys & {"record_type", "counterparty", "due_date"}) and (
            bool(keys & {"debit", "credit", "withdrawals", "deposits"}) or
            ("description" in keys and "reference" not in keys) or hint_for(name) == rtype)
    return True
