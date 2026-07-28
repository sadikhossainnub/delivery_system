# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

"""
Backend methods for Delivery System Number Cards and Dashboard Charts.
All methods are whitelisted for use with Frappe Number Card (type=Custom)
and Dashboard Chart (type=Custom) records.
"""

import frappe
from frappe.utils import today, get_first_day, get_last_day, add_months, add_days, getdate, flt


# ---------------------------------------------------------------------------
# Number Card Methods
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_courier_balance_card(company=None):
	"""1.1 — Steadfast Current Balance (cached 15 mins)."""
	cache_key = "steadfast_balance_card"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return {"value": flt(cached), "fieldtype": "Currency"}

	try:
		from delivery_system.couriers import get_client
		client = get_client("steadfast")
		bal_data = client.get_balance()
		balance = flt(bal_data.get("current_balance") or bal_data.get("balance") or 0)
		frappe.cache().set_value(cache_key, balance, expires_in_sec=900)
		return {"value": balance, "fieldtype": "Currency"}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "get_courier_balance_card")
		return {"value": 0, "fieldtype": "Currency"}


@frappe.whitelist()
def get_clearing_account_balance(company=None):
	"""1.2 — Total Outstanding COD (Clearing Account balance from GL)."""
	if not company:
		company = frappe.defaults.get_user_default("Company")
	if not company:
		return {"value": 0, "fieldtype": "Currency"}

	# Find the clearing account for this company
	clearing_account = _get_clearing_account(company)
	if not clearing_account:
		return {"value": 0, "fieldtype": "Currency"}

	# Sum GL entries: debit - credit = outstanding balance in clearing account
	result = frappe.db.sql("""
		SELECT IFNULL(SUM(debit - credit), 0) as balance
		FROM `tabGL Entry`
		WHERE account = %s AND company = %s AND is_cancelled = 0
	""", (clearing_account, company), as_dict=True)

	balance = flt(result[0].balance) if result else 0
	return {"value": balance, "fieldtype": "Currency"}


@frappe.whitelist()
def get_stuck_deliveries_count(company=None):
	"""1.6 — Stuck Deliveries (3+ days pending)."""
	min_days = 3
	try:
		min_days = frappe.db.get_single_value("Courier Settings", "min_days_pending") or 3
	except Exception:
		pass

	filters = {
		"delivery_status": ["in", ["pending", "in_review"]],
		"creation": ["<=", add_days(today(), -min_days)],
		"docstatus": ["<", 2],
	}
	if company:
		# Filter by company via reference doctype
		pass  # Delivery Order doesn't have a direct company field

	count = frappe.db.count("Delivery Order", filters=filters)
	return {"value": count, "fieldtype": "Int"}


@frappe.whitelist()
def get_monthly_cod_collected(company=None):
	"""1.8 — This Month's COD Collected (sum net_amount from Courier Payout Log)."""
	first_day = get_first_day(today())
	last_day = get_last_day(today())

	filters = {
		"payout_date": ["between", [first_day, last_day]],
	}

	result = frappe.db.sql("""
		SELECT IFNULL(SUM(net_amount), 0) as total
		FROM `tabCourier Payout Log`
		WHERE payout_date BETWEEN %s AND %s
	""", (first_day, last_day), as_dict=True)

	total = flt(result[0].total) if result else 0
	return {"value": total, "fieldtype": "Currency"}


@frappe.whitelist()
def get_monthly_delivery_charges(company=None):
	"""1.9 — This Month's Delivery Charges (sum delivery_charges_deducted)."""
	first_day = get_first_day(today())
	last_day = get_last_day(today())

	result = frappe.db.sql("""
		SELECT IFNULL(SUM(delivery_charges_deducted), 0) as total
		FROM `tabCourier Payout Log`
		WHERE payout_date BETWEEN %s AND %s
	""", (first_day, last_day), as_dict=True)

	total = flt(result[0].total) if result else 0
	return {"value": total, "fieldtype": "Currency"}


# ---------------------------------------------------------------------------
# Dashboard Chart Methods
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_daily_delivery_trend(company=None, courier_provider=None):
	"""2.2 — Daily Bookings vs Delivered vs Cancelled (last 30 days)."""
	end_date = getdate(today())
	start_date = add_days(end_date, -29)

	# Build date range labels
	labels = []
	d = start_date
	while d <= end_date:
		labels.append(str(d))
		d = add_days(d, 1)

	company_filter = ""
	params = [str(start_date), str(end_date)]

	# Bookings by creation date
	bookings_data = frappe.db.sql("""
		SELECT DATE(creation) as dt, COUNT(*) as cnt
		FROM `tabDelivery Order`
		WHERE DATE(creation) BETWEEN %s AND %s
		GROUP BY DATE(creation)
	""", params, as_dict=True)

	# Delivered by last_synced_on
	delivered_data = frappe.db.sql("""
		SELECT DATE(last_synced_on) as dt, COUNT(*) as cnt
		FROM `tabDelivery Order`
		WHERE delivery_status = 'delivered'
		  AND DATE(last_synced_on) BETWEEN %s AND %s
		GROUP BY DATE(last_synced_on)
	""", params, as_dict=True)

	# Cancelled by last_synced_on
	cancelled_data = frappe.db.sql("""
		SELECT DATE(last_synced_on) as dt, COUNT(*) as cnt
		FROM `tabDelivery Order`
		WHERE delivery_status = 'cancelled'
		  AND DATE(last_synced_on) BETWEEN %s AND %s
		GROUP BY DATE(last_synced_on)
	""", params, as_dict=True)

	# Map to date-indexed dicts
	bookings_map = {str(r.dt): r.cnt for r in bookings_data}
	delivered_map = {str(r.dt): r.cnt for r in delivered_data}
	cancelled_map = {str(r.dt): r.cnt for r in cancelled_data}

	return {
		"labels": labels,
		"datasets": [
			{"name": "Bookings", "values": [bookings_map.get(d, 0) for d in labels]},
			{"name": "Delivered", "values": [delivered_map.get(d, 0) for d in labels]},
			{"name": "Cancelled", "values": [cancelled_map.get(d, 0) for d in labels]},
		],
	}


@frappe.whitelist()
def get_monthly_cod_trend(company=None, months=6):
	"""2.3 — Monthly COD Collection Trend (line chart)."""
	months = int(months or 6)
	end_date = get_last_day(today())
	start_date = get_first_day(add_months(today(), -(months - 1)))

	result = frappe.db.sql("""
		SELECT DATE_FORMAT(payout_date, '%%Y-%%m') as month_label,
		       IFNULL(SUM(net_amount), 0) as total
		FROM `tabCourier Payout Log`
		WHERE payout_date BETWEEN %s AND %s
		GROUP BY DATE_FORMAT(payout_date, '%%Y-%%m')
		ORDER BY month_label
	""", (str(start_date), str(end_date)), as_dict=True)

	# Build full month labels
	labels = []
	values_map = {r.month_label: flt(r.total) for r in result}
	d = start_date
	while d <= end_date:
		label = str(d)[:7]  # YYYY-MM
		if label not in labels:
			labels.append(label)
		d = add_months(d, 1)

	return {
		"labels": labels,
		"datasets": [
			{"name": "COD Collected", "values": [values_map.get(l, 0) for l in labels]},
		],
	}


@frappe.whitelist()
def get_monthly_charges_trend(company=None):
	"""2.4 — Monthly Delivery Charges Trend (bar chart)."""
	months = 6
	end_date = get_last_day(today())
	start_date = get_first_day(add_months(today(), -(months - 1)))

	result = frappe.db.sql("""
		SELECT DATE_FORMAT(payout_date, '%%Y-%%m') as month_label,
		       IFNULL(SUM(delivery_charges_deducted), 0) as total
		FROM `tabCourier Payout Log`
		WHERE payout_date BETWEEN %s AND %s
		GROUP BY DATE_FORMAT(payout_date, '%%Y-%%m')
		ORDER BY month_label
	""", (str(start_date), str(end_date)), as_dict=True)

	labels = []
	values_map = {r.month_label: flt(r.total) for r in result}
	d = start_date
	while d <= end_date:
		label = str(d)[:7]
		if label not in labels:
			labels.append(label)
		d = add_months(d, 1)

	return {
		"labels": labels,
		"datasets": [
			{"name": "Delivery Charges", "values": [values_map.get(l, 0) for l in labels]},
		],
	}


@frappe.whitelist()
def get_success_rate(company=None, from_date=None, to_date=None):
	"""2.5 — Overall Delivery Success Rate (percentage)."""
	if not from_date:
		from_date = add_days(today(), -90)
	if not to_date:
		to_date = today()

	delivered = frappe.db.count("Delivery Order", filters={
		"delivery_status": "delivered",
		"creation": ["between", [from_date, to_date]],
	})
	cancelled = frappe.db.count("Delivery Order", filters={
		"delivery_status": "cancelled",
		"creation": ["between", [from_date, to_date]],
	})

	total = delivered + cancelled
	rate = (delivered / total * 100) if total else 0
	return {"value": round(rate, 1), "fieldtype": "Percent"}


@frappe.whitelist()
def get_reconciliation_rate(company=None, from_date=None, to_date=None):
	"""2.6 — COD Reconciliation Rate (percentage)."""
	if not from_date:
		from_date = add_days(today(), -90)
	if not to_date:
		to_date = today()

	total_delivered = frappe.db.count("Delivery Order", filters={
		"delivery_status": "delivered",
		"creation": ["between", [from_date, to_date]],
	})
	reconciled = frappe.db.count("Delivery Order", filters={
		"delivery_status": "delivered",
		"payment_reconciled": 1,
		"creation": ["between", [from_date, to_date]],
	})

	rate = (reconciled / total_delivered * 100) if total_delivered else 0
	return {"value": round(rate, 1), "fieldtype": "Percent"}


# ---------------------------------------------------------------------------
# Phase 2 — Stubs (build when data volume / multi-courier justifies)
# ---------------------------------------------------------------------------

# TODO: Phase 2 — Zone/Area-wise Delivery Volume (Bar, top 10 zones)
#   Depends on `zone` field or `Delivery Zone` doctype.

# TODO: Phase 2 — Zone-wise Success Rate (Bar)
#   Same dependency as above.

# TODO: Phase 2 — Courier Provider Performance Comparison (Bar)
#   Only meaningful once a second courier provider is active.

# TODO: Phase 2 — Return/Cancellation Reason Breakdown (Donut)
#   Depends on structured reason capture on cancellation.


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------


def _get_clearing_account(company):
	"""Get the clearing account for a company from Courier Settings."""
	try:
		accounts = frappe.get_all(
			"Courier Account",
			filters={"parent": "Courier Settings", "company": company},
			fields=["clearing_account"],
			limit=1,
		)
		if accounts and accounts[0].clearing_account:
			return accounts[0].clearing_account
	except Exception:
		pass
	return None
