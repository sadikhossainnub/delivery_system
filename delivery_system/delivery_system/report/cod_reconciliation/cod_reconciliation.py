# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# COD Reconciliation Report
# Matches expected COD amount per delivery against actual courier payouts.

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
			"fieldname": "delivery_order",
			"label": _("Delivery Order"),
			"fieldtype": "Link",
			"options": "Delivery Order",
			"width": 140,
		},
		{
			"fieldname": "invoice_reference",
			"label": _("Invoice"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "consignment_id",
			"label": _("Consignment ID"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "recipient_name",
			"label": _("Recipient"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "expected_cod",
			"label": _("Expected COD"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "received_amount",
			"label": _("Received Amount"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "payment_id",
			"label": _("Payment ID"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "payment_date",
			"label": _("Payment Date"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "variance",
			"label": _("Variance"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "reconciliation_status",
			"label": _("Reconciliation Status"),
			"fieldtype": "Data",
			"width": 140,
		},
	]


def get_data(filters):
	conditions, values = build_conditions(filters)

	sql = f"""
		SELECT
			do.name AS delivery_order,
			do.invoice_reference,
			do.consignment_id,
			do.recipient_name,
			do.cod_amount AS expected_cod,
			do.courier_provider,
			do.payment_reconciled,
			do.reconciled_payment_id,
			do.reference_doctype,
			do.reference_name
		FROM `tabDelivery Order` do
		WHERE do.docstatus = 1
			AND do.delivery_status = 'delivered'
			{conditions}
		ORDER BY do.creation DESC
	"""

	orders = frappe.db.sql(sql, values, as_dict=True)
	if not orders:
		return []

	# Fetch payments from courier API if possible
	payout_map = {}
	try:
		from delivery_system.couriers import get_client

		default_provider = frappe.db.get_single_value("Courier Settings", "default_provider")
		provider_code = (
			frappe.db.get_value("Courier Provider", default_provider, "provider_code")
			if default_provider
			else "steadfast"
		)
		client = get_client(provider_code)

		raw_payments = client.get_payments(
			date_from=filters.get("from_date"),
			date_to=filters.get("to_date"),
		)

		for p in raw_payments:
			cid = str(p.get("consignment_id") or p.get("cid") or "").strip()
			inv = str(p.get("invoice") or "").strip()
			p_id = str(p.get("payment_id") or p.get("id") or "")
			amt = float(p.get("amount") or p.get("received_amount") or p.get("cod_amount") or 0)
			p_date = p.get("created_at") or p.get("payment_date") or p.get("date")

			if cid:
				payout_map[cid] = {"payment_id": p_id, "amount": amt, "payment_date": p_date}
			if inv:
				payout_map[inv] = {"payment_id": p_id, "amount": amt, "payment_date": p_date}
	except Exception:
		# If API call fails or courier not configured, continue with stored reconciliation data
		pass

	data = []
	status_filter = filters.get("reconciliation_status")

	for row in orders:
		cid = row.consignment_id
		inv = row.invoice_reference
		expected = float(row.expected_cod or 0)

		# Match payout
		payout = payout_map.get(cid) or payout_map.get(inv)

		if row.payment_reconciled:
			received = expected
			payment_id = row.reconciled_payment_id or "MANUAL"
			payment_date = None
			status = "Matched"
		elif payout:
			received = float(payout["amount"])
			payment_id = payout["payment_id"]
			payment_date = payout["payment_date"]
			if abs(expected - received) < 0.01:
				status = "Matched"
				# Auto-mark as reconciled in DB
				frappe.db.set_value(
					"Delivery Order",
					row.delivery_order,
					{"payment_reconciled": 1, "reconciled_payment_id": payment_id},
				)
			else:
				status = "Partial"
		else:
			received = 0.0
			payment_id = "-"
			payment_date = None
			status = "Unmatched"

		variance = expected - received

		if status_filter and status != status_filter:
			continue

		row_dict = {
			"delivery_order": row.delivery_order,
			"invoice_reference": row.invoice_reference,
			"consignment_id": row.consignment_id,
			"recipient_name": row.recipient_name,
			"expected_cod": expected,
			"received_amount": received,
			"payment_id": payment_id,
			"payment_date": payment_date,
			"variance": variance,
			"reconciliation_status": status,
		}
		data.append(row_dict)

	return data


def build_conditions(filters):
	conditions = []
	values = {}

	if filters.get("from_date"):
		conditions.append("DATE(do.creation) >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("DATE(do.creation) <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	if filters.get("company"):
		conditions.append(
			"""(
				(do.reference_doctype = 'Sales Order' AND EXISTS (
					SELECT 1 FROM `tabSales Order` so
					WHERE so.name = do.reference_name AND so.company = %(company)s
				))
				OR
				(do.reference_doctype = 'Delivery Note' AND EXISTS (
					SELECT 1 FROM `tabDelivery Note` dn
					WHERE dn.name = do.reference_name AND dn.company = %(company)s
				))
			)"""
		)
		values["company"] = filters["company"]

	cond_str = ("AND " + " AND ".join(conditions)) if conditions else ""
	return cond_str, values
