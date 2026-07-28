# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Courier Delivery Status — Script Report
# Used for reconciliation against courier payment data.

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
			"width": 150,
		},
		{
			"fieldname": "customer",
			"label": _("Customer"),
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"fieldname": "courier_provider",
			"label": _("Courier"),
			"fieldtype": "Link",
			"options": "Courier Provider",
			"width": 120,
		},
		{
			"fieldname": "consignment_id",
			"label": _("Consignment ID"),
			"fieldtype": "Data",
			"width": 140,
		},
		{
			"fieldname": "tracking_code",
			"label": _("Tracking Code"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "cod_amount",
			"label": _("COD Amount"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "delivery_status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "last_synced_on",
			"label": _("Last Synced"),
			"fieldtype": "Datetime",
			"width": 150,
		},
		{
			"fieldname": "days_pending",
			"label": _("Days Pending"),
			"fieldtype": "Int",
			"width": 100,
		},
		{
			"fieldname": "creation",
			"label": _("Booked On"),
			"fieldtype": "Date",
			"width": 100,
		},
	]


def get_data(filters):
	conditions, values = build_conditions(filters)

	sql = f"""
		SELECT
			do.name,
			do.reference_doctype,
			do.reference_name,
			do.courier_provider,
			do.consignment_id,
			do.tracking_code,
			do.cod_amount,
			do.delivery_status,
			do.last_synced_on,
			do.creation,
			CASE
				WHEN do.reference_doctype = 'Sales Order'
				THEN (SELECT so.customer_name FROM `tabSales Order` so WHERE so.name = do.reference_name)
				WHEN do.reference_doctype = 'Delivery Note'
				THEN (SELECT dn.customer_name FROM `tabDelivery Note` dn WHERE dn.name = do.reference_name)
				ELSE NULL
			END AS customer
		FROM `tabDelivery Order` do
		WHERE do.docstatus = 1
		{conditions}
		ORDER BY do.creation DESC
	"""

	rows = frappe.db.sql(sql, values, as_dict=True)

	for row in rows:
		booked_date = (row.creation.date() if hasattr(row.creation, "date") else row.creation)
		if row.delivery_status not in ("delivered", "cancelled", "partial_delivered"):
			row["days_pending"] = date_diff(today(), booked_date)
		else:
			row["days_pending"] = 0

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

	if filters.get("delivery_status"):
		conditions.append("do.delivery_status = %(delivery_status)s")
		values["delivery_status"] = filters["delivery_status"]

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


def get_filters():
	return [
		{
			"fieldname": "from_date",
			"label": _("From Date"),
			"fieldtype": "Date",
			"default": frappe.utils.add_months(frappe.utils.today(), -1),
		},
		{
			"fieldname": "to_date",
			"label": _("To Date"),
			"fieldtype": "Date",
			"default": frappe.utils.today(),
		},
		{
			"fieldname": "courier_provider",
			"label": _("Courier Provider"),
			"fieldtype": "Link",
			"options": "Courier Provider",
		},
		{
			"fieldname": "delivery_status",
			"label": _("Delivery Status"),
			"fieldtype": "Select",
			"options": "\npending\nin_review\ndelivered_approval_pending\npartial_delivered_approval_pending\ncancelled_approval_pending\ndelivered\npartial_delivered\ncancelled\nhold\nunknown",
		},
		{
			"fieldname": "company",
			"label": _("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"default": frappe.defaults.get_user_default("Company"),
		},
	]
