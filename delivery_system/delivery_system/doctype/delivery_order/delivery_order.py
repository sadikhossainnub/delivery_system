# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

# Status groups for easier comparisons
TERMINAL_STATUSES = {"delivered", "cancelled", "partial_delivered"}
BD_PHONE_REGEX = re.compile(r"^01[3-9]\d{8}$")
MAX_ADDRESS_LEN = 250
MAX_RAW_RESPONSE_LEN = 5000  # cap stored JSON to avoid DB bloat


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
			frappe.throw(
				_(
					"Cannot submit Delivery Order without a Consignment ID. "
					"Please click 'Send to Courier' first."
				)
			)

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
		"""Push delivery_status to the custom field on linked Sales Order / Delivery Note."""
		if not (self.reference_doctype and self.reference_name):
			return
		try:
			frappe.db.set_value(
				self.reference_doctype,
				self.reference_name,
				{
					"courier_status": status,
					"delivery_order_ref": self.name,
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
