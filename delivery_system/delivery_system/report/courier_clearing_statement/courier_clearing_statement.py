# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Courier Clearing Account Statement — mini bank-reconciliation ledger view.
# Displays opening balance, all Dr/Cr entries in the Clearing Account, and closing balance.

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"fieldname": "posting_date",
			"label": _("Posting Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "voucher_type",
			"label": _("Voucher Type"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "voucher_no",
			"label": _("Voucher No"),
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 160,
		},
		{
			"fieldname": "against_account",
			"label": _("Against Account / Remarks"),
			"fieldtype": "Data",
			"width": 220,
		},
		{
			"fieldname": "debit",
			"label": _("Debit (In)"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "credit",
			"label": _("Credit (Out)"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "balance",
			"label": _("Running Balance"),
			"fieldtype": "Currency",
			"width": 140,
		},
	]


def get_data(filters):
	company = filters.get("company") or frappe.defaults.get_user_default("Company")
	if not company:
		return []

	# Find clearing account
	from delivery_system.accounting import get_accounting_settings
	acc_config = get_accounting_settings(company)
	clearing_acc = acc_config.get("clearing_account")

	if not clearing_acc or not frappe.db.exists("Account", clearing_acc):
		# Fallback search by account name pattern
		clearing_acc = frappe.db.get_value(
			"Account",
			{"company": company, "account_name": ["like", "%Clearing%"]},
			"name",
		)

	if not clearing_acc:
		return []

	conditions, values = build_conditions(filters)
	values["clearing_account"] = clearing_acc

	# Get opening balance
	from_date = filters.get("from_date")
	opening_balance = 0.0
	if from_date:
		op_res = frappe.db.sql(
			"""
			SELECT SUM(debit - credit) AS opening
			FROM `tabGL Entry`
			WHERE account = %(clearing_account)s
				AND is_cancelled = 0
				AND posting_date < %(from_date)s
			""",
			{"clearing_account": clearing_acc, "from_date": from_date},
			as_dict=True,
		)
		if op_res and op_res[0].opening:
			opening_balance = float(op_res[0].opening)

	data = [
		{
			"posting_date": from_date or "",
			"voucher_type": "",
			"voucher_no": "",
			"against_account": _("Opening Balance"),
			"debit": 0,
			"credit": 0,
			"balance": opening_balance,
		}
	]

	sql = f"""
		SELECT
			posting_date,
			voucher_type,
			voucher_no,
			remarks AS against_account,
			debit,
			credit
		FROM `tabGL Entry`
		WHERE account = %(clearing_account)s
			AND is_cancelled = 0
			{conditions}
		ORDER BY posting_date ASC, creation ASC
	"""

	entries = frappe.db.sql(sql, values, as_dict=True)
	running_balance = opening_balance

	for entry in entries:
		dr = float(entry.get("debit") or 0)
		cr = float(entry.get("credit") or 0)
		running_balance += (dr - cr)

		entry["balance"] = running_balance
		data.append(entry)

	return data


def build_conditions(filters):
	conditions = []
	values = {}

	if filters.get("from_date"):
		conditions.append("posting_date >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("posting_date <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	cond_str = ("AND " + " AND ".join(conditions)) if conditions else ""
	return cond_str, values
