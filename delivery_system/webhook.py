# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Inbound webhook handler for courier status push notifications.
# Endpoint: /api/method/delivery_system.webhook.steadfast_webhook
#
# Steadfast does not currently provide HMAC-signed webhooks, so we
# rely on an IP allowlist configured in Courier Settings.
# When/if Steadfast adds webhook signing, add HMAC verification here.

from __future__ import annotations

import hashlib
import hmac
import json

import frappe
from frappe import _
from frappe.utils import now_datetime


# ---------------------------------------------------------------------------
# Public webhook endpoints (unauthenticated — verified by IP or HMAC)
# ---------------------------------------------------------------------------


@frappe.whitelist(allow_guest=True)
def steadfast_webhook():
	"""Receive inbound status push from Steadfast.

	Expected payload (Steadfast format):
	{
	  "consignment_id": "...",
	  "invoice": "...",
	  "status": "delivered" | "cancelled" | ...,
	  "message": "...",
	  ...
	}

	Heavy processing is offloaded to a background job so we return 200 quickly.
	"""
	try:
		payload = _parse_payload()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "steadfast_webhook.parse")
		frappe.response["http_status_code"] = 400
		return {"status": "error", "message": "Invalid payload"}

	# IP allowlist check (optional — skip if no allowlist configured)
	_check_ip_allowlist()

	# Enqueue background processing
	frappe.enqueue(
		"delivery_system.webhook._process_steadfast_webhook",
		queue="short",
		payload=payload,
		now=frappe.flags.in_test,  # run synchronously in tests
	)

	frappe.response["http_status_code"] = 200
	return {"status": "ok"}


# ---------------------------------------------------------------------------
# Background processor
# ---------------------------------------------------------------------------


def _process_steadfast_webhook(payload: dict):
	"""Process a Steadfast webhook payload (runs in background job)."""
	consignment_id = str(payload.get("consignment_id") or "").strip()
	invoice = str(payload.get("invoice") or "").strip()
	new_status = str(payload.get("status") or "unknown").lower()
	message = str(payload.get("message") or "")

	# Find matching Delivery Order
	delivery_order_name = None

	if consignment_id:
		delivery_order_name = frappe.db.get_value(
			"Delivery Order", {"consignment_id": consignment_id, "docstatus": 1}, "name"
		)

	if not delivery_order_name and invoice:
		delivery_order_name = frappe.db.get_value(
			"Delivery Order", {"invoice_reference": invoice, "docstatus": 1}, "name"
		)

	if not delivery_order_name:
		frappe.log_error(
			f"Steadfast webhook: no matching Delivery Order for consignment_id={consignment_id!r} invoice={invoice!r}",
			"steadfast_webhook.no_match",
		)
		return

	try:
		do = frappe.get_doc("Delivery Order", delivery_order_name)
		old_status = do.delivery_status

		if new_status == old_status:
			return  # no change, nothing to do

		do.update_status(new_status, message=message or f"Webhook: {new_status}", commit=True)

		# Notification hook point for WhatsApp/Evolution API integration
		if new_status in ("delivered", "cancelled", "partial_delivered"):
			_fire_status_notification(do, new_status)

	except Exception:
		frappe.log_error(frappe.get_traceback(), "steadfast_webhook._process")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_payload() -> dict:
	"""Parse the inbound request body as JSON."""
	request = frappe.request
	if request.content_type and "application/json" in request.content_type:
		body = request.get_data(as_text=True)
		return json.loads(body) if body else {}
	# Fallback: form data
	return dict(frappe.form_dict)


def _check_ip_allowlist():
	"""Block requests from IPs not in the allowlist (if configured).

	Allowlist is stored as a newline-separated Data field on Courier Settings
	named `webhook_ip_allowlist`. If empty, all IPs are allowed.
	"""
	allowlist_raw = frappe.db.get_single_value("Courier Settings", "webhook_ip_allowlist") or ""
	allowed_ips = [ip.strip() for ip in allowlist_raw.splitlines() if ip.strip()]

	if not allowed_ips:
		return  # no restriction configured

	remote_addr = (
		frappe.request.headers.get("X-Forwarded-For", frappe.request.remote_addr) or ""
	).split(",")[0].strip()

	if remote_addr not in allowed_ips:
		frappe.log_error(f"Webhook blocked from IP: {remote_addr}", "steadfast_webhook.ip_block")
		frappe.throw(_("Access denied from this IP address."), frappe.PermissionError)


def _verify_hmac_signature(secret: str, payload_bytes: bytes, signature_header: str) -> bool:
	"""Verify an HMAC-SHA256 signature (for future use when Steadfast supports it)."""
	expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected, signature_header)


def _fire_status_notification(do, status: str):
	"""Hook point for downstream notification integrations (WhatsApp/SMS etc.).

	Override or extend this in a site-specific app. Currently a no-op.
	"""
	# Example integration point:
	# frappe.publish_realtime("courier_status_update", {
	#     "delivery_order": do.name,
	#     "reference": do.reference_name,
	#     "status": status,
	# })
	pass
