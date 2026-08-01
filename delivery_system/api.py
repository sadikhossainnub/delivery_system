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


def calculate_cod_amount(ref_doc) -> float:
	"""Calculate the Cash On Delivery (COD) amount for a Sales Order or Delivery Note.

	If customer has already paid in advance (fully or partially), COD amount is adjusted
	so the courier only collects the remaining unpaid balance.
	If fully paid in advance, COD amount is 0.
	"""
	if not ref_doc:
		return 0.0

	# 1. If marked as paid via boolean flag or payment status / order status
	if ref_doc.get("is_paid"):
		return 0.0

	payment_status = str(ref_doc.get("payment_status") or "").strip().lower()
	if payment_status in ("paid", "fully paid", "completed"):
		return 0.0

	doc_status = str(ref_doc.get("status") or "").strip().lower()
	if doc_status in ("paid", "completed"):
		return 0.0

	per_paid = frappe.utils.flt(ref_doc.get("per_paid"))
	if per_paid >= 100.0:
		return 0.0

	total_amount = frappe.utils.flt(ref_doc.get("rounded_total") or ref_doc.get("grand_total") or 0.0)

	# 2. Check direct outstanding_amount if present on the doc
	if ref_doc.get("outstanding_amount") is not None and ref_doc.get("outstanding_amount") != "":
		outstanding = frappe.utils.flt(ref_doc.get("outstanding_amount"))
		if outstanding <= 0:
			return 0.0
		return max(0.0, float(outstanding))

	# 3. Advance paid or paid amount directly on the doc
	advance_paid = frappe.utils.flt(ref_doc.get("advance_paid") or 0.0)
	paid_amount = frappe.utils.flt(ref_doc.get("paid_amount") or 0.0)
	total_paid = max(advance_paid, paid_amount)

	ref_doctype = getattr(ref_doc, "doctype", "") or ref_doc.get("doctype") or ""
	ref_name = getattr(ref_doc, "name", "") or ref_doc.get("name") or ""

	# 4. Check DB for linked Payment Entries and Sales Invoices if reference exists
	db_paid = 0.0
	if ref_doctype and ref_name and getattr(frappe, "db", None) and hasattr(frappe.db, "sql"):
		try:
			# Check submitted Payment Entries linked to this reference doc
			pe_allocated = frappe.db.sql(
				"""
				SELECT SUM(allocated_amount)
				FROM `tabPayment Entry Reference`
				WHERE reference_doctype = %s AND reference_name = %s AND docstatus = 1
				""",
				(ref_doctype, ref_name),
			)
			if pe_allocated and pe_allocated[0][0]:
				db_paid += frappe.utils.flt(pe_allocated[0][0])

			# Check linked Sales Invoices if reference is Sales Order
			if ref_doctype == "Sales Order":
				si_list = frappe.db.sql(
					"""
					SELECT DISTINCT parent
					FROM `tabSales Invoice Item`
					WHERE sales_order = %s AND docstatus = 1
					""",
					(ref_name,),
					as_dict=True,
				)
				if si_list:
					all_si_paid = True
					si_total_paid = 0.0
					for row in si_list:
						si_doc = frappe.db.get_value(
							"Sales Invoice",
							row.parent,
							["grand_total", "outstanding_amount", "status", "is_paid"],
							as_dict=True,
						)
						if si_doc:
							if si_doc.is_paid or str(si_doc.status or "").lower() in ("paid", "completed") or frappe.utils.flt(si_doc.outstanding_amount) <= 0:
								si_total_paid += frappe.utils.flt(si_doc.grand_total)
							else:
								all_si_paid = False
								si_total_paid += max(0.0, frappe.utils.flt(si_doc.grand_total) - frappe.utils.flt(si_doc.outstanding_amount))
					if all_si_paid and si_list:
						return 0.0
					db_paid += si_total_paid

			# Check linked Sales Invoices & Sales Order if reference is Delivery Note (Sales Order -> Delivery Note -> Sales Invoice workflow)
			elif ref_doctype == "Delivery Note":
				dn_si_list = frappe.db.sql(
					"""
					SELECT DISTINCT parent
					FROM `tabSales Invoice Item`
					WHERE delivery_note = %s AND docstatus = 1
					""",
					(ref_name,),
					as_dict=True,
				)
				if dn_si_list:
					all_dn_si_paid = True
					dn_si_paid_sum = 0.0
					for row in dn_si_list:
						si_doc = frappe.db.get_value(
							"Sales Invoice",
							row.parent,
							["grand_total", "outstanding_amount", "status", "is_paid"],
							as_dict=True,
						)
						if si_doc:
							if si_doc.is_paid or str(si_doc.status or "").lower() in ("paid", "completed") or frappe.utils.flt(si_doc.outstanding_amount) <= 0:
								dn_si_paid_sum += frappe.utils.flt(si_doc.grand_total)
							else:
								all_dn_si_paid = False
								dn_si_paid_sum += max(0.0, frappe.utils.flt(si_doc.grand_total) - frappe.utils.flt(si_doc.outstanding_amount))
					if all_dn_si_paid and dn_si_list:
						return 0.0
					db_paid += dn_si_paid_sum

				so_name = ref_doc.get("against_sales_order") or ref_doc.get("sales_order")
				if not so_name and ref_doc.get("items"):
					so_name = ref_doc.items[0].get("against_sales_order") or ref_doc.items[0].get("sales_order")
				if so_name and frappe.db.exists("Sales Order", so_name):
					so_doc = frappe.get_doc("Sales Order", so_name)
					so_cod = calculate_cod_amount(so_doc)
					if so_cod <= 0:
						return 0.0
					if total_amount > 0:
						cod = min(total_amount - (total_paid + db_paid), so_cod)
						return max(0.0, float(round(cod, 2)))

		except Exception:
			frappe.log_error(frappe.get_traceback(), "calculate_cod_amount.db_check")

	total_paid = max(total_paid, db_paid)
	cod = total_amount - total_paid

	if cod <= 0.01:
		return 0.0

	return max(0.0, float(round(cod, 2)))


@frappe.whitelist()
def get_ref_cod_amount(reference_doctype: str, reference_name: str) -> float:
	"""Return calculated COD amount for a given reference doctype and name."""
	if not reference_doctype or not reference_name or not frappe.db.exists(reference_doctype, reference_name):
		return 0.0
	ref_doc = frappe.get_doc(reference_doctype, reference_name)
	return calculate_cod_amount(ref_doc)


@frappe.whitelist()
def get_delivery_charge(
	delivery_order_name: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> float:
	"""Fetch delivery charge for a given Delivery Order or reference document via courier API or logs."""
	if not delivery_order_name and reference_doctype and reference_name:
		delivery_order_name = frappe.db.get_value(
			"Delivery Order",
			{"reference_doctype": reference_doctype, "reference_name": reference_name, "docstatus": ["!=", 2]},
			"name",
		)

	if not delivery_order_name or not frappe.db.exists("Delivery Order", delivery_order_name):
		return 0.0

	do = frappe.get_doc("Delivery Order", delivery_order_name)
	provider_code = (
		frappe.db.get_value("Courier Provider", do.courier_provider, "provider_code")
		if do.courier_provider
		else "steadfast"
	)
	company = _get_company_from_reference(do.reference_doctype, do.reference_name)

	# 1. Attempt to fetch charge via Courier API
	try:
		client = get_client(provider_code, company)
		if hasattr(client, "get_payments"):
			payments = client.get_payments()
			for p in payments:
				cid = str(p.get("consignment_id") or p.get("cid") or "").strip()
				inv = str(p.get("invoice") or "").strip()
				if (cid and cid == do.consignment_id) or (inv and inv == do.invoice_reference):
					chg = p.get("delivery_charge") or p.get("charge") or p.get("delivery_fee") or p.get("charge_amount")
					if chg is not None:
						return float(chg)

		status_res = client.get_status(
			consignment_id=do.consignment_id or None,
			invoice=do.invoice_reference or None,
		)
		raw = status_res.get("raw") or status_res
		if isinstance(raw, dict):
			for key in ("delivery_charge", "charge", "delivery_fee", "charge_amount"):
				if key in raw and raw[key] is not None:
					return float(raw[key])
	except Exception:
		pass

	# 2. Extract charge from stored raw_response JSON
	if do.raw_response:
		try:
			data = json.loads(do.raw_response)
			consignment = data.get("consignment") or data
			if isinstance(consignment, dict):
				for key in ("delivery_charge", "charge", "delivery_fee", "charge_amount"):
					if key in consignment and consignment[key] is not None:
						return float(consignment[key])
		except Exception:
			pass

	# 3. Check Courier Payout Log
	res = frappe.db.sql(
		"""
		SELECT cpl.delivery_charges_deducted
		FROM `tabCourier Payout Log Item` cpli
		JOIN `tabCourier Payout Log` cpl ON cpl.name = cpli.parent
		WHERE cpli.delivery_order = %s
		LIMIT 1
		""",
		(delivery_order_name,),
	)
	if res and res[0][0] is not None:
		return float(res[0][0])

	return 0.0



@frappe.whitelist()
def send_to_courier(
	reference_doctype: str,
	reference_name: str,
	provider_code: str | None = None,
	recipient_name: str | None = None,
	recipient_phone: str | None = None,
	recipient_address: str | None = None,
	cod_amount: float | str | None = None,
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
	cod_amount: float | str | None = None,
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

	ref_doc = None
	if reference_doctype and reference_name and frappe.db.exists(reference_doctype, reference_name):
		ref_doc = frappe.get_doc(reference_doctype, reference_name)

	if ref_doc:
		if not recipient_name:
			recipient_name = ref_doc.get("customer_name") or ref_doc.get("customer") or ""
		if not recipient_phone:
			recipient_phone = ref_doc.get("customer_mobile_no") or ref_doc.get("contact_mobile") or ref_doc.get("mobile_no") or ""
		if not recipient_address:
			raw_addr = ref_doc.get("shipping_address") or ref_doc.get("customer_address") or ""
			import re
			recipient_address = re.sub(r"<[^>]*>", "", str(raw_addr)).strip() if raw_addr else ""

	if cod_amount is None:
		cod_amount = calculate_cod_amount(ref_doc) if ref_doc else 0.0
	else:
		cod_amount = float(cod_amount)

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
	"""Update courier_status, delivery_order_ref, and tracking_url on the linked SO and DN."""
	if not (reference_doctype and reference_name):
		return
	try:
		do = frappe.get_doc("Delivery Order", delivery_order_name)
		tracking_url = do.get_tracking_url() if hasattr(do, "get_tracking_url") else getattr(do, "tracking_url", "")
		update_dict = {
			"courier_status": status,
			"delivery_order_ref": delivery_order_name,
			"tracking_url": tracking_url,
		}

		if frappe.db.exists(reference_doctype, reference_name):
			frappe.db.set_value(reference_doctype, reference_name, update_dict)

		if reference_doctype == "Delivery Note" and frappe.db.exists("Delivery Note", reference_name):
			dn_doc = frappe.get_doc("Delivery Note", reference_name)
			so_name = dn_doc.get("against_sales_order") or dn_doc.get("sales_order")
			if not so_name and dn_doc.get("items"):
				so_name = dn_doc.items[0].get("against_sales_order") or dn_doc.items[0].get("sales_order")
			if so_name and frappe.db.exists("Sales Order", so_name):
				frappe.db.set_value("Sales Order", so_name, update_dict)
		elif reference_doctype == "Sales Order":
			dn_list = frappe.db.sql(
				"""
				SELECT DISTINCT parent
				FROM `tabDelivery Note Item`
				WHERE against_sales_order = %s OR sales_order = %s
				""",
				(reference_name, reference_name),
				as_dict=True,
			)
			for row in dn_list:
				if frappe.db.exists("Delivery Note", row.parent):
					frappe.db.set_value("Delivery Note", row.parent, update_dict)
	except Exception:
		# Custom fields may not exist yet (patch not applied)
		pass
