# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Scheduled background tasks for the Delivery System.
# Registered in hooks.py scheduler_events.

from __future__ import annotations

import time

import frappe
from frappe.utils import now_datetime

# Statuses that don't need further polling
TERMINAL_STATUSES = {"delivered", "cancelled", "partial_delivered"}

# Delay between individual API calls to respect rate limits (seconds)
RATE_LIMIT_DELAY = 0.3


def sync_pending_deliveries():
	"""Scheduled job: poll courier API for status updates on all non-terminal Delivery Orders.

	Runs every 30 minutes (configured in hooks.py).
	- Groups records by provider+company to reuse client instances
	- Respects a configurable auto_sync_status toggle
	- Logs any status changes to Delivery Order Log
	"""
	settings = frappe.get_single("Courier Settings")

	if not settings.auto_sync_status:
		return

	pending = frappe.get_all(
		"Delivery Order",
		filters={
			"docstatus": 1,
			"delivery_status": ["not in", list(TERMINAL_STATUSES)],
			"consignment_id": ["!=", ""],
		},
		fields=["name", "courier_provider", "consignment_id", "invoice_reference", "delivery_status", "reference_doctype", "reference_name"],
		order_by="modified asc",
	)

	if not pending:
		return

	frappe.logger("delivery_system").info(f"sync_pending_deliveries: syncing {len(pending)} orders")

	# Group by (provider_code, company) to reuse clients
	from delivery_system.couriers import get_client

	client_cache: dict[tuple, object] = {}
	errors = []

	for record in pending:
		provider_code = frappe.db.get_value(
			"Courier Provider", record.courier_provider, "provider_code"
		)
		company = frappe.db.get_value(record.reference_doctype, record.reference_name, "company") if record.reference_doctype and record.reference_name else None

		cache_key = (provider_code, company)
		if cache_key not in client_cache:
			try:
				client_cache[cache_key] = get_client(provider_code, company)
			except Exception as exc:
				errors.append(f"{record.name}: {exc}")
				continue

		client = client_cache[cache_key]

		try:
			result = client.get_status(consignment_id=record.consignment_id)
			new_status = (result.get("delivery_status") or "unknown").lower()

			if new_status != record.delivery_status:
				do = frappe.get_doc("Delivery Order", record.name)
				do.update_status(
					new_status,
					message=f"Scheduled sync: status changed from {record.delivery_status} to {new_status}",
					commit=False,
				)
				frappe.logger("delivery_system").info(
					f"{record.name}: {record.delivery_status} → {new_status}"
				)

		except Exception as exc:
			errors.append(f"{record.name}: {exc}")
			frappe.log_error(frappe.get_traceback(), f"sync_pending_deliveries.{record.name}")

		# Rate limiting
		time.sleep(RATE_LIMIT_DELAY)

	frappe.db.commit()

	if errors:
		frappe.log_error(
			"\n".join(errors),
			"sync_pending_deliveries.errors",
		)


def notify_stuck_deliveries():
	"""Daily job: find deliveries stuck for >= 3 days and log digest for ops team."""
	from delivery_system.delivery_system.report.pending_stuck_deliveries.pending_stuck_deliveries import (
		get_data,
	)

	stuck_orders = get_data({"min_days_pending": 3})
	if not stuck_orders:
		return

	summary_msg = f"Delivery System Digest: {len(stuck_orders)} orders stuck for >= 3 days.\n\n"
	for item in stuck_orders[:10]:
		summary_msg += f"- {item['name']} ({item['customer']}): {item['days_pending']} days pending, Status: {item['delivery_status']}\n"

	frappe.logger("delivery_system").info(summary_msg)
	frappe.log_error(summary_msg, "notify_stuck_deliveries.digest")


def sync_courier_payouts():
	"""Scheduled job: fetch payout statements from courier APIs and auto-create Courier Payout records."""
	settings = frappe.get_single("Courier Settings")
	if not settings.enable_accounting_automation:
		return

	from delivery_system.accounting import post_payout_entries
	from delivery_system.couriers import get_client

	default_provider = settings.default_provider
	if not default_provider:
		return

	provider_code = (
		frappe.db.get_value("Courier Provider", default_provider, "provider_code") or "steadfast"
	)

	try:
		client = get_client(provider_code)
		if not hasattr(client, "get_payments"):
			return

		raw_payments = client.get_payments()
		if not raw_payments:
			return

		for p in raw_payments:
			payment_id = str(p.get("payment_id") or p.get("id") or "").strip()
			if not payment_id:
				continue

			if frappe.db.exists("Courier Payout", {"payment_id": payment_id}):
				continue

			cid = str(p.get("consignment_id") or p.get("cid") or "").strip()
			inv = str(p.get("invoice") or "").strip()

			filters = {"docstatus": 1}
			if cid:
				filters["consignment_id"] = cid
			elif inv:
				filters["invoice_reference"] = inv
			else:
				continue

			matched_orders = frappe.get_all(
				"Delivery Order",
				filters=filters,
				fields=["name", "cod_amount"],
			)

			post_payout_entries(p, matched_orders)

		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "sync_courier_payouts")


