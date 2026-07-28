# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Return / Cancelled Orders Report — Phase 2
# TODO: Phase 2 — identifies patterns in returns by area, product, or customer.

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
			"fieldname": "name",
			"label": _("Delivery Order"),
			"fieldtype": "Link",
			"options": "Delivery Order",
			"width": 140,
		},
		{
			"fieldname": "reference_name",
			"label": _("Reference"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "consignment_id",
			"label": _("Consignment ID"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "delivery_status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "reason",
			"label": _("Reason / Last Message"),
			"fieldtype": "Data",
			"width": 200,
		},
		{
			"fieldname": "recipient_address",
			"label": _("Recipient Address"),
			"fieldtype": "Data",
			"width": 200,
		},
	]


def get_data(filters):
	conditions, values = build_conditions(filters)

	sql = f"""
		SELECT
			do.name,
			do.reference_name,
			do.consignment_id,
			do.delivery_status,
			do.recipient_address,
			CASE
				WHEN do.reference_doctype = 'Sales Order'
				THEN (SELECT so.customer_name FROM `tabSales Order` so WHERE so.name = do.reference_name)
				WHEN do.reference_doctype = 'Delivery Note'
				THEN (SELECT dn.customer_name FROM `tabDelivery Note` dn WHERE dn.name = do.reference_name)
				ELSE NULL
			END AS customer,
			(
				SELECT dol.message
				FROM `tabDelivery Order Log` dol
				WHERE dol.parent = do.name
				ORDER BY dol.logged_at DESC
				LIMIT 1
			) AS reason
		FROM `tabDelivery Order` do
		WHERE do.docstatus = 1
			AND do.delivery_status IN ('cancelled', 'partial_delivered')
			{conditions}
		ORDER BY do.modified DESC
	"""

	return frappe.db.sql(sql, values, as_dict=True)


def build_conditions(filters):
	conditions = []
	values = {}

	if filters.get("from_date"):
		conditions.append("DATE(do.modified) >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("DATE(do.modified) <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	if filters.get("courier_provider"):
		conditions.append("do.courier_provider = %(courier_provider)s")
		values["courier_provider"] = filters["courier_provider"]

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
