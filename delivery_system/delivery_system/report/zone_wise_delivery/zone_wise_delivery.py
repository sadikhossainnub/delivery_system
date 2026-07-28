# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Area / Zone-wise Delivery Report — Phase 2
# TODO: Phase 2 — spot which areas have low delivery success or high return rates based on recipient address.

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
			"fieldname": "zone",
			"label": _("Zone / Address Group"),
			"fieldtype": "Data",
			"width": 180,
		},
		{
			"fieldname": "total_deliveries",
			"label": _("Total Deliveries"),
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"fieldname": "delivered_count",
			"label": _("Delivered"),
			"fieldtype": "Int",
			"width": 110,
		},
		{
			"fieldname": "cancelled_count",
			"label": _("Cancelled"),
			"fieldtype": "Int",
			"width": 110,
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

	# Basic zone grouping by recipient_address prefix/city if zone field is not yet present
	sql = f"""
		SELECT
			COALESCE(SUBSTRING_INDEX(do.recipient_address, ',', 1), 'Unspecified') AS zone,
			COUNT(do.name) AS total_deliveries,
			SUM(CASE WHEN do.delivery_status = 'delivered' THEN 1 ELSE 0 END) AS delivered_count,
			SUM(CASE WHEN do.delivery_status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_count
		FROM `tabDelivery Order` do
		WHERE do.docstatus = 1
			{conditions}
		GROUP BY zone
		ORDER BY total_deliveries DESC
	"""

	rows = frappe.db.sql(sql, values, as_dict=True)

	for row in rows:
		total = row["total_deliveries"] or 0
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
