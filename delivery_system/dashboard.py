# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

"""
Backend methods for Delivery System Number Cards and Dashboard Charts.
All methods are whitelisted for use with Frappe Number Card (type=Custom)
and Dashboard Chart (type=Custom) records.

Fixed version with:
- Proper company filtering
- Error handling
- SQL injection prevention
- Null checks
- Cache key uniqueness
"""

import frappe
from frappe import _
from frappe.utils import today, get_first_day, get_last_day, add_months, add_days, getdate, flt, cint


# ---------------------------------------------------------------------------
# Number Card & Chart Methods
# ---------------------------------------------------------------------------


@frappe.whitelist()
def sync_dashboard_charts():
	"""Ensure standard Dashboard Chart records in database have correct configuration."""
	charts = [
		{
			"name": "Daily Delivery Trend",
			"chart_name": "Daily Delivery Trend",
			"chart_type": "Count",
			"document_type": "Delivery Order",
			"based_on": "creation",
			"time_interval": "Daily",
			"timespan": "Last Month",
			"type": "Line",
			"timeseries": 1,
			"show_values_over_chart": 1,
			"filters_json": "[]",
			"dynamic_filters_json": "[]",
		},
		{
			"name": "Monthly COD Collection Trend",
			"chart_name": "Monthly COD Collection Trend",
			"chart_type": "Sum",
			"document_type": "Courier Payout",
			"based_on": "payout_date",
			"value_based_on": "net_amount",
			"time_interval": "Monthly",
			"timespan": "Last Year",
			"type": "Line",
			"timeseries": 1,
			"show_values_over_chart": 1,
			"filters_json": "[]",
			"dynamic_filters_json": "[]",
		},
		{
			"name": "Monthly Delivery Charges Trend",
			"chart_name": "Monthly Delivery Charges Trend",
			"chart_type": "Sum",
			"document_type": "Courier Payout",
			"based_on": "payout_date",
			"value_based_on": "delivery_charges_deducted",
			"time_interval": "Monthly",
			"timespan": "Last Year",
			"type": "Bar",
			"timeseries": 1,
			"show_values_over_chart": 1,
			"filters_json": "[]",
			"dynamic_filters_json": "[]",
		},
		{
			"name": "Delivery Status Breakdown",
			"chart_name": "Delivery Status Breakdown",
			"chart_type": "Group By",
			"document_type": "Delivery Order",
			"group_by_based_on": "delivery_status",
			"group_by_type": "Count",
			"type": "Donut",
			"show_values_over_chart": 1,
			"filters_json": "[]",
			"dynamic_filters_json": "[]",
		},
	]

	for c in charts:
		name = c["name"]
		if frappe.db.exists("Dashboard Chart", name):
			# Clear invalid source link first via direct SQL
			frappe.db.sql("""
				UPDATE `tabDashboard Chart`
				SET source = '', chart_type = %s, document_type = %s,
					based_on = %s, value_based_on = %s,
					time_interval = %s, timespan = %s,
					`type` = %s, timeseries = %s,
					show_values_over_chart = %s,
					group_by_based_on = %s, group_by_type = %s,
					filters_json = %s, dynamic_filters_json = %s
				WHERE name = %s
			""", (
				c.get("chart_type", ""),
				c.get("document_type", ""),
				c.get("based_on", ""),
				c.get("value_based_on", ""),
				c.get("time_interval", ""),
				c.get("timespan", ""),
				c.get("type", ""),
				c.get("timeseries", 0),
				c.get("show_values_over_chart", 0),
				c.get("group_by_based_on", ""),
				c.get("group_by_type", "Count"),
				c.get("filters_json", "[]"),
				c.get("dynamic_filters_json", "[]"),
				name,
			))
		else:
			c["doctype"] = "Dashboard Chart"
			c["module"] = "Delivery System"
			c["is_standard"] = 1
			c["is_public"] = 1
			c["source"] = ""
			doc = frappe.get_doc(c)
			doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"success": True, "message": "Dashboard Charts synced successfully!"}



@frappe.whitelist()
def get_courier_balance_card(company=None, courier_provider=None):
	"""1.1 — Courier Current Balance (cached 15 mins).
	
	Args:
		company: Company name for multi-company setup
		courier_provider: Courier provider name (defaults to default_provider from settings)
	
	Returns:
		dict: {"value": float, "fieldtype": "Currency"}
	"""
	# Get company
	if not company:
		company = frappe.defaults.get_user_default("Company")
	
	# Get courier provider
	if not courier_provider:
		try:
			courier_provider = frappe.db.get_single_value("Courier Settings", "default_provider")
		except Exception:
			frappe.log_error(frappe.get_traceback(), "get_courier_balance_card.get_provider")
			return {"value": 0, "fieldtype": "Currency"}
	
	if not courier_provider:
		return {"value": 0, "fieldtype": "Currency"}
	
	# Get provider code
	try:
		provider_code = frappe.db.get_value("Courier Provider", courier_provider, "provider_code")
		if not provider_code:
			return {"value": 0, "fieldtype": "Currency"}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "get_courier_balance_card.get_provider_code")
		return {"value": 0, "fieldtype": "Currency"}
	
	# Create unique cache key per company and provider
	cache_key = f"courier_balance_{provider_code}_{company or 'default'}"
	cached = frappe.cache().get_value(cache_key)
	
	if cached is not None:
		return {"value": flt(cached), "fieldtype": "Currency"}

	try:
		from delivery_system.couriers import get_client
		client = get_client(provider_code, company)
		
		if not hasattr(client, 'get_balance'):
			# Provider doesn't support balance query
			return {"value": 0, "fieldtype": "Currency"}
		
		bal_data = client.get_balance()
		balance = flt(bal_data.get("current_balance") or bal_data.get("balance") or 0)
		
		# Cache for 15 minutes
		frappe.cache().set_value(cache_key, balance, expires_in_sec=900)
		return {"value": balance, "fieldtype": "Currency"}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_courier_balance_card.api_call")
		return {"value": 0, "fieldtype": "Currency"}


@frappe.whitelist()
def get_clearing_account_balance(company=None):
	"""1.2 — Total Outstanding COD (Clearing Account balance from GL).
	
	Args:
		company: Company name (required for multi-company)
	
	Returns:
		dict: {"value": float, "fieldtype": "Currency"}
	"""
	if not company:
		company = frappe.defaults.get_user_default("Company")
	
	if not company:
		frappe.log_error("No company specified or defaulted", "get_clearing_account_balance")
		return {"value": 0, "fieldtype": "Currency"}

	# Find the clearing account for this company
	clearing_account = _get_clearing_account(company)
	
	if not clearing_account:
		# Log warning but don't fail
		frappe.log_error(
			f"No clearing account configured for company: {company}",
			"get_clearing_account_balance.no_account"
		)
		return {"value": 0, "fieldtype": "Currency"}

	try:
		# Sum GL entries: debit - credit = outstanding balance in clearing account
		result = frappe.db.sql("""
			SELECT IFNULL(SUM(debit - credit), 0) as balance
			FROM `tabGL Entry`
			WHERE account = %s AND company = %s AND is_cancelled = 0
		""", (clearing_account, company), as_dict=True)

		balance = flt(result[0].balance) if result and len(result) > 0 else 0
		return {"value": balance, "fieldtype": "Currency"}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_clearing_account_balance.query_error")
		return {"value": 0, "fieldtype": "Currency"}


@frappe.whitelist()
def get_stuck_deliveries_count(company=None):
	"""1.6 — Stuck Deliveries (3+ days pending).
	
	Args:
		company: Company name (optional, filters by company if provided)
	
	Returns:
		dict: {"value": int, "fieldtype": "Int"}
	"""
	# Get min_days setting
	min_days = 3
	try:
		min_days = cint(frappe.db.get_single_value("Courier Settings", "min_days_pending") or 3)
	except Exception:
		pass  # Use default

	# Build filters
	filters = {
		"delivery_status": ["in", ["pending", "in_review"]],
		"creation": ["<=", add_days(today(), -min_days)],
		"docstatus": ["<", 2],
	}
	
	# Add company filter if specified
	if company:
		# Get delivery orders linked to this company via reference doctype
		try:
			# Get all delivery orders
			all_orders = frappe.get_all(
				"Delivery Order",
				filters=filters,
				fields=["name", "reference_doctype", "reference_name"]
			)
			
			# Filter by company
			company_orders = []
			for order in all_orders:
				if order.reference_doctype and order.reference_name:
					try:
						order_company = frappe.db.get_value(
							order.reference_doctype,
							order.reference_name,
							"company"
						)
						if order_company == company:
							company_orders.append(order.name)
					except Exception:
						continue  # Skip if reference doesn't have company field
			
			return {"value": len(company_orders), "fieldtype": "Int"}
			
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), "get_stuck_deliveries_count.company_filter")
			return {"value": 0, "fieldtype": "Int"}
	
	# No company filter - get all
	try:
		count = frappe.db.count("Delivery Order", filters=filters)
		return {"value": count, "fieldtype": "Int"}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_stuck_deliveries_count.query_error")
		return {"value": 0, "fieldtype": "Int"}


@frappe.whitelist()
def get_monthly_cod_collected(company=None):
	"""1.8 — This Month's COD Collected (sum net_amount from Courier Payout).
	
	Args:
		company: Company name (optional filter)
	
	Returns:
		dict: {"value": float, "fieldtype": "Currency"}
	"""
	first_day = get_first_day(today())
	last_day = get_last_day(today())

	try:
		if company:
			# Filter by company - need to join with delivery orders
			result = frappe.db.sql("""
				SELECT IFNULL(SUM(DISTINCT cp.net_amount), 0) as total
				FROM `tabCourier Payout` cp
				INNER JOIN `tabCourier Payout Item` cpi ON cpi.parent = cp.name
				INNER JOIN `tabDelivery Order` do ON do.name = cpi.delivery_order
				WHERE cp.payout_date BETWEEN %s AND %s
				  AND do.reference_doctype IN ('Sales Order', 'Delivery Note')
				  AND EXISTS (
					SELECT 1 FROM `tabSales Order` so 
					WHERE so.name = do.reference_name 
					  AND so.company = %s
					  AND do.reference_doctype = 'Sales Order'
					UNION
					SELECT 1 FROM `tabDelivery Note` dn
					WHERE dn.name = do.reference_name
					  AND dn.company = %s
					  AND do.reference_doctype = 'Delivery Note'
				  )
			""", (first_day, last_day, company, company), as_dict=True)
		else:
			# No company filter
			result = frappe.db.sql("""
				SELECT IFNULL(SUM(net_amount), 0) as total
				FROM `tabCourier Payout`
				WHERE payout_date BETWEEN %s AND %s
			""", (first_day, last_day), as_dict=True)

		total = flt(result[0].total) if result and len(result) > 0 else 0
		return {"value": total, "fieldtype": "Currency"}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_monthly_cod_collected.query_error")
		return {"value": 0, "fieldtype": "Currency"}


@frappe.whitelist()
def get_monthly_delivery_charges(company=None):
	"""1.9 — This Month's Delivery Charges (sum delivery_charges_deducted).
	
	Args:
		company: Company name (optional filter)
	
	Returns:
		dict: {"value": float, "fieldtype": "Currency"}
	"""
	first_day = get_first_day(today())
	last_day = get_last_day(today())

	try:
		if company:
			# Filter by company via delivery orders
			result = frappe.db.sql("""
				SELECT IFNULL(SUM(DISTINCT cp.delivery_charges_deducted), 0) as total
				FROM `tabCourier Payout` cp
				INNER JOIN `tabCourier Payout Item` cpi ON cpi.parent = cp.name
				INNER JOIN `tabDelivery Order` do ON do.name = cpi.delivery_order
				WHERE cp.payout_date BETWEEN %s AND %s
				  AND do.reference_doctype IN ('Sales Order', 'Delivery Note')
				  AND EXISTS (
					SELECT 1 FROM `tabSales Order` so 
					WHERE so.name = do.reference_name 
					  AND so.company = %s
					  AND do.reference_doctype = 'Sales Order'
					UNION
					SELECT 1 FROM `tabDelivery Note` dn
					WHERE dn.name = do.reference_name
					  AND dn.company = %s
					  AND do.reference_doctype = 'Delivery Note'
				  )
			""", (first_day, last_day, company, company), as_dict=True)
		else:
			result = frappe.db.sql("""
				SELECT IFNULL(SUM(delivery_charges_deducted), 0) as total
				FROM `tabCourier Payout`
				WHERE payout_date BETWEEN %s AND %s
			""", (first_day, last_day), as_dict=True)

		total = flt(result[0].total) if result and len(result) > 0 else 0
		return {"value": total, "fieldtype": "Currency"}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_monthly_delivery_charges.query_error")
		return {"value": 0, "fieldtype": "Currency"}


# ---------------------------------------------------------------------------
# Dashboard Chart Methods
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_daily_delivery_trend(company=None, courier_provider=None):
	"""2.2 — Daily Bookings vs Delivered vs Cancelled (last 30 days).
	
	Args:
		company: Company name (optional filter)
		courier_provider: Courier provider name (optional filter)
	
	Returns:
		dict: Chart data with labels and datasets
	"""
	end_date = getdate(today())
	start_date = add_days(end_date, -29)

	# Build date range labels
	labels = []
	d = start_date
	while d <= end_date:
		labels.append(str(d))
		d = add_days(d, 1)

	# Build company filter
	company_condition = ""
	params_bookings = [str(start_date), str(end_date)]
	params_delivered = [str(start_date), str(end_date)]
	params_cancelled = [str(start_date), str(end_date)]
	
	if company:
		company_condition = """
			AND EXISTS (
				SELECT 1 FROM `tabSales Order` so 
				WHERE so.name = do.reference_name 
				  AND so.company = %s
				  AND do.reference_doctype = 'Sales Order'
				UNION
				SELECT 1 FROM `tabDelivery Note` dn
				WHERE dn.name = do.reference_name
				  AND dn.company = %s
				  AND do.reference_doctype = 'Delivery Note'
			)
		"""
		params_bookings.extend([company, company])
		params_delivered.extend([company, company])
		params_cancelled.extend([company, company])

	try:
		# Bookings by creation date
		bookings_data = frappe.db.sql(f"""
			SELECT DATE(do.creation) as dt, COUNT(*) as cnt
			FROM `tabDelivery Order` do
			WHERE DATE(do.creation) BETWEEN %s AND %s
			  {company_condition}
			GROUP BY DATE(do.creation)
		""", tuple(params_bookings), as_dict=True)

		# Delivered by last_synced_on (with NULL check)
		delivered_data = frappe.db.sql(f"""
			SELECT DATE(do.last_synced_on) as dt, COUNT(*) as cnt
			FROM `tabDelivery Order` do
			WHERE do.delivery_status = 'delivered'
			  AND do.last_synced_on IS NOT NULL
			  AND DATE(do.last_synced_on) BETWEEN %s AND %s
			  {company_condition}
			GROUP BY DATE(do.last_synced_on)
		""", tuple(params_delivered), as_dict=True)

		# Cancelled by last_synced_on (with NULL check)
		cancelled_data = frappe.db.sql(f"""
			SELECT DATE(do.last_synced_on) as dt, COUNT(*) as cnt
			FROM `tabDelivery Order` do
			WHERE do.delivery_status = 'cancelled'
			  AND do.last_synced_on IS NOT NULL
			  AND DATE(do.last_synced_on) BETWEEN %s AND %s
			  {company_condition}
			GROUP BY DATE(do.last_synced_on)
		""", tuple(params_cancelled), as_dict=True)

		# Map to date-indexed dicts
		bookings_map = {str(r.dt): r.cnt for r in bookings_data if r.dt}
		delivered_map = {str(r.dt): r.cnt for r in delivered_data if r.dt}
		cancelled_map = {str(r.dt): r.cnt for r in cancelled_data if r.dt}

		return {
			"labels": labels,
			"datasets": [
				{"name": "Bookings", "values": [bookings_map.get(d, 0) for d in labels]},
				{"name": "Delivered", "values": [delivered_map.get(d, 0) for d in labels]},
				{"name": "Cancelled", "values": [cancelled_map.get(d, 0) for d in labels]},
			],
		}
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_daily_delivery_trend.query_error")
		return {
			"labels": labels,
			"datasets": [
				{"name": "Bookings", "values": [0] * len(labels)},
				{"name": "Delivered", "values": [0] * len(labels)},
				{"name": "Cancelled", "values": [0] * len(labels)},
			],
		}


@frappe.whitelist()
def get_monthly_cod_trend(company=None, months=6):
	"""2.3 — Monthly COD Collection Trend (line chart).
	
	Args:
		company: Company name (optional filter)
		months: Number of months to show (default 6, max 24)
	
	Returns:
		dict: Chart data with labels and datasets
	"""
	# Validate months parameter
	try:
		months = cint(months or 6)
		if months < 1:
			months = 6
		if months > 24:
			months = 24
	except Exception:
		months = 6
	
	end_date = get_last_day(today())
	start_date = get_first_day(add_months(today(), -(months - 1)))

	try:
		if company:
			# With company filter
			result = frappe.db.sql("""
				SELECT DATE_FORMAT(cp.payout_date, '%%Y-%%m') as month_label,
				       IFNULL(SUM(DISTINCT cp.net_amount), 0) as total
				FROM `tabCourier Payout` cp
				INNER JOIN `tabCourier Payout Item` cpi ON cpi.parent = cp.name
				INNER JOIN `tabDelivery Order` do ON do.name = cpi.delivery_order
				WHERE cp.payout_date BETWEEN %s AND %s
				  AND do.reference_doctype IN ('Sales Order', 'Delivery Note')
				  AND EXISTS (
					SELECT 1 FROM `tabSales Order` so 
					WHERE so.name = do.reference_name 
					  AND so.company = %s
					  AND do.reference_doctype = 'Sales Order'
					UNION
					SELECT 1 FROM `tabDelivery Note` dn
					WHERE dn.name = do.reference_name
					  AND dn.company = %s
					  AND do.reference_doctype = 'Delivery Note'
				  )
				GROUP BY DATE_FORMAT(cp.payout_date, '%%Y-%%m')
				ORDER BY month_label
			""", (str(start_date), str(end_date), company, company), as_dict=True)
		else:
			# No company filter
			result = frappe.db.sql("""
				SELECT DATE_FORMAT(payout_date, '%%Y-%%m') as month_label,
				       IFNULL(SUM(net_amount), 0) as total
				FROM `tabCourier Payout`
				WHERE payout_date BETWEEN %s AND %s
				GROUP BY DATE_FORMAT(payout_date, '%%Y-%%m')
				ORDER BY month_label
			""", (str(start_date), str(end_date)), as_dict=True)

		# Build full month labels
		labels = []
		values_map = {r.month_label: flt(r.total) for r in result if r.month_label}
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
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_monthly_cod_trend.query_error")
		return {
			"labels": [],
			"datasets": [{"name": "COD Collected", "values": []}],
		}


@frappe.whitelist()
def get_monthly_charges_trend(company=None, months=6):
	"""2.4 — Monthly Delivery Charges Trend (bar chart).
	
	Args:
		company: Company name (optional filter)
		months: Number of months to show (default 6, max 24)
	
	Returns:
		dict: Chart data with labels and datasets
	"""
	# Validate months parameter
	try:
		months = cint(months or 6)
		if months < 1:
			months = 6
		if months > 24:
			months = 24
	except Exception:
		months = 6
		
	end_date = get_last_day(today())
	start_date = get_first_day(add_months(today(), -(months - 1)))

	try:
		if company:
			# With company filter
			result = frappe.db.sql("""
				SELECT DATE_FORMAT(cp.payout_date, '%%Y-%%m') as month_label,
				       IFNULL(SUM(DISTINCT cp.delivery_charges_deducted), 0) as total
				FROM `tabCourier Payout` cp
				INNER JOIN `tabCourier Payout Item` cpi ON cpi.parent = cp.name
				INNER JOIN `tabDelivery Order` do ON do.name = cpi.delivery_order
				WHERE cp.payout_date BETWEEN %s AND %s
				  AND do.reference_doctype IN ('Sales Order', 'Delivery Note')
				  AND EXISTS (
					SELECT 1 FROM `tabSales Order` so 
					WHERE so.name = do.reference_name 
					  AND so.company = %s
					  AND do.reference_doctype = 'Sales Order'
					UNION
					SELECT 1 FROM `tabDelivery Note` dn
					WHERE dn.name = do.reference_name
					  AND dn.company = %s
					  AND do.reference_doctype = 'Delivery Note'
				  )
				GROUP BY DATE_FORMAT(cp.payout_date, '%%Y-%%m')
				ORDER BY month_label
			""", (str(start_date), str(end_date), company, company), as_dict=True)
		else:
			# No company filter
			result = frappe.db.sql("""
				SELECT DATE_FORMAT(payout_date, '%%Y-%%m') as month_label,
				       IFNULL(SUM(delivery_charges_deducted), 0) as total
				FROM `tabCourier Payout`
				WHERE payout_date BETWEEN %s AND %s
				GROUP BY DATE_FORMAT(payout_date, '%%Y-%%m')
				ORDER BY month_label
			""", (str(start_date), str(end_date)), as_dict=True)

		# Build full month labels
		labels = []
		values_map = {r.month_label: flt(r.total) for r in result if r.month_label}
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
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_monthly_charges_trend.query_error")
		return {
			"labels": [],
			"datasets": [{"name": "Delivery Charges", "values": []}],
		}


@frappe.whitelist()
def get_success_rate(company=None, from_date=None, to_date=None):
	"""2.5 — Overall Delivery Success Rate (percentage).
	
	Args:
		company: Company name (optional filter)
		from_date: Start date (default: 90 days ago)
		to_date: End date (default: today)
	
	Returns:
		dict: {"value": float, "fieldtype": "Percent"}
	"""
	# Validate and set default dates
	try:
		if not from_date:
			from_date = add_days(today(), -90)
		if not to_date:
			to_date = today()
		
		# Ensure dates are in correct format
		from_date = getdate(from_date)
		to_date = getdate(to_date)
	except Exception:
		from_date = add_days(today(), -90)
		to_date = today()

	# Build filters
	base_filters = {
		"creation": ["between", [from_date, to_date]],
		"docstatus": 1
	}

	try:
		if company:
			# With company filter - need to check via reference
			all_orders = frappe.get_all(
				"Delivery Order",
				filters=base_filters,
				fields=["name", "delivery_status", "reference_doctype", "reference_name"]
			)
			
			delivered = 0
			cancelled = 0
			
			for order in all_orders:
				if order.reference_doctype and order.reference_name:
					try:
						order_company = frappe.db.get_value(
							order.reference_doctype,
							order.reference_name,
							"company"
						)
						if order_company == company:
							if order.delivery_status == "delivered":
								delivered += 1
							elif order.delivery_status == "cancelled":
								cancelled += 1
					except Exception:
						continue
		else:
			# No company filter
			delivered_filters = {**base_filters, "delivery_status": "delivered"}
			cancelled_filters = {**base_filters, "delivery_status": "cancelled"}
			
			delivered = frappe.db.count("Delivery Order", filters=delivered_filters)
			cancelled = frappe.db.count("Delivery Order", filters=cancelled_filters)

		total = delivered + cancelled
		rate = (delivered / total * 100) if total > 0 else 0
		return {"value": round(rate, 1), "fieldtype": "Percent"}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_success_rate.query_error")
		return {"value": 0, "fieldtype": "Percent"}


@frappe.whitelist()
def get_reconciliation_rate(company=None, from_date=None, to_date=None):
	"""2.6 — COD Reconciliation Rate (percentage).
	
	Args:
		company: Company name (optional filter)
		from_date: Start date (default: 90 days ago)
		to_date: End date (default: today)
	
	Returns:
		dict: {"value": float, "fieldtype": "Percent"}
	"""
	# Validate and set default dates
	try:
		if not from_date:
			from_date = add_days(today(), -90)
		if not to_date:
			to_date = today()
		
		from_date = getdate(from_date)
		to_date = getdate(to_date)
	except Exception:
		from_date = add_days(today(), -90)
		to_date = today()

	# Build filters
	base_filters = {
		"delivery_status": "delivered",
		"creation": ["between", [from_date, to_date]],
		"docstatus": 1
	}

	try:
		if company:
			# With company filter
			all_delivered = frappe.get_all(
				"Delivery Order",
				filters=base_filters,
				fields=["name", "payment_reconciled", "reference_doctype", "reference_name"]
			)
			
			total_delivered = 0
			reconciled = 0
			
			for order in all_delivered:
				if order.reference_doctype and order.reference_name:
					try:
						order_company = frappe.db.get_value(
							order.reference_doctype,
							order.reference_name,
							"company"
						)
						if order_company == company:
							total_delivered += 1
							if order.payment_reconciled:
								reconciled += 1
					except Exception:
						continue
		else:
			# No company filter
			total_delivered = frappe.db.count("Delivery Order", filters=base_filters)
			
			reconciled_filters = {**base_filters, "payment_reconciled": 1}
			reconciled = frappe.db.count("Delivery Order", filters=reconciled_filters)

		rate = (reconciled / total_delivered * 100) if total_delivered > 0 else 0
		return {"value": round(rate, 1), "fieldtype": "Percent"}
		
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "get_reconciliation_rate.query_error")
		return {"value": 0, "fieldtype": "Percent"}


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
	"""Get the clearing account for a company from Courier Settings.
	
	Args:
		company: Company name
	
	Returns:
		str: Account name or None
	"""
	if not company:
		return None
		
	try:
		accounts = frappe.get_all(
			"Courier Account",
			filters={"parent": "Courier Settings", "company": company},
			fields=["clearing_account"],
			limit=1,
		)
		if accounts and len(accounts) > 0 and accounts[0].clearing_account:
			return accounts[0].clearing_account
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"_get_clearing_account.{company}")
	
	return None
