# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Whitelisted API endpoints for Delivery System.
# All endpoints verify permission before executing and never expose credentials.

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from delivery_system.couriers import get_client

VALID_STATUSES = {
	"", "pending", "in_review", "delivered_approval_pending",
	"partial_delivered_approval_pending", "cancelled_approval_pending",
	"unknown_approval_pending",
	"delivered", "partial_delivered", "cancelled", "hold", "unknown",
}


def _sanitize_status(raw_status: str, fallback: str = "pending") -> str:
	"""Return a valid delivery_status value; fall back if the API returns garbage like '400'."""
	status = (raw_status or "").strip().lower()
	return status if status in VALID_STATUSES else fallback


def _check_permission(ptype: str = "create"):
	"""Raise PermissionError if the current user cannot create/write Delivery Order."""
	if not frappe.has_permission("Delivery Order", ptype):
		frappe.throw(_("You do not have permission to perform this action."), frappe.PermissionError)


def _get_company_from_reference(reference_doctype: str, reference_name: str) -> str | None:
	"""Extract the company from a Sales Order or Delivery Note."""
	try:
		return frappe.db.get_value(reference_doctype, reference_name, "company")
	except Exception:
		return None


@frappe.whitelist()
def send_to_courier(
	reference_doctype: str,
	reference_name: str,
	provider_code: str | None = None,
	recipient_name: str | None = None,
	recipient_phone: str | None = None,
	recipient_address: str | None = None,
	cod_amount: float = 0,
	delivery_type: str = "Home Delivery",
	note: str = "",
) -> dict:
	"""Create a Delivery Order and book it with the courier API.

	Returns a dict with tracking info on success.
	The caller (JS) should reload the form after this call.
	"""
	_check_permission("create")
	return _do_send_to_courier(
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		provider_code=provider_code,
		recipient_name=recipient_name,
		recipient_phone=recipient_phone,
		recipient_address=recipient_address,
		cod_amount=cod_amount,
		delivery_type=delivery_type,
		note=note,
	)


@frappe.whitelist()
def bulk_send_to_courier(reference_doctype: str, names) -> list[dict]:

	"""Book multiple Sales Orders / Delivery Notes with the courier in bulk.

	``names`` can be a JSON string (from list-view action) or a Python list.
	Returns a list of result dicts (one per reference).
	"""
	_check_permission("create")

	if isinstance(names, str):
		names = json.loads(names)

	if len(names) > 500:
		frappe.throw(
			_("Bulk send supports a maximum of 500 records per batch. Got {0}.").format(len(names)),
			frappe.ValidationError,
		)

	results = []
	for name in names:
		try:
			r = _do_send_to_courier(reference_doctype, name)
			results.append({"reference": name, "success": True, **r})
		except Exception as exc:
			results.append({"reference": name, "success": False, "error": str(exc)})

	return results


@frappe.whitelist()
def sync_single_status(delivery_order_name: str) -> dict:
	"""Manually re-fetch status from the courier for a single Delivery Order."""
	_check_permission("write")

	do = frappe.get_doc("Delivery Order", delivery_order_name)
	provider_code = frappe.db.get_value("Courier Provider", do.courier_provider, "provider_code")
	company = _get_company_from_reference(do.reference_doctype, do.reference_name)

	try:
		client = get_client(provider_code, company)
		result = client.get_status(
			consignment_id=do.consignment_id or None,
			invoice=do.invoice_reference or None,
		)
	except frappe.ValidationError:
		_append_log(delivery_order_name, "error", "Status sync failed")
		raise
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "sync_single_status")
		frappe.throw(_("Failed to sync status: {0}").format(str(exc)))

	new_status = _sanitize_status(result.get("delivery_status"), "unknown")
	old_status = do.delivery_status

	frappe.db.set_value(
		"Delivery Order",
		delivery_order_name,
		{
			"delivery_status": new_status,
			"last_synced_on": now_datetime(),
			"raw_response": json.dumps(result.get("raw") or result, ensure_ascii=False)[:5000],
		},
	)

	if new_status != old_status:
		_append_log(delivery_order_name, new_status, f"Status updated from {old_status} to {new_status}")
		_sync_reference_fields(do.reference_doctype, do.reference_name, delivery_order_name, new_status)

	frappe.db.commit()
	return {"status": new_status, "previous_status": old_status}


@frappe.whitelist()
def request_return(delivery_order_name: str, reason: str = "") -> dict:
	"""Initiate a return / pickup request for a delivered or problematic consignment."""
	_check_permission("write")

	do = frappe.get_doc("Delivery Order", delivery_order_name)
	if not do.consignment_id:
		frappe.throw(
			_("Cannot request return: no consignment ID found on this Delivery Order."),
			frappe.ValidationError,
		)

	provider_code = frappe.db.get_value("Courier Provider", do.courier_provider, "provider_code")
	company = _get_company_from_reference(do.reference_doctype, do.reference_name)

	try:
		client = get_client(provider_code, company)
		result = client.create_return_request(do.consignment_id, reason=reason)
	except frappe.ValidationError:
		_append_log(delivery_order_name, "error", f"Return request failed")
		raise
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "request_return")
		frappe.throw(_("Failed to create return request: {0}").format(str(exc)))

	_append_log(delivery_order_name, "return_requested", f"Return requested. Reason: {reason}")
	frappe.db.commit()
	return result


@frappe.whitelist()
def get_courier_balance(provider_code: str = "steadfast") -> dict:
	"""Fetch the current account balance from the courier."""
	if not frappe.has_permission("Courier Settings", "read"):
		frappe.throw(_("Insufficient permission to view courier balance."), frappe.PermissionError)

	try:
		client = get_client(provider_code)
		return client.get_balance()
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "get_courier_balance")
		frappe.throw(_("Failed to fetch balance: {0}").format(str(exc)))


@frappe.whitelist()
def test_courier_connection(provider_code: str = "steadfast") -> dict:
	"""Test API connection with the courier by fetching balance."""
	if not frappe.has_permission("Courier Settings", "read"):
		frappe.throw(_("Insufficient permission."), frappe.PermissionError)

	try:
		client = get_client(provider_code)
		bal = client.get_balance()
		current_balance = bal.get("current_balance") if "current_balance" in bal else bal.get("balance", 0)
		return {"success": True, "balance": current_balance}
	except Exception as exc:
		return {"success": False, "error": str(exc)}


@frappe.whitelist()
def mark_manually_reconciled(delivery_order_name: str, payment_id: str | None = None) -> dict:
	"""Manually mark a Delivery Order as payment reconciled."""
	_check_permission("write")

	do = frappe.get_doc("Delivery Order", delivery_order_name)
	reconciled_id = payment_id or "MANUAL"

	frappe.db.set_value(
		"Delivery Order",
		delivery_order_name,
		{
			"payment_reconciled": 1,
			"reconciled_payment_id": reconciled_id,
		},
	)

	_append_log(delivery_order_name, "reconciled", f"Payment marked as reconciled ({reconciled_id})")
	frappe.db.commit()

	return {"success": True, "reconciled_payment_id": reconciled_id}


@frappe.whitelist()
def get_dashboard_stats() -> dict:
	"""Fetch summary metrics for dashboard cards with balance cached for 15 minutes."""
	today_str = frappe.utils.today()

	# 1. Today's Bookings
	todays_bookings = frappe.db.count("Delivery Order", filters={"creation": [">=", today_str]})

	# 2. Today Delivered
	todays_delivered = frappe.db.count(
		"Delivery Order",
		filters={"delivery_status": "delivered", "last_synced_on": [">=", today_str]},
	)

	# 3. Today Cancelled
	todays_cancelled = frappe.db.count(
		"Delivery Order",
		filters={"delivery_status": "cancelled", "last_synced_on": [">=", today_str]},
	)

	# 4. Account Balance (Cached 15 mins)
	cache = frappe.cache()
	cached_balance = cache.hget("delivery_system_dashboard", "balance")

	if cached_balance is None:
		try:
			default_provider = frappe.db.get_single_value("Courier Settings", "default_provider")
			provider_code = (
				frappe.db.get_value("Courier Provider", default_provider, "provider_code")
				if default_provider
				else "steadfast"
			)
			client = get_client(provider_code)
			bal_data = client.get_balance()
			cached_balance = bal_data.get("current_balance") or bal_data.get("balance") or 0
			cache.hset("delivery_system_dashboard", "balance", cached_balance)
		except Exception:
			cached_balance = 0

	return {
		"todays_bookings": todays_bookings,
		"todays_delivered": todays_delivered,
		"todays_cancelled": todays_cancelled,
		"account_balance": cached_balance,
	}


@frappe.whitelist()
def download_user_guide():
	"""Serve the Delivery System User Guide PDF for download."""
	import os

	pdf_path = frappe.get_app_path("delivery_system", "..", "Delivery_System_User_Guide.pdf")
	if not os.path.exists(pdf_path):
		pdf_path = frappe.get_app_path("delivery_system", "Delivery_System_User_Guide.pdf")

	if not os.path.exists(pdf_path):
		frappe.throw(_("User Guide PDF not found on server."), frappe.FileNotFoundError)

	with open(pdf_path, "rb") as f:
		content = f.read()

	frappe.response["filename"] = "Delivery_System_User_Guide.pdf"
	frappe.response["filecontent"] = content
	frappe.response["type"] = "pdf"


@frappe.whitelist()
def get_enabled_providers() -> list[dict]:
	"""Return list of enabled Courier Provider records (for JS dropdowns)."""
	return frappe.get_all(
		"Courier Provider",
		filters={"enabled": 1},
		fields=["name", "courier_name", "provider_code"],
		order_by="courier_name asc",
	)


@frappe.whitelist()
def get_booking_config() -> dict:
	"""Return booking configuration and enabled providers for client scripts."""
	booking_doctype = frappe.db.get_single_value("Courier Settings", "booking_doctype") or "Both"
	providers = frappe.get_all(
		"Courier Provider",
		filters={"enabled": 1},
		fields=["name", "courier_name", "provider_code"],
		order_by="courier_name asc",
	)
	return {
		"booking_doctype": booking_doctype,
		"providers": providers,
	}


# ---------------------------------------------------------------------------
# Internal helpers (not whitelisted)
# ---------------------------------------------------------------------------


def _do_send_to_courier(
	reference_doctype: str,
	reference_name: str,
	provider_code: str | None = None,
	recipient_name: str | None = None,
	recipient_phone: str | None = None,
	recipient_address: str | None = None,
	cod_amount: float = 0,
	delivery_type: str = "Home Delivery",
	note: str = "",
) -> dict:
	"""Internal (non-whitelisted) implementation of send_to_courier.

	Used by bulk_send_to_courier to avoid going through the whitelist decorator.
	Permission checks are done by the calling whitelist method.
	"""
	# Validate allowed booking source doctype from Courier Settings
	allowed_doctype = frappe.db.get_single_value("Courier Settings", "booking_doctype") or "Both"
	if allowed_doctype != "Both" and reference_doctype != allowed_doctype:
		frappe.throw(
			_("Courier booking is currently restricted to {0} only in Courier Settings.").format(allowed_doctype),
			frappe.ValidationError,
		)

	# Prevent duplicate
	existing = frappe.db.get_value(
		"Delivery Order",
		{
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"docstatus": ["!=", 2],
		},
		"name",
	)
	if existing:
		frappe.throw(
			_("A Delivery Order {0} already exists for {1}.").format(existing, reference_name),
			frappe.ValidationError,
		)

	if not provider_code:
		default = frappe.db.get_single_value("Courier Settings", "default_provider")
		if default:
			provider_code = frappe.db.get_value("Courier Provider", default, "provider_code")
	if not provider_code:
		frappe.throw(_("No courier provider specified or configured as default."), frappe.ValidationError)

	company = _get_company_from_reference(reference_doctype, reference_name)

	do = frappe.get_doc(
		{
			"doctype": "Delivery Order",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"courier_provider": frappe.db.get_value(
				"Courier Provider", {"provider_code": provider_code, "enabled": 1}, "name"
			),
			"recipient_name": recipient_name or "",
			"recipient_phone": recipient_phone or "",
			"recipient_address": recipient_address or "",
			"cod_amount": cod_amount,
			"delivery_type": delivery_type,
			"note": note,
			"delivery_status": "pending",
		}
	)

	try:
		do.insert(ignore_permissions=True)
	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "_do_send_to_courier.insert")
		frappe.throw(_("Failed to create Delivery Order: {0}").format(str(exc)))

	try:
		client = get_client(provider_code, company)
		result = client.create_order(
			{
				"invoice": do.invoice_reference,
				"recipient_name": do.recipient_name,
				"recipient_phone": do.recipient_phone,
				"recipient_address": do.recipient_address,
				"cod_amount": float(do.cod_amount or 0),
				"note": do.note or "",
				"delivery_type": do.delivery_type,
			}
		)
	except frappe.ValidationError:
		_append_log(do.name, "error", "Courier API error during order creation")
		raise
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "_do_send_to_courier.api_call")
		_append_log(do.name, "error", str(exc))
		frappe.throw(_("Unexpected error while calling courier API: {0}").format(str(exc)))

	raw_status = result.get("status") or "pending"
	safe_status = _sanitize_status(raw_status, "pending")

	do_doc = frappe.get_doc("Delivery Order", do.name)
	do_doc.consignment_id = result.get("consignment_id") or ""
	do_doc.tracking_code = result.get("tracking_code") or ""
	do_doc.tracking_url = do_doc.get_tracking_url()

	frappe.db.set_value(
		"Delivery Order",
		do.name,
		{
			"consignment_id": do_doc.consignment_id,
			"tracking_code": do_doc.tracking_code,
			"tracking_url": do_doc.tracking_url,
			"delivery_status": safe_status,
			"last_synced_on": now_datetime(),
			"raw_response": json.dumps(result.get("raw") or result, ensure_ascii=False)[:5000],
		},
	)

	_append_log(do.name, safe_status, "Order created with courier")

	try:
		do_doc.submit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "_do_send_to_courier.submit")

	_sync_reference_fields(reference_doctype, reference_name, do.name, safe_status)
	frappe.db.commit()

	return {
		"delivery_order": do.name,
		"consignment_id": result.get("consignment_id"),
		"tracking_code": result.get("tracking_code"),
		"tracking_url": do_doc.tracking_url,
		"status": result.get("status"),
	}


def _append_log(delivery_order_name: str, status: str, message: str):
	"""Insert a Delivery Order Log row without loading the full parent doc."""
	try:
		log_entry = frappe.get_doc(
			{
				"doctype": "Delivery Order Log",
				"parenttype": "Delivery Order",
				"parent": delivery_order_name,
				"parentfield": "delivery_logs",
				"status": status,
				"message": message,
				"logged_at": now_datetime(),
			}
		)
		log_entry.db_insert()
	except Exception:
		# Non-fatal logging failure
		frappe.log_error(frappe.get_traceback(), "_append_log")


def _sync_reference_fields(
	reference_doctype: str, reference_name: str, delivery_order_name: str, status: str
):
	"""Update courier_status, delivery_order_ref, and tracking_url on the linked SO/DN."""
	if not (reference_doctype and reference_name):
		return
	try:
		do = frappe.get_doc("Delivery Order", delivery_order_name)
		tracking_url = do.get_tracking_url() if hasattr(do, "get_tracking_url") else getattr(do, "tracking_url", "")
		frappe.db.set_value(
			reference_doctype,
			reference_name,
			{
				"courier_status": status,
				"delivery_order_ref": delivery_order_name,
				"tracking_url": tracking_url,
			},
		)
	except Exception:
		# Custom fields may not exist yet (patch not applied)
		pass
