# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Pathao Courier API client — STUB (not yet implemented)
# Implement this module when Pathao integration is needed.
# Expose a `Client` class that extends BaseCourierClient.

from __future__ import annotations

import frappe

from delivery_system.couriers import BaseCourierClient


class Client(BaseCourierClient):
	"""Pathao courier API client (stub — not yet implemented)."""

	def create_order(self, order_data: dict) -> dict:
		frappe.throw(frappe._("Pathao courier integration is not yet implemented."), frappe.ValidationError)

	def bulk_create(self, orders: list[dict]) -> list[dict]:
		frappe.throw(frappe._("Pathao courier integration is not yet implemented."), frappe.ValidationError)

	def get_status(self, invoice=None, consignment_id=None, tracking_code=None) -> dict:
		frappe.throw(frappe._("Pathao courier integration is not yet implemented."), frappe.ValidationError)

	def get_balance(self) -> dict:
		frappe.throw(frappe._("Pathao courier integration is not yet implemented."), frappe.ValidationError)

	def create_return_request(self, consignment_id: str, reason: str = "") -> dict:
		frappe.throw(frappe._("Pathao courier integration is not yet implemented."), frappe.ValidationError)
