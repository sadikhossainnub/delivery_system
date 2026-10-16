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


def post_clearing_entry(
	delivery_order_doc, force: bool = False, auto_create_invoice: bool = True
) -> str | None:
	"""Post Payment Entry (Receive) allocating COD amount against the linked Sales Invoice.

	Ensures:
	1. The linked Sales Invoice is resolved or auto-created.
	2. A Payment Entry (Type: Receive) is posted with references to the Sales Invoice.
	3. The Sales Invoice outstanding amount is reduced and marked as Paid.
	"""
	cod_amt = flt(delivery_order_doc.cod_amount)
	if cod_amt <= 0:
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
	if not customer:
		return None

	# Resolve or create the linked Sales Invoice
	sales_invoice = get_or_create_sales_invoice(delivery_order_doc, auto_create=auto_create_invoice)

	# Check if already paid with a linked invoice
	if delivery_order_doc.clearing_entry_posted and not force:
		existing_pe = getattr(delivery_order_doc, "clearing_journal_entry", None)
		if existing_pe and frappe.db.exists("Payment Entry", existing_pe):
			has_inv_ref = frappe.db.get_value(
				"Payment Entry Reference",
				{"parent": existing_pe, "reference_doctype": "Sales Invoice"},
				"name",
			)
			if has_inv_ref:
				return existing_pe

	# If there was an old unallocated clearing Payment Entry, cancel it to avoid double-charging
	existing_pe = getattr(delivery_order_doc, "clearing_journal_entry", None)
	if existing_pe and frappe.db.exists("Payment Entry", existing_pe):
		try:
			old_pe = frappe.get_doc("Payment Entry", existing_pe)
			if old_pe.docstatus == 1:
				has_inv_ref = any(r.reference_doctype == "Sales Invoice" for r in (old_pe.references or []))
				if not has_inv_ref and sales_invoice:
					old_pe.cancel()
		except Exception:
			pass

	mode_of_payment = acc_config.get("default_mode_of_payment") or "Steadfast COD"
	remarks = f"Auto-posted by delivery_system - Consignment {delivery_order_doc.consignment_id or delivery_order_doc.name}"

	try:
		savepoint = "post_clearing_" + delivery_order_doc.name.replace("-", "_")
		frappe.db.savepoint(savepoint)

		pe = None
		if sales_invoice and frappe.db.exists("Sales Invoice", sales_invoice):
			sinv_doc = frappe.get_doc("Sales Invoice", sales_invoice)
			outstanding = flt(sinv_doc.outstanding_amount)

			if outstanding <= 0:
				frappe.db.set_value(
					"Delivery Order",
					delivery_order_doc.name,
					{"clearing_entry_posted": 1},
				)
				_append_log(delivery_order_doc.name, "accounting", f"Linked Sales Invoice {sales_invoice} is already fully paid.")
				return sales_invoice

			allocated_amt = flt(min(cod_amt, outstanding))

			# 1. Try ERPNext standard mapper
			try:
				from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
				pe = get_payment_entry("Sales Invoice", sales_invoice)
				pe.paid_to = clearing_acc
				pe.paid_amount = allocated_amt
				pe.received_amount = allocated_amt
				if pe.references:
					pe.references[0].allocated_amount = allocated_amt
					pe.references[0].outstanding_amount = outstanding
			except Exception:
				pe = None

			# 2. Manual fallback with explicit references to the Sales Invoice
			if not pe:
				pe = frappe.get_doc({
					"doctype": "Payment Entry",
					"payment_type": "Receive",
					"company": company,
					"posting_date": today(),
					"mode_of_payment": mode_of_payment,
					"party_type": "Customer",
					"party": customer,
					"paid_from": sinv_doc.debit_to or debtors_acc,
					"paid_to": clearing_acc,
					"paid_amount": allocated_amt,
					"received_amount": allocated_amt,
					"reference_no": delivery_order_doc.consignment_id or delivery_order_doc.name,
					"reference_date": today(),
					"remarks": remarks,
					"references": [
						{
							"reference_doctype": "Sales Invoice",
							"reference_name": sales_invoice,
							"total_amount": sinv_doc.grand_total,
							"outstanding_amount": outstanding,
							"allocated_amount": allocated_amt,
						}
					],
				})

			pe.mode_of_payment = mode_of_payment
			pe.reference_no = delivery_order_doc.consignment_id or delivery_order_doc.name
			pe.reference_date = today()
			pe.remarks = remarks
			pe.posting_date = today()

		else:
			# --- Fallback: no Sales Invoice yet, build manually ---
			pe = frappe.get_doc({
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": company,
				"posting_date": today(),
				"mode_of_payment": mode_of_payment,
				"party_type": "Customer",
				"party": customer,
				"paid_to": clearing_acc,
				"paid_amount": cod_amt,
				"received_amount": cod_amt,
				"reference_no": delivery_order_doc.consignment_id or delivery_order_doc.name,
				"reference_date": today(),
				"remarks": remarks,
			})

		pe.insert(ignore_permissions=True)
		pe.submit()

		frappe.db.set_value(
			"Delivery Order",
			delivery_order_doc.name,
			{
				"clearing_entry_posted": 1,
				"clearing_journal_entry": pe.name,
			},
		)

		_append_log(
			delivery_order_doc.name,
			"accounting",
			f"Posted clearing Payment Entry {pe.name} applied to Sales Invoice {sales_invoice or 'N/A'}"
		)
		return pe.name
	except Exception as exc:
		frappe.db.rollback(to_savepoint=savepoint)
		frappe.log_error(frappe.get_traceback(), "post_clearing_entry")
		_append_log(delivery_order_doc.name, "error", f"Failed to post clearing Payment Entry: {exc}")
		return None


def reverse_clearing_entry(delivery_order_doc) -> str | None:
	"""Cancel the clearing Payment Entry when Delivery Order is cancelled.

	Cancelling the Payment Entry automatically reverses the Sales Invoice
	payment and restores the Debtors balance.
	"""
	if not delivery_order_doc.clearing_entry_posted or delivery_order_doc.reversal_journal_entry:
		return None

	pe_name = delivery_order_doc.clearing_journal_entry
	if not pe_name:
		return None

	try:
		# Cancel the Payment Entry — ERPNext auto-reverses the GL and invoice link
		if frappe.db.exists("Payment Entry", pe_name):
			pe = frappe.get_doc("Payment Entry", pe_name)
			if pe.docstatus == 1:
				pe.cancel()
				frappe.db.set_value(
					"Delivery Order",
					delivery_order_doc.name,
					{"reversal_journal_entry": pe_name},
				)
				_append_log(delivery_order_doc.name, "accounting", f"Cancelled clearing Payment Entry {pe_name}")
				return pe_name
		# Fallback: check if it was a Journal Entry (legacy)
		elif frappe.db.exists("Journal Entry", pe_name):
			je = frappe.get_doc("Journal Entry", pe_name)
			if je.docstatus == 1:
				je.cancel()
				frappe.db.set_value(
					"Delivery Order",
					delivery_order_doc.name,
					{"reversal_journal_entry": pe_name},
				)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "reverse_clearing_entry")
		_append_log(delivery_order_doc.name, "error", f"Failed to reverse clearing entry: {exc}")
	return None


def post_payout_entries(payout_data: dict, matched_orders: list) -> dict:
	"""Process courier payout: create Bank JE to clear the Clearing Account + Courier Payout log.

	When the courier transfers the net COD amount to the company's bank:
	1. Journal Entry:
	       Dr  Bank Account                net_amount
	       Dr  Delivery Charges            charge_amount
	           Cr  Steadfast Clearing Account  gross_amount
	2. Courier Payout log (linked to Delivery Orders)
	"""
	payment_id = str(payout_data.get("payment_id") or payout_data.get("id") or "")
	gross_amount = flt(payout_data.get("gross_amount") or payout_data.get("amount") or 0)
	charge_amount = flt(payout_data.get("charge_amount") or payout_data.get("delivery_charge") or 0)
	net_amount = gross_amount - charge_amount

	if not payment_id:
		return {"success": False, "error": "Missing payment_id"}

	# Check duplicate
	if frappe.db.exists("Courier Payout", {"payment_id": payment_id}):
		return {"success": True, "message": "Payout already logged"}

	default_provider = frappe.db.get_single_value("Courier Settings", "default_provider")
	provider_name = default_provider or "Steadfast"
	company = (
		frappe.defaults.get_user_default("Company")
		or frappe.db.get_single_value("Global Defaults", "default_company")
	)

	acc_config = get_accounting_settings(company)
	clearing_acc = acc_config["clearing_account"]
	charge_acc = acc_config["delivery_charge_account"]

	# --- 1. Settlement Payment Entry: Clearing Account -> Bank Account with Delivery Charges ---
	payout_pe_name = None
	if clearing_acc and frappe.db.exists("Account", clearing_acc):
		bank_acc = _get_default_bank_account(company)
		cost_center = frappe.get_cached_value("Company", company, "cost_center") if company else None

		# Try creating Payment Entry (Internal Transfer)
		if bank_acc and frappe.db.exists("Account", bank_acc):
			try:
				pe = frappe.get_doc({
					"doctype": "Payment Entry",
					"payment_type": "Internal Transfer",
					"company": company,
					"posting_date": payout_data.get("payment_date") or today(),
					"paid_from": clearing_acc,
					"paid_to": bank_acc,
					"paid_amount": gross_amount,
					"received_amount": net_amount,
					"reference_no": payment_id,
					"reference_date": payout_data.get("payment_date") or today(),
					"remarks": f"Courier payout settlement - Payment ID {payment_id}",
				})

				if charge_acc and charge_amount > 0 and frappe.db.exists("Account", charge_acc):
					pe.append("deductions", {
						"account": charge_acc,
						"cost_center": cost_center,
						"amount": charge_amount,
					})

				pe.insert(ignore_permissions=True)
				pe.submit()
				payout_pe_name = pe.name
			except Exception as exc:
				frappe.log_error(frappe.get_traceback(), "post_payout_entries.payment_entry")

		# Fallback to Journal Entry if Payment Entry fails (e.g. account restrictions)
		if not payout_pe_name:
			try:
				je_accounts = []
				if bank_acc and net_amount > 0:
					je_accounts.append({
						"account": bank_acc,
						"debit_in_account_currency": net_amount,
						"credit_in_account_currency": 0,
					})

				if charge_acc and charge_amount > 0 and frappe.db.exists("Account", charge_acc):
					je_accounts.append({
						"account": charge_acc,
						"debit_in_account_currency": charge_amount,
						"credit_in_account_currency": 0,
					})

				if je_accounts:
					je_accounts.append({
						"account": clearing_acc,
						"debit_in_account_currency": 0,
						"credit_in_account_currency": gross_amount,
					})
					je = frappe.get_doc({
						"doctype": "Journal Entry",
						"voucher_type": "Journal Entry",
						"company": company,
						"posting_date": payout_data.get("payment_date") or today(),
						"user_remark": f"Courier payout settlement - Payment ID {payment_id}",
						"accounts": je_accounts,
					})
					je.insert(ignore_permissions=True)
					je.submit()
					payout_pe_name = je.name
			except Exception:
				frappe.log_error(frappe.get_traceback(), "post_payout_entries.je_fallback")

	# --- 2. Courier Payout log ---
	payout_log = frappe.get_doc({
		"doctype": "Courier Payout",
		"courier_provider": provider_name,
		"payment_id": payment_id,
		"payout_date": payout_data.get("payment_date") or today(),
		"gross_amount": gross_amount,
		"delivery_charges_deducted": charge_amount,
		"net_amount": net_amount,
		"reconciliation_status": "Complete",
		"raw_response": json.dumps(payout_data, ensure_ascii=False)[:5000],
	})

	linked_items = []
	for do in matched_orders:
		do_doc = frappe.get_doc("Delivery Order", do.name) if isinstance(do.name, str) else do
		clearing_pe = getattr(do_doc, "clearing_journal_entry", None)

		item_dict = {
			"delivery_order": do.name,
			"journal_entry": clearing_pe or payout_pe_name,
			"amount": flt(do.cod_amount),
		}
		# If payment_entry field exists on Courier Payout Item
		if clearing_pe or payout_pe_name:
			item_dict["payment_entry"] = clearing_pe or payout_pe_name

		linked_items.append(item_dict)
		frappe.db.set_value(
			"Delivery Order",
			do.name,
			{"payment_reconciled": 1, "reconciled_payment_id": payment_id},
		)

	payout_log.linked_journal_entries = linked_items
	payout_log.insert(ignore_permissions=True)

	# Store the payout Payment Entry reference on the log
	if payout_pe_name:
		frappe.db.set_value("Courier Payout", payout_log.name, "linked_payment_entry", payout_pe_name)

	return {
		"success": True,
		"payout_log": payout_log.name,
		"payout_payment_entry": payout_pe_name,
		"payout_journal_entry": payout_pe_name,
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


def _find_existing_sales_invoice(delivery_order_doc) -> str | None:
	"""Exhaustively find any existing Sales Invoice linked to this Delivery Order."""
	ref_dt = getattr(delivery_order_doc, "reference_doctype", None)
	ref_name = getattr(delivery_order_doc, "reference_name", None)
	inv_ref = getattr(delivery_order_doc, "invoice_reference", None)

	# 1. Direct match: invoice_reference is an existing Sales Invoice
	if inv_ref and frappe.db.exists("Sales Invoice", inv_ref):
		sinv = frappe.get_doc("Sales Invoice", inv_ref)
		if sinv.docstatus == 0:
			try:
				sinv.submit()
			except Exception:
				pass
		if sinv.docstatus == 1:
			return sinv.name

	# 2. Direct reference is Sales Invoice
	if ref_dt == "Sales Invoice" and ref_name and frappe.db.exists("Sales Invoice", ref_name):
		sinv = frappe.get_doc("Sales Invoice", ref_name)
		if sinv.docstatus == 0:
			try:
				sinv.submit()
			except Exception:
				pass
		if sinv.docstatus == 1:
			return sinv.name

	# 3. Delivery Note reference
	if ref_dt == "Delivery Note" and ref_name:
		# 3a. Sales Invoice Item where delivery_note == ref_name (standard ERPNext DN -> SI)
		sinv_names = frappe.db.sql(
			"""
			SELECT DISTINCT parent
			FROM `tabSales Invoice Item`
			WHERE delivery_note = %s
			ORDER BY creation DESC
			""",
			(ref_name,),
			as_dict=True,
		)
		for row in sinv_names:
			sinv = frappe.get_doc("Sales Invoice", row.parent)
			if sinv.docstatus == 0:
				try:
					sinv.submit()
				except Exception:
					pass
			if sinv.docstatus == 1:
				return sinv.name

		# 3b. Sales Invoice header where delivery_doc_no == ref_name
		sinv_names = frappe.db.sql(
			"""
			SELECT name FROM `tabSales Invoice`
			WHERE delivery_doc_no = %s
			ORDER BY creation DESC
			""",
			(ref_name,),
			as_dict=True,
		)
		for row in sinv_names:
			sinv = frappe.get_doc("Sales Invoice", row.name)
			if sinv.docstatus == 0:
				try:
					sinv.submit()
				except Exception:
					pass
			if sinv.docstatus == 1:
				return sinv.name

		# 3c. Delivery Note Item where against_sales_invoice is set
		sinv_name = frappe.db.get_value("Delivery Note Item", {"parent": ref_name}, "against_sales_invoice")
		if sinv_name and frappe.db.exists("Sales Invoice", sinv_name):
			sinv = frappe.get_doc("Sales Invoice", sinv_name)
			if sinv.docstatus == 0:
				try:
					sinv.submit()
				except Exception:
					pass
			if sinv.docstatus == 1:
				return sinv.name

		# 3d. Check if Delivery Note is against a Sales Order, and find SO's invoice
		dn_so = frappe.db.get_value("Delivery Note", ref_name, "against_sales_order") or frappe.db.get_value(
			"Delivery Note Item", {"parent": ref_name}, "against_sales_order"
		)
		if dn_so:
			sinv_names = frappe.db.sql(
				"""
				SELECT DISTINCT parent FROM `tabSales Invoice Item`
				WHERE sales_order = %s ORDER BY creation DESC
				""",
				(dn_so,),
				as_dict=True,
			)
			for row in sinv_names:
				sinv = frappe.get_doc("Sales Invoice", row.parent)
				if sinv.docstatus == 0:
					try:
						sinv.submit()
					except Exception:
						pass
				if sinv.docstatus == 1:
					return sinv.name

	# 4. Sales Order reference
	if ref_dt == "Sales Order" and ref_name:
		# 4a. Direct Sales Invoice Item with sales_order == ref_name
		sinv_names = frappe.db.sql(
			"""
			SELECT DISTINCT parent
			FROM `tabSales Invoice Item`
			WHERE sales_order = %s
			ORDER BY creation DESC
			""",
			(ref_name,),
			as_dict=True,
		)
		for row in sinv_names:
			sinv = frappe.get_doc("Sales Invoice", row.parent)
			if sinv.docstatus == 0:
				try:
					sinv.submit()
				except Exception:
					pass
			if sinv.docstatus == 1:
				return sinv.name

		# 4b. Find Delivery Notes created for this Sales Order -> check their Sales Invoices
		dn_list = frappe.db.sql(
			"""
			SELECT DISTINCT parent FROM `tabDelivery Note Item`
			WHERE against_sales_order = %s OR sales_order = %s
			""",
			(ref_name, ref_name),
			as_dict=True,
		)
		for dn_row in dn_list:
			sinv_names = frappe.db.sql(
				"""
				SELECT DISTINCT parent FROM `tabSales Invoice Item`
				WHERE delivery_note = %s ORDER BY creation DESC
				""",
				(dn_row.parent,),
				as_dict=True,
			)
			for row in sinv_names:
				sinv = frappe.get_doc("Sales Invoice", row.parent)
				if sinv.docstatus == 0:
					try:
						sinv.submit()
					except Exception:
						pass
				if sinv.docstatus == 1:
					return sinv.name

	return None


def get_or_create_sales_invoice(delivery_order_doc, auto_create: bool = True) -> str | None:
	"""Exhaustively find or auto-create the submitted Sales Invoice linked to a Delivery Order."""
	# 1. Search existing invoices
	try:
		sinv_name = _find_existing_sales_invoice(delivery_order_doc)
		if sinv_name:
			return sinv_name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "get_or_create_sales_invoice.search")

	if not auto_create:
		return None

	# 2. Auto-generate from reference document if none found
	ref_dt = getattr(delivery_order_doc, "reference_doctype", None)
	ref_name = getattr(delivery_order_doc, "reference_name", None)

	if not (ref_dt and ref_name and frappe.db.exists(ref_dt, ref_name)):
		return None

	try:
		sinv = None
		if ref_dt == "Sales Order":
			from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
			sinv = make_sales_invoice(ref_name)
		elif ref_dt == "Delivery Note":
			from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
			sinv = make_sales_invoice(ref_name)

		if sinv:
			sinv.posting_date = today()
			sinv.insert(ignore_permissions=True)
			sinv.submit()
			_append_log(
				delivery_order_doc.name,
				"accounting",
				f"Auto-created and submitted Sales Invoice {sinv.name} from {ref_dt} {ref_name}",
			)
			return sinv.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "get_or_create_sales_invoice.auto_create")

	return None


def _get_sales_invoice(reference_doctype: str, reference_name: str) -> str | None:
	"""Legacy alias for finding sales invoice."""
	mock_doc = frappe._dict({"reference_doctype": reference_doctype, "reference_name": reference_name})
	return _find_existing_sales_invoice(mock_doc)


def _get_default_bank_account(company: str) -> str | None:
	"""Get the default bank account for a company.

	Priority:
	1. Company.default_bank_account
	2. Mode of Payment 'Steadfast COD' default account for company
	3. First non-group Bank-type account for company
	"""
	try:
		# Priority 1: company default
		bank_acc = frappe.db.get_value("Company", company, "default_bank_account")
		if bank_acc:
			return bank_acc

		# Priority 2: via Mode of Payment account mapping
		mop_acc = frappe.db.get_value(
			"Mode of Payment Account",
			{"parent": "Steadfast COD", "company": company},
			"default_account",
		)
		if mop_acc:
			return mop_acc

		# Priority 3: first non-group Bank account for company
		bank_acc = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Bank", "is_group": 0},
			"name",
		)
		return bank_acc or None
	except Exception:
		return None


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
