# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Delivery Charge vs Revenue Report
# Evaluates per-order profitability including courier costs and COD charges.

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
			"fieldname": "reference_doctype",
			"label": _("Ref Type"),
			"fieldtype": "Data",
			"width": 110,
		},
		{
			"fieldname": "reference_name",
			"label": _("Reference"),
			"fieldtype": "Dynamic Link",
			"options": "reference_doctype",
			"width": 140,
		},
		{
			"fieldname": "invoice_amount",
			"label": _("Invoice Amount"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "delivery_charge",
			"label": _("Delivery Charge"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "cod_collection_fee",
			"label": _("COD Fee"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "net_margin",
			"label": _("Net Margin After Cost"),
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def get_data(filters):
	conditions, values = build_conditions(filters)

	sql = f"""
		SELECT
			do.name AS delivery_order,
			do.reference_doctype,
			do.reference_name,
			do.cod_amount AS invoice_amount,
			COALESCE(
				(
					SELECT SUM(cpli.amount)
					FROM `tabCourier Payout Log Item` cpli
					WHERE cpli.delivery_order = do.name
				), 60.00
			) AS delivery_charge,
			ROUND(do.cod_amount * 0.01, 2) AS cod_collection_fee
		FROM `tabDelivery Order` do
		WHERE do.docstatus = 1
			{conditions}
		ORDER BY do.creation DESC
	"""

	rows = frappe.db.sql(sql, values, as_dict=True)

	for row in rows:
		inv_amt = float(row.get("invoice_amount") or 0)
		charge = float(row.get("delivery_charge") or 0)
		cod_fee = float(row.get("cod_collection_fee") or 0)
		row["net_margin"] = inv_amt - (charge + cod_fee)

	return rows


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
