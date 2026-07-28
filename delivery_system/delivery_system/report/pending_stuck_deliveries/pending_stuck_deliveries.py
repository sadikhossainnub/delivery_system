# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Pending / Stuck Delivery Report
# Surfaces deliveries that have remained pending/in_review/hold beyond a minimum number of days.

import frappe
from frappe import _
from frappe.utils import date_diff, today


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
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "recipient_phone",
			"label": _("Recipient Phone"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "consignment_id",
			"label": _("Consignment ID"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "delivery_status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 120,
		},
		{
			"fieldname": "booked_on",
			"label": _("Booked On"),
			"fieldtype": "Date",
			"width": 110,
		},
		{
			"fieldname": "days_pending",
			"label": _("Days Pending"),
			"fieldtype": "Int",
			"width": 110,
		},
		{
			"fieldname": "last_status_message",
			"label": _("Last Status Message"),
			"fieldtype": "Data",
			"width": 200,
		},
	]


def get_data(filters):
	min_days = int(filters.get("min_days_pending") or 3)
	conditions, values = build_conditions(filters)

	sql = f"""
		SELECT
			do.name,
			do.reference_doctype,
			do.reference_name,
			do.recipient_phone,
			do.consignment_id,
			do.delivery_status,
			do.creation AS booked_on,
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
			) AS last_status_message
		FROM `tabDelivery Order` do
		WHERE do.docstatus = 1
			AND do.delivery_status IN ('pending', 'in_review', 'hold')
			{conditions}
		ORDER BY do.creation ASC
	"""

	rows = frappe.db.sql(sql, values, as_dict=True)
	result = []

	for row in rows:
		booked_date = row.booked_on.date() if hasattr(row.booked_on, "date") else row.booked_on
		days = date_diff(today(), booked_date)

		if days >= min_days:
			row["days_pending"] = days
			row["booked_on"] = booked_date
			result.append(row)

	result.sort(key=lambda x: x["days_pending"], reverse=True)
	return result


def build_conditions(filters):
	conditions = []
	values = {}

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
