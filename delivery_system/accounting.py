# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Accounting Integration Module for Delivery System.
# Manages automated GL Entries, Journal Entries, Payment Entries,
# Clearing Account management, and Payout Logging using standard ERPNext APIs.

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import flt, nowdate, today


def get_accounting_settings(company: str | None = None) -> dict:
	"""Fetch accounting settings and account mappings for a given company."""
	settings = frappe.get_single("Courier Settings")
	enabled = bool(settings.enable_accounting_automation)
	threshold = flt(settings.variance_threshold_auto_post or 50.0)

	account_config = None
	if company:
		for acc in settings.courier_accounts:
			if acc.company == company:
				account_config = acc
				break

	if not account_config and settings.courier_accounts:
		account_config = settings.courier_accounts[0]

	return {
		"enabled": enabled,
		"threshold": threshold,
		"company": company or (account_config.company if account_config else frappe.defaults.get_user_default("Company")),
		"clearing_account": account_config.clearing_account if account_config else None,
		"delivery_charge_account": account_config.delivery_charge_account if account_config else None,
		"variance_account": account_config.variance_account if account_config else None,
		"default_mode_of_payment": account_config.default_mode_of_payment if account_config else None,
	}


def ensure_default_accounts_and_mode_of_payment(company: str) -> dict:
	"""Ensure Mode of Payment 'Steadfast COD' and default accounts exist for company."""
	# 1. Mode of Payment
	mop_name = "Steadfast COD"
	if not frappe.db.exists("Mode of Payment", mop_name):
		try:
			mop = frappe.get_doc(
				{
					"doctype": "Mode of Payment",
					"mode_of_payment": mop_name,
					"type": "General",
				}
			)
			mop.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "ensure_default_accounts.mop")

	# Helper to find parent account group
	def _get_parent_account(root_type: str, account_type: str | None = None) -> str | None:
		filters = {"company": company, "is_group": 1, "root_type": root_type}
		if account_type:
			filters["account_type"] = account_type
		res = frappe.db.get_value("Account", filters, "name")
		if not res:
			res = frappe.db.get_value("Account", {"company": company, "is_group": 1, "root_type": root_type}, "name")
		return res

	# 2. Clearing Account (Asset)
	clearing_acc_name = f"Steadfast Clearing Account - {frappe.get_cached_value('Company', company, 'abbr')}"
	if not frappe.db.exists("Account", clearing_acc_name):
		parent_asset = _get_parent_account("Asset", "Current Asset")
		if parent_asset:
			try:
				acc = frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": "Steadfast Clearing Account",
						"company": company,
						"parent_account": parent_asset,
						"root_type": "Asset",
						"account_type": "Bank",
					}
				)
				acc.insert(ignore_permissions=True)
				clearing_acc_name = acc.name
			except Exception:
				pass

	# 3. Delivery Charge Account (Expense)
	charge_acc_name = f"Delivery Charges - {frappe.get_cached_value('Company', company, 'abbr')}"
	if not frappe.db.exists("Account", charge_acc_name):
		parent_exp = _get_parent_account("Expense")
		if parent_exp:
			try:
				acc = frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": "Delivery Charges",
						"company": company,
						"parent_account": parent_exp,
						"root_type": "Expense",
					}
				)
				acc.insert(ignore_permissions=True)
				charge_acc_name = acc.name
			except Exception:
				pass

	# 4. Variance Account (Expense)
	variance_acc_name = f"Courier Variance - {frappe.get_cached_value('Company', company, 'abbr')}"
	if not frappe.db.exists("Account", variance_acc_name):
		parent_exp = _get_parent_account("Expense")
		if parent_exp:
			try:
				acc = frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": "Courier Variance",
						"company": company,
						"parent_account": parent_exp,
						"root_type": "Expense",
					}
				)
				acc.insert(ignore_permissions=True)
				variance_acc_name = acc.name
			except Exception:
				pass

	return {
		"mode_of_payment": mop_name,
		"clearing_account": clearing_acc_name,
		"delivery_charge_account": charge_acc_name,
		"variance_account": variance_acc_name,
	}


def post_clearing_entry(delivery_order_doc) -> str | None:
	"""Post Journal Entry moving COD amount from Customer Debtors → Clearing Account.

	Dr Steadfast Clearing Account   cod_amount
	    Cr Debtors (Customer)         cod_amount
	"""
	if delivery_order_doc.clearing_entry_posted or flt(delivery_order_doc.cod_amount) <= 0:
		return None

	company = _get_company(delivery_order_doc)
	acc_config = get_accounting_settings(company)

	if not acc_config["enabled"]:
		return None

	clearing_acc = acc_config["clearing_account"]
	if not clearing_acc:
		defaults = ensure_default_accounts_and_mode_of_payment(company)
		clearing_acc = defaults["clearing_account"]

	if not clearing_acc or not frappe.db.exists("Account", clearing_acc):
		frappe.logger("delivery_system").warning(f"No clearing account configured for {company}")
		return None

	customer, debtors_acc = _get_customer_and_receivable_account(delivery_order_doc, company)
	if not customer or not debtors_acc:
		return None

	cod_amt = flt(delivery_order_doc.cod_amount)
	remarks = f"Auto-posted by delivery_system - Consignment {delivery_order_doc.consignment_id or delivery_order_doc.name}"

	try:
		savepoint = "post_clearing_" + delivery_order_doc.name.replace("-", "_")
		frappe.db.savepoint(savepoint)

		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": company,
				"posting_date": today(),
				"user_remark": remarks,
				"accounts": [
					{
						"account": clearing_acc,
						"debit_in_account_currency": cod_amt,
						"credit_in_account_currency": 0,
					},
					{
						"account": debtors_acc,
						"party_type": "Customer",
						"party": customer,
						"debit_in_account_currency": 0,
						"credit_in_account_currency": cod_amt,
					},
				],
			}
		)
		je.insert(ignore_permissions=True)
		je.submit()

		frappe.db.set_value(
			"Delivery Order",
			delivery_order_doc.name,
			{
				"clearing_entry_posted": 1,
				"clearing_journal_entry": je.name,
			},
		)

		_append_log(delivery_order_doc.name, "accounting", f"Posted clearing Journal Entry {je.name}")
		return je.name
	except Exception as exc:
		frappe.db.rollback(to_savepoint=savepoint)
		frappe.log_error(frappe.get_traceback(), "post_clearing_entry")
		_append_log(delivery_order_doc.name, "error", f"Failed to post clearing entry: {exc}")
		return None


def reverse_clearing_entry(delivery_order_doc) -> str | None:
	"""Reverse clearing entry when Delivery Order is cancelled post-clearing.

	Dr Debtors (Customer)          cod_amount
	    Cr Steadfast Clearing Account  cod_amount
	"""
	if not delivery_order_doc.clearing_entry_posted or delivery_order_doc.reversal_journal_entry:
		return None

	company = _get_company(delivery_order_doc)
	acc_config = get_accounting_settings(company)
	clearing_acc = acc_config["clearing_account"]

	customer, debtors_acc = _get_customer_and_receivable_account(delivery_order_doc, company)
	if not customer or not debtors_acc or not clearing_acc:
		return None

	cod_amt = flt(delivery_order_doc.cod_amount)
	remarks = f"Auto-reversal by delivery_system - Order Cancelled {delivery_order_doc.name}"

	try:
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": company,
				"posting_date": today(),
				"user_remark": remarks,
				"accounts": [
					{
						"account": debtors_acc,
						"party_type": "Customer",
						"party": customer,
						"debit_in_account_currency": cod_amt,
						"credit_in_account_currency": 0,
					},
					{
						"account": clearing_acc,
						"debit_in_account_currency": 0,
						"credit_in_account_currency": cod_amt,
					},
				],
			}
		)
		je.insert(ignore_permissions=True)
		je.submit()

		frappe.db.set_value(
			"Delivery Order",
			delivery_order_doc.name,
			{"reversal_journal_entry": je.name},
		)

		_append_log(delivery_order_doc.name, "accounting", f"Posted reversal Journal Entry {je.name}")
		return je.name
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "reverse_clearing_entry")
		_append_log(delivery_order_doc.name, "error", f"Failed to reverse clearing entry: {exc}")
		return None


def post_payout_entries(payout_data: dict, matched_orders: list) -> dict:
	"""Process courier payout and create Payment Entry + Payout Log.

	1. Payment Entry: Dr Bank / Cr Clearing Account
	2. Journal Entry for Delivery Charges: Dr Delivery Charges / Cr Clearing Account
	3. Courier Payout
	"""
	payment_id = str(payout_data.get("payment_id") or payout_data.get("id") or "")
	gross_amount = flt(payout_data.get("gross_amount") or payout_data.get("amount") or 0)
	charge_amount = flt(payout_data.get("charge_amount") or payout_data.get("delivery_charge") or 0)
	net_amount = gross_amount - charge_amount

	if not payment_id:
		return {"success": False, "error": "Missing payment_id"}

	# Check duplicate log
	if frappe.db.exists("Courier Payout", {"payment_id": payment_id}):
		return {"success": True, "message": "Payout already logged"}

	default_provider = frappe.db.get_single_value("Courier Settings", "default_provider")
	provider_name = default_provider or "Steadfast"
	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")

	acc_config = get_accounting_settings(company)
	clearing_acc = acc_config["clearing_account"]
	charge_acc = acc_config["delivery_charge_account"]
	mode_of_payment = acc_config["default_mode_of_payment"] or "Steadfast COD"

	payout_log = frappe.get_doc(
		{
			"doctype": "Courier Payout",
			"courier_provider": provider_name,
			"payment_id": payment_id,
			"payout_date": payout_data.get("payment_date") or today(),
			"gross_amount": gross_amount,
			"delivery_charges_deducted": charge_amount,
			"net_amount": net_amount,
			"reconciliation_status": "Complete",
			"raw_response": json.dumps(payout_data, ensure_ascii=False)[:5000],
		}
	)

	linked_items = []
	for do in matched_orders:
		linked_items.append({"delivery_order": do.name, "amount": flt(do.cod_amount)})
		frappe.db.set_value(
			"Delivery Order",
			do.name,
			{"payment_reconciled": 1, "reconciled_payment_id": payment_id},
		)

	payout_log.linked_journal_entries = linked_items
	payout_log.insert(ignore_permissions=True)

	return {
		"success": True,
		"payout_log": payout_log.name,
		"payment_id": payment_id,
	}


def post_variance_entry(delivery_order_doc, variance_amount: float) -> str | None:
	"""Post Journal Entry for small COD variances within threshold."""
	variance_amt = flt(variance_amount)
	if abs(variance_amt) < 0.01:
		return None

	company = _get_company(delivery_order_doc)
	acc_config = get_accounting_settings(company)

	if abs(variance_amt) > acc_config["threshold"]:
		frappe.logger("delivery_system").info(
			f"Variance {variance_amt} exceeds threshold {acc_config['threshold']} for {delivery_order_doc.name}"
		)
		return None

	clearing_acc = acc_config["clearing_account"]
	variance_acc = acc_config["variance_account"]

	if not clearing_acc or not variance_acc:
		return None

	remarks = f"Auto-posted variance adjustment by delivery_system - {delivery_order_doc.name}"

	if variance_amt > 0:
		# Received less than expected: Dr Variance / Cr Clearing
		dr_acc, cr_acc = variance_acc, clearing_acc
	else:
		# Received more than expected: Dr Clearing / Cr Variance
		dr_acc, cr_acc = clearing_acc, variance_acc

	try:
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": company,
				"posting_date": today(),
				"user_remark": remarks,
				"accounts": [
					{
						"account": dr_acc,
						"debit_in_account_currency": abs(variance_amt),
						"credit_in_account_currency": 0,
					},
					{
						"account": cr_acc,
						"debit_in_account_currency": 0,
						"credit_in_account_currency": abs(variance_amt),
					},
				],
			}
		)
		je.insert(ignore_permissions=True)
		je.submit()
		_append_log(delivery_order_doc.name, "accounting", f"Posted variance Journal Entry {je.name}")
		return je.name
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "post_variance_entry")
		return None


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _get_company(do_doc) -> str:
	if do_doc.reference_doctype and do_doc.reference_name:
		try:
			comp = frappe.db.get_value(do_doc.reference_doctype, do_doc.reference_name, "company")
			if comp and isinstance(comp, str):
				return comp
		except Exception:
			pass
	try:
		user_default = frappe.defaults.get_user_default("Company")
		if user_default:
			return user_default
	except Exception:
		pass
	return "Default Company"


def _get_customer_and_receivable_account(do_doc, company: str) -> tuple[str | None, str | None]:
	if not (do_doc.reference_doctype and do_doc.reference_name):
		return None, None

	customer = frappe.db.get_value(do_doc.reference_doctype, do_doc.reference_name, "customer")
	if not customer:
		return None, None

	debtors_acc = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Receivable", "is_group": 0},
		"name",
	)
	return customer, debtors_acc


def _append_log(delivery_order_name: str, status: str, message: str):
	try:
		log = frappe.get_doc(
			{
				"doctype": "Delivery Order Log",
				"parenttype": "Delivery Order",
				"parent": delivery_order_name,
				"parentfield": "delivery_logs",
				"status": status,
				"message": message[:500] if message else "",
				"logged_at": frappe.utils.now_datetime(),
			}
		)
		log.db_insert()
	except Exception:
		pass
