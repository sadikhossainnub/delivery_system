# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today, add_days, date_diff


def execute(filters=None):
	"""Return stuck deliveries report data."""
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	"""Define report columns."""
	return [
		{
			"fieldname": "name",
			"label": _("Delivery Order"),
			"fieldtype": "Link",
			"options": "Delivery Order",
			"width": 150
		},
		{
			"fieldname": "consignment_id",
			"label": _("Consignment ID"),
			"fieldtype": "Data",
			"width": 130
		},
		{
			"fieldname": "creation",
			"label": _("Created On"),
			"fieldtype": "Date",
			"width": 100
		},
		{
			"fieldname": "days_pending",
			"label": _("Days Pending"),
			"fieldtype": "Int",
			"width": 100
		},
		{
			"fieldname": "courier_provider",
			"label": _("Courier"),
			"fieldtype": "Link",
			"options": "Courier Provider",
			"width": 120
		},
		{
			"fieldname": "delivery_status",
			"label": _("Status"),
			"fieldtype": "Data",
			"width": 100
		},
		{
			"fieldname": "recipient_name",
			"label": _("Recipient"),
			"fieldtype": "Data",
			"width": 150
		},
		{
			"fieldname": "recipient_phone",
			"label": _("Phone"),
			"fieldtype": "Data",
			"width": 120
		},
		{
			"fieldname": "cod_amount",
			"label": _("COD Amount"),
			"fieldtype": "Currency",
			"width": 120
		},
		{
			"fieldname": "reference_name",
			"label": _("Reference"),
			"fieldtype": "Dynamic Link",
			"options": "reference_doctype",
			"width": 150
		},
		{
			"fieldname": "company",
			"label": _("Company"),
			"fieldtype": "Link",
			"options": "Company",
			"width": 150
		}
	]


def get_data(filters):
	"""Fetch stuck delivery orders."""
	# Get min_days from settings
	min_days = 3
	try:
		min_days = frappe.db.get_single_value("Courier Settings", "min_days_pending") or 3
	except Exception:
		pass
	
	cutoff_date = add_days(today(), -min_days)
	
	# Base query
	conditions = [
		"do.delivery_status IN ('pending', 'in_review')",
		"do.creation <= %(cutoff_date)s",
		"do.docstatus < 2"
	]
	
	# Add company filter if provided
	if filters and filters.get("company"):
		conditions.append("""
			EXISTS (
				SELECT 1 FROM `tabSales Order` so 
				WHERE so.name = do.reference_name 
				  AND so.company = %(company)s
				  AND do.reference_doctype = 'Sales Order'
				UNION
				SELECT 1 FROM `tabDelivery Note` dn
				WHERE dn.name = do.reference_name
				  AND dn.company = %(company)s
				  AND do.reference_doctype = 'Delivery Note'
			)
		""")
	
	query = f"""
		SELECT 
			do.name,
			do.consignment_id,
			DATE(do.creation) as creation,
			DATEDIFF(CURDATE(), DATE(do.creation)) as days_pending,
			do.courier_provider,
			do.delivery_status,
			do.recipient_name,
			do.recipient_phone,
			do.cod_amount,
			do.reference_doctype,
			do.reference_name,
			CASE 
				WHEN do.reference_doctype = 'Sales Order' THEN 
					(SELECT company FROM `tabSales Order` WHERE name = do.reference_name)
				WHEN do.reference_doctype = 'Delivery Note' THEN 
					(SELECT company FROM `tabDelivery Note` WHERE name = do.reference_name)
				ELSE NULL
			END as company
		FROM `tabDelivery Order` do
		WHERE {" AND ".join(conditions)}
		ORDER BY do.creation ASC
	"""
	
	params = {
		"cutoff_date": cutoff_date,
		"company": filters.get("company") if filters else None
	}
	
	data = frappe.db.sql(query, params, as_dict=True)
	
	return data
