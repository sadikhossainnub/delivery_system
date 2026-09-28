# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Manual / Local Courier Client implementation for in-house delivery & local employees.

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime

from delivery_system.couriers import BaseCourierClient


class Client(BaseCourierClient):
	"""Client adapter for Manual Courier & Internal Employee / Local Deliveries.

	Does not depend on external HTTP APIs. Automatically creates local tracking numbers,
	tracks status directly within Frappe, and allows manual status updates and fraud checks.
	"""

	def __init__(self, api_key: str = "", secret_key: str = "", base_url: str = ""):
		self.api_key = api_key or "manual"
		self.secret_key = secret_key or "manual"
		self.base_url = (base_url or "").rstrip("/")

	def create_order(self, order_data: dict) -> dict:
		"""Book a consignment locally for manual or internal employee delivery.

		Args:
			order_data: Dict with keys: invoice, recipient_name, recipient_phone,
				recipient_address, cod_amount, note (optional), delivery_type (optional).

		Returns:
			Dict containing consignment_id, tracking_code, status, and raw response.
		"""
		invoice = order_data.get("invoice") or frappe.generate_hash(length=10)
		consignment_id = f"MAN-{invoice}"
		tracking_code = f"MAN-{invoice}"

		try:
			created_at = str(now_datetime())
		except Exception:
			from datetime import datetime
			created_at = str(datetime.now())

		return {
			"consignment_id": consignment_id,
			"tracking_code": tracking_code,
			"status": "pending",
			"message": _("Manual delivery order created successfully."),
			"raw": {
				"provider": "manual",
				"invoice": invoice,
				"recipient_name": order_data.get("recipient_name"),
				"recipient_phone": order_data.get("recipient_phone"),
				"cod_amount": order_data.get("cod_amount"),
				"delivery_type": order_data.get("delivery_type", "Local Delivery"),
				"created_at": created_at,
			},
		}

	def bulk_create(self, orders: list[dict]) -> list[dict]:
		"""Book multiple consignments locally."""
		return [self.create_order(o) for o in orders]

	def get_status(
		self,
		invoice: str | None = None,
		consignment_id: str | None = None,
		tracking_code: str | None = None,
	) -> dict:
		"""Check delivery status from local database."""
		filters = {}
		if consignment_id:
			filters["consignment_id"] = consignment_id
		elif invoice:
			filters["invoice_reference"] = invoice
		elif tracking_code:
			filters["tracking_code"] = tracking_code
		else:
			frappe.throw(_("Please provide invoice, consignment_id, or tracking_code."), frappe.ValidationError)

		do = None
		if getattr(frappe, "db", None) and hasattr(frappe.db, "get_value"):
			do = frappe.db.get_value(
				"Delivery Order",
				filters,
				["name", "consignment_id", "tracking_code", "delivery_status"],
				as_dict=True,
			)

		if do:
			return {
				"consignment_id": do.consignment_id or consignment_id,
				"tracking_code": do.tracking_code or tracking_code,
				"delivery_status": do.delivery_status or "pending",
				"status": do.delivery_status or "pending",
				"message": _("Fetched status from local system."),
				"raw": {"delivery_order": do.name, "status": do.delivery_status},
			}

		return {
			"consignment_id": consignment_id or "",
			"tracking_code": tracking_code or "",
			"delivery_status": "pending",
			"status": "pending",
			"message": _("No delivery order record found in local system."),
		}

	def get_balance(self) -> dict:
		"""Return balance for manual courier (always 0 since internal)."""
		return {"current_balance": 0.0, "balance": 0.0, "currency": "BDT"}

	def create_return_request(self, consignment_id: str, reason: str = "") -> dict:
		"""Initiate a manual return request."""
		return {
			"status": "success",
			"consignment_id": consignment_id,
			"message": _("Manual return request logged. Reason: {0}").format(reason or _("N/A")),
		}

	def ping(self) -> dict:
		"""Check connection status for manual delivery module."""
		return {"status": 200, "message": "Manual delivery client is operational."}

	def fraud_check(self, phone: str) -> dict:
		"""Check customer delivery history locally by phone number."""
		phone = (phone or "").strip()
		if not phone or not getattr(frappe, "db", None):
			return {"status": 200, "total_orders": 0, "delivered": 0, "cancelled": 0, "score": 100}

		try:
			orders = frappe.get_all(
				"Delivery Order",
				filters={"recipient_phone": phone},
				fields=["name", "delivery_status"],
			)
		except Exception:
			orders = []

		total = len(orders)
		delivered = sum(1 for o in orders if o.get("delivery_status") == "delivered")
		cancelled = sum(1 for o in orders if o.get("delivery_status") in ("cancelled", "returned"))
		pending = total - delivered - cancelled

		score = 100
		if total > 0:
			score = int(round((delivered / total) * 100))

		return {
			"status": 200,
			"phone": phone,
			"total_orders": total,
			"delivered": delivered,
			"cancelled": cancelled,
			"pending": pending,
			"score": score,
			"message": _("Local fraud check calculated from past orders."),
		}
