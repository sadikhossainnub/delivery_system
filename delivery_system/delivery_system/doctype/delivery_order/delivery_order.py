# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# Status groups for easier comparisons
TERMINAL_STATUSES = {"delivered", "cancelled", "partial_delivered"}
VALID_STATUSES = {
	"", "pending", "in_review", "delivered_approval_pending",
	"partial_delivered_approval_pending", "cancelled_approval_pending",
	"unknown_approval_pending",
	"delivered", "partial_delivered", "cancelled", "hold", "unknown",
}
BD_PHONE_REGEX = re.compile(r"^01[3-9]\d{8}$")
MAX_ADDRESS_LEN = 250
MAX_RAW_RESPONSE_LEN = 5000  # cap stored JSON to avoid DB bloat


def _sanitize_status(raw_status: str, fallback: str = "pending") -> str:
	"""Return a valid delivery_status value; fall back if the API returns garbage like '400'."""
	status = (raw_status or "").strip().lower()
	return status if status in VALID_STATUSES else fallback


class DeliveryOrder(Document):
	# ---------------------------------------------------------------------------
	# Lifecycle hooks
	# ---------------------------------------------------------------------------

	def before_insert(self):
		"""Auto-generate invoice_reference from name or a hash when not provided."""
		if not self.invoice_reference:
			# Name isn't set yet at before_insert; generate a deterministic ref
			self.invoice_reference = frappe.generate_hash(length=16)

	def validate(self):
		self._validate_phone()
		self._truncate_address()
		self._truncate_raw_response()

	def before_submit(self):
		if not self.consignment_id:
			self.book_with_courier()

	def book_with_courier(self):
		"""Call courier API to create order and assign consignment_id."""
		if self.consignment_id:
			return

		if not self.courier_provider:
			frappe.throw(_("Please select a Courier Provider."))

		provider_code = frappe.db.get_value("Courier Provider", self.courier_provider, "provider_code")
		if not provider_code:
			frappe.throw(_("Invalid Courier Provider selected."))

		company = None
		if self.reference_doctype and self.reference_name:
			company = frappe.db.get_value(self.reference_doctype, self.reference_name, "company")

		from delivery_system.couriers import get_client
		import json

		client = get_client(provider_code, company)
		result = client.create_order(
			{
				"invoice": self.invoice_reference or self.name,
				"recipient_name": self.recipient_name,
				"recipient_phone": self.recipient_phone,
				"recipient_address": self.recipient_address,
				"cod_amount": float(self.cod_amount or 0),
				"note": self.note or "",
				"delivery_type": self.delivery_type or "Home Delivery",
			}
		)

		self.consignment_id = result.get("consignment_id") or ""
		self.tracking_code = result.get("tracking_code") or ""
		self.tracking_url = self.get_tracking_url()
		self.delivery_status = _sanitize_status(result.get("status"), "pending")
		self.last_synced_on = now_datetime()
		self.raw_response = json.dumps(result.get("raw") or result, ensure_ascii=False)[:5000]

		self.append(
			"delivery_logs",
			{
				"status": self.delivery_status,
				"message": f"Booked with courier ({provider_code})",
				"logged_at": now_datetime(),
			},
		)

		self._update_reference_status(self.delivery_status)

	def get_tracking_url(self) -> str:
		"""Return tracking URL based on courier_provider and tracking_code/consignment_id."""
		code = self.tracking_code or self.consignment_id
		if not code:
			return getattr(self, "tracking_url", "") or ""
		provider_code = ""
		if self.courier_provider:
			provider_code = frappe.db.get_value("Courier Provider", self.courier_provider, "provider_code") or ""

		if provider_code == "steadfast" or not provider_code:
			return f"https://steadfast.com.bd/t/{code}"
		elif provider_code == "pathao":
			return f"https://pathao.com/tracking/?consignment_id={code}"
		elif provider_code == "redx":
			return f"https://redx.com.bd/track-order?trackingId={code}"
		return f"https://steadfast.com.bd/t/{code}"

	def on_cancel(self):
		"""Update linked SO/DN custom field on cancel."""
		self._update_reference_status("cancelled")

	# ---------------------------------------------------------------------------
	# Validation helpers
	# ---------------------------------------------------------------------------

	def _validate_phone(self):
		phone = (self.recipient_phone or "").strip()
		if not BD_PHONE_REGEX.match(phone):
			frappe.throw(
				_(
					"Recipient phone <b>{0}</b> is not a valid Bangladeshi mobile number. "
					"It must be 11 digits starting with 01[3-9]."
				).format(phone)
			)

	def _truncate_address(self):
		if self.recipient_address and len(self.recipient_address) > MAX_ADDRESS_LEN:
			self.recipient_address = self.recipient_address[:MAX_ADDRESS_LEN]

	def _truncate_raw_response(self):
		if self.raw_response and len(self.raw_response) > MAX_RAW_RESPONSE_LEN:
			self.raw_response = self.raw_response[:MAX_RAW_RESPONSE_LEN] + "\n... [truncated]"

	# ---------------------------------------------------------------------------
	# Status & logging
	# ---------------------------------------------------------------------------

	def update_status(self, new_status: str, message: str = "", commit: bool = False):
		"""Update delivery_status, append a log row, and save.

		Safe to call from background jobs / API methods on an already-loaded doc.
		"""
		old_status = self.delivery_status
		self.db_set("delivery_status", new_status, update_modified=False)
		self.db_set("last_synced_on", now_datetime(), update_modified=False)

		# Append log row (uses direct DB insert to avoid re-loading full doc)
		log_entry = frappe.get_doc(
			{
				"doctype": "Delivery Order Log",
				"parenttype": "Delivery Order",
				"parent": self.name,
				"parentfield": "delivery_logs",
				"status": new_status,
				"message": message or f"Status changed from {old_status} to {new_status}",
				"logged_at": now_datetime(),
			}
		)
		log_entry.db_insert()

		if commit:
			frappe.db.commit()

		# Mirror status on the linked SO/DN
		self._update_reference_status(new_status)

		# Accounting integration triggers
		try:
			from delivery_system.accounting import post_clearing_entry, reverse_clearing_entry
			if new_status == "delivered":
				post_clearing_entry(self)
			elif new_status in ("cancelled", "partial_delivered") and getattr(self, "clearing_entry_posted", 0):
				reverse_clearing_entry(self)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "DeliveryOrder.update_status.accounting")

	def _update_reference_status(self, status: str):
		"""Push delivery_status and tracking_url to the custom field on linked Sales Order / Delivery Note."""
		if not (self.reference_doctype and self.reference_name):
			return
		try:
			frappe.db.set_value(
				self.reference_doctype,
				self.reference_name,
				{
					"courier_status": status,
					"delivery_order_ref": self.name,
					"tracking_url": self.get_tracking_url(),
				},
			)
		except Exception:
			# Non-fatal — the fields may not exist if the patch hasn't run
			frappe.log_error(frappe.get_traceback(), "DeliveryOrder._update_reference_status")

	# ---------------------------------------------------------------------------
	# Utility
	# ---------------------------------------------------------------------------

	@staticmethod
	def is_terminal(status: str) -> bool:
		return status in TERMINAL_STATUSES
