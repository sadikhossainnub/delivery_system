# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Courier Performance Report — Phase 2 (Multi-courier performance comparison)
# TODO: Phase 2 — Multi-courier analysis (Total Bookings, Delivered Count, Cancelled Count, Success Rate %, Avg Delivery Time)

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
			"fieldname": "courier_provider",
			"label": _("Courier Provider"),
			"fieldtype": "Link",
			"options": "Courier Provider",
			"width": 150,
		},
		{
			"fieldname": "total_bookings",
			"label": _("Total Bookings"),
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"fieldname": "delivered_count",
			"label": _("Delivered Count"),
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"fieldname": "cancelled_count",
			"label": _("Cancelled Count"),
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"fieldname": "success_rate",
			"label": _("Success Rate %"),
			"fieldtype": "Percent",
			"width": 130,
		},
	]


def get_data(filters):
	conditions, values = build_conditions(filters)

	sql = f"""
		SELECT
			do.courier_provider,
			COUNT(do.name) AS total_bookings,
			SUM(CASE WHEN do.delivery_status = 'delivered' THEN 1 ELSE 0 END) AS delivered_count,
			SUM(CASE WHEN do.delivery_status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_count
		FROM `tabDelivery Order` do
		WHERE do.docstatus = 1
			{conditions}
		GROUP BY do.courier_provider
		ORDER BY total_bookings DESC
	"""

	rows = frappe.db.sql(sql, values, as_dict=True)

	for row in rows:
		total = row["total_bookings"] or 0
		delivered = row["delivered_count"] or 0
		row["success_rate"] = round((delivered / total * 100), 2) if total > 0 else 0.0

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
