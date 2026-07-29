# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Patch: Add courier custom fields to Sales Order and Delivery Note
# Run once via patches.txt after migrate.
#
# Fields added:
#   - courier_status (Data, read-only) — mirrors Delivery Order status
#   - delivery_order_ref (Link → Delivery Order, read-only)

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	courier_fields = [
		{
			"fieldname": "delivery_system_section",
			"fieldtype": "Section Break",
			"label": "Courier",
			"insert_after": "additional_info_section",
			"collapsible": 1,
		},
		{
			"fieldname": "customer_mobile_no",
			"fieldtype": "Data",
			"label": "Customer Mobile No",
			"insert_after": "delivery_system_section",
			"fetch_from": "customer.mobile_no",
		},
		{
			"fieldname": "delivery_order_ref",
			"fieldtype": "Link",
			"label": "Delivery Order",
			"options": "Delivery Order",
			"insert_after": "customer_mobile_no",
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
		},
		{
			"fieldname": "courier_status",
			"fieldtype": "Data",
			"label": "Courier Status",
			"insert_after": "delivery_order_ref",
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
			"in_list_view": 0,
		},
		{
			"fieldname": "tracking_url",
			"fieldtype": "Data",
			"options": "URL",
			"label": "Tracking Link",
			"insert_after": "courier_status",
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
			"in_list_view": 1,
		},
	]

	custom_fields = {
		"Sales Order": courier_fields,
		"Delivery Note": courier_fields,
	}

	create_custom_fields(custom_fields, ignore_validate=True)
