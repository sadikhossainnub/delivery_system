# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# doc_events.py — Frappe document event hooks for delivery_system

import frappe
from frappe import _
from frappe.utils import now_datetime


def cancel_linked_delivery_orders(doc, method=None):
	"""
	Automatically cancel all submitted Delivery Orders linked to a
	Sales Order or Delivery Note when it is cancelled.

	Called via doc_events hook on:
	  - Sales Order.on_cancel
	  - Delivery Note.on_cancel
	"""
	linked_orders = frappe.get_all(
		"Delivery Order",
		filters={
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"docstatus": 1,  # submitted only
		},
		pluck="name",
	)

	for do_name in linked_orders:
		try:
			do_doc = frappe.get_doc("Delivery Order", do_name)
			do_doc.cancel()
			frappe.msgprint(
				_("Delivery Order {0} has been cancelled automatically.").format(
					frappe.utils.get_link_to_form("Delivery Order", do_name)
				),
				alert=True,
				indicator="orange",
			)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"cancel_linked_delivery_orders: failed to cancel {do_name}",
			)
