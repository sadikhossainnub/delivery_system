# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

"""
Demo data generator for Delivery System app.
Creates realistic Customers, Sales Orders, Delivery Orders, Courier Payout Logs,
and GL accounts to populate ERPNext Desk, Reports, Number Cards, and Dashboard Charts.
"""

import random
import frappe
from frappe import _
from frappe.utils import today, add_days, flt, now_datetime


@frappe.whitelist()
def generate_demo_data(reset_existing=False):
	"""Generate a full set of realistic demo data for the Delivery System app."""
	company = _ensure_company()

	if reset_existing:
		_cleanup_existing_demo_data()

	try:
		# 1. Setup Providers & Settings
		_setup_providers_and_settings(company)

		# 2. Setup Default Accounts
		clearing_acc, charge_acc, variance_acc, mode_of_payment = _ensure_accounts(company)

		# 3. Create Demo Customers
		customers = _create_demo_customers()

		# 4. Create Demo Items if none exist
		item_code = _ensure_demo_item(company)

		# 5. Create Demo Sales Orders & Delivery Orders
		delivery_orders = _create_demo_orders(company, customers, item_code)

		# 6. Create Demo Courier Payout Logs
		_create_demo_payout_logs(company, delivery_orders)

		frappe.db.commit()
		return {
			"success": True,
			"message": f"Demo data successfully generated for company {company}!",
			"delivery_orders_count": len(delivery_orders),
		}

	except Exception as exc:
		frappe.db.rollback()
		frappe.log_error(frappe.get_traceback(), "generate_demo_data")
		frappe.throw(f"Failed to generate demo data: {exc}")


def _setup_providers_and_settings(company):
	"""Ensure Courier Providers and Courier Settings exist."""
	providers = [
		{"provider_code": "steadfast", "courier_name": "Steadfast", "enabled": 1, "base_url": "https://portal.packzy.com/api/v1"},
		{"provider_code": "pathao", "courier_name": "Pathao", "enabled": 1, "base_url": "https://api.pathao.com"},
		{"provider_code": "redx", "courier_name": "RedX", "enabled": 1, "base_url": "https://openapi.redx.com.bd"},
	]

	for p in providers:
		if not frappe.db.exists("Courier Provider", p["courier_name"]):
			doc = frappe.get_doc({
				"doctype": "Courier Provider",
				"name": p["courier_name"],
				"courier_name": p["courier_name"],
				"provider_code": p["provider_code"],
				"enabled": p["enabled"],
				"base_url": p["base_url"],
			})
			doc.insert(ignore_permissions=True)

	# Courier Settings
	settings = frappe.get_single("Courier Settings")
	settings.default_provider = "Steadfast"
	settings.booking_doctype = "Both"
	settings.auto_sync_status = 1
	settings.enable_accounting_automation = 1
	settings.variance_threshold_auto_post = 50.0
	settings.save(ignore_permissions=True)


def _ensure_accounts(company):
	"""Ensure default GL accounts and Mode of Payment exist for the company."""
	parent_asset = frappe.db.get_value("Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name") \
		or frappe.db.get_value("Account", {"company": company, "root_type": "Asset", "is_group": 0}, "name")
	
	parent_expense = frappe.db.get_value("Account", {"company": company, "root_type": "Expense", "is_group": 0}, "name")

	# Clearing Account
	clearing_acc_name = f"Steadfast Clearing Account - {company}"
	if not frappe.db.exists("Account", clearing_acc_name):
		c_acc = frappe.get_doc({
			"doctype": "Account",
			"account_name": "Steadfast Clearing Account",
			"company": company,
			"root_type": "Asset",
			"account_type": "Bank",
			"is_group": 0,
		})
		try:
			c_acc.insert(ignore_permissions=True)
			clearing_acc_name = c_acc.name
		except Exception:
			clearing_acc_name = parent_asset

	# Delivery Charge Account
	charge_acc_name = f"Delivery Charges - {company}"
	if not frappe.db.exists("Account", charge_acc_name):
		ch_acc = frappe.get_doc({
			"doctype": "Account",
			"account_name": "Delivery Charges",
			"company": company,
			"root_type": "Expense",
			"account_type": "Expense",
			"is_group": 0,
		})
		try:
			ch_acc.insert(ignore_permissions=True)
			charge_acc_name = ch_acc.name
		except Exception:
			charge_acc_name = parent_expense

	# Variance Account
	variance_acc_name = f"Courier Variance - {company}"
	if not frappe.db.exists("Account", variance_acc_name):
		v_acc = frappe.get_doc({
			"doctype": "Account",
			"account_name": "Courier Variance",
			"company": company,
			"root_type": "Expense",
			"account_type": "Expense",
			"is_group": 0,
		})
		try:
			v_acc.insert(ignore_permissions=True)
			variance_acc_name = v_acc.name
		except Exception:
			variance_acc_name = parent_expense

	# Mode of Payment
	mop_name = "Steadfast COD"
	if not frappe.db.exists("Mode of Payment", mop_name):
		mop = frappe.get_doc({
			"doctype": "Mode of Payment",
			"mode_of_payment": mop_name,
			"type": "Bank",
			"accounts": [{"company": company, "default_account": clearing_acc_name}],
		})
		try:
			mop.insert(ignore_permissions=True)
		except Exception:
			pass

	# Update Courier Settings child table
	settings = frappe.get_single("Courier Settings")
	existing_account = False
	for row in settings.courier_accounts:
		if row.company == company and row.courier_provider == "Steadfast":
			row.clearing_account = clearing_acc_name
			row.delivery_charge_account = charge_acc_name
			row.variance_account = variance_acc_name
			row.default_mode_of_payment = mop_name
			existing_account = True
			break

	if not existing_account:
		settings.append("courier_accounts", {
			"company": company,
			"courier_provider": "Steadfast",
			"api_key": "demo_steadfast_key_99",
			"secret_key": "demo_secret_pass_123",
			"clearing_account": clearing_acc_name,
			"delivery_charge_account": charge_acc_name,
			"variance_account": variance_acc_name,
			"default_mode_of_payment": mop_name,
		})

	settings.save(ignore_permissions=True)
	return clearing_acc_name, charge_acc_name, variance_acc_name, mop_name


def _create_demo_customers():
	"""Create realistic Bangladeshi customers."""
	cg = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	if not cg:
		cg_doc = frappe.get_doc({"doctype": "Customer Group", "customer_group_name": "Individual", "is_group": 0})
		try:
			cg_doc.insert(ignore_permissions=True)
			cg = cg_doc.name
		except Exception:
			cg = "Commercial"

	terr = frappe.db.get_value("Territory", {"is_group": 0}, "name")
	if not terr:
		terr_doc = frappe.get_doc({"doctype": "Territory", "territory_name": "Bangladesh", "is_group": 0})
		try:
			terr_doc.insert(ignore_permissions=True)
			terr = terr_doc.name
		except Exception:
			terr = "All Territories"

	customer_data = [
		{"customer_name": "Jamal Uddin", "mobile_no": "01712345678", "city": "Dhaka", "address": "House 12, Road 5, Dhanmondi, Dhaka"},
		{"customer_name": "Nusrat Jahan", "mobile_no": "01898765432", "city": "Chittagong", "address": "GEC Circle, Nasirabad, Chittagong"},
		{"customer_name": "Rahim Afroz", "mobile_no": "01555123456", "city": "Sylhet", "address": "Zindabazar, Ward 14, Sylhet"},
		{"customer_name": "Tanvir Ahmed", "mobile_no": "01911223344", "city": "Rajshahi", "address": "Saheb Bazar, Boalia, Rajshahi"},
		{"customer_name": "Shayla Akter", "mobile_no": "01677889900", "city": "Khulna", "address": "KDA Avenue, Sonadanga, Khulna"},
		{"customer_name": "Mahbubur Rahman", "mobile_no": "01300112233", "city": "Gazipur", "address": "Chowrastra, Board Bazar, Gazipur"},
	]

	created_customers = []
	for c in customer_data:
		if not frappe.db.exists("Customer", c["customer_name"]):
			cust = frappe.get_doc({
				"doctype": "Customer",
				"customer_name": c["customer_name"],
				"customer_type": "Individual",
				"customer_group": cg,
				"territory": terr,
				"mobile_no": c["mobile_no"],
			})
			cust.insert(ignore_permissions=True)
			created_customers.append(cust.name)
		else:
			created_customers.append(c["customer_name"])

	return created_customers


def _ensure_demo_item(company):
	"""Ensure at least one Item exists for Sales Order creation."""
	existing = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
	if existing:
		return existing

	item = frappe.get_doc({
		"doctype": "Item",
		"item_code": "DEMO-PARCEL-ITEM",
		"item_name": "Courier Demo Goods",
		"item_group": "All Item Groups",
		"is_stock_item": 0,
		"standard_rate": 1200.0,
	})
	item.insert(ignore_permissions=True)
	return item.name


def _create_demo_orders(company, customers, item_code):
	"""Create demo Sales Orders and corresponding Delivery Orders."""
	statuses_distribution = [
		("delivered", 12),
		("pending", 4),
		("in_review", 3),
		("cancelled", 4),
		("hold", 2),
	]

	order_index = 1001
	delivery_orders = []

	for status, count in statuses_distribution:
		for i in range(count):
			customer_name = random.choice(customers)
			mobile_no = frappe.db.get_value("Customer", customer_name, "mobile_no") or "01700000000"
			days_ago = random.randint(1, 28)
			creation_date = add_days(today(), -days_ago)
			cod_amount = round(random.uniform(500, 4500), 2)

			# Create Sales Order
			so = frappe.get_doc({
				"doctype": "Sales Order",
				"company": company,
				"customer": customer_name,
				"order_type": "Sales",
				"transaction_date": creation_date,
				"delivery_date": add_days(creation_date, 3),
				"items": [{
					"item_code": item_code,
					"qty": 1,
					"rate": cod_amount,
				}],
			})
			so.flags.ignore_mandatory = True
			so.flags.ignore_validate = True
			try:
				so.insert(ignore_permissions=True)
				try:
					so.submit()
				except Exception:
					pass
				ref_name = so.name
			except Exception:
				# Direct DB insert for demo Sales Order if missing stock/warehouse fields
				so_name = f"SO-DEMO-{order_index}"
				frappe.db.sql("""
					INSERT INTO `tabSales Order` (name, company, customer, docstatus, transaction_date, delivery_date, grand_total, creation, modified, owner, modified_by)
					VALUES (%s, %s, %s, 1, %s, %s, %s, NOW(), NOW(), 'Administrator', 'Administrator')
					ON DUPLICATE KEY UPDATE name=name
				""", (so_name, company, customer_name, creation_date, add_days(creation_date, 3), cod_amount))
				ref_name = so_name

			# Reconciled status for delivered orders
			reconciled = 1 if status == "delivered" and i < 8 else 0
			reconciled_id = f"PAY-ST-{2000 + i}" if reconciled else None

			# Create Delivery Order
			do_doc = frappe.get_doc({
				"doctype": "Delivery Order",
				"reference_doctype": "Sales Order",
				"reference_name": ref_name,
				"courier_provider": "Steadfast",
				"invoice_reference": f"INV-{order_index}",
				"delivery_status": status,
				"recipient_name": customer_name,
				"recipient_phone": mobile_no,
				"recipient_address": f"Demo Address {order_index}, Dhaka, Bangladesh",
				"delivery_type": "Home Delivery",
				"cod_amount": cod_amount,
				"consignment_id": f"ST-{800000 + order_index}",
				"tracking_code": f"TRK-{900000 + order_index}",
				"last_synced_on": now_datetime(),
				"payment_reconciled": reconciled,
				"reconciled_payment_id": reconciled_id,
				"creation": creation_date,
			})

			do_doc.insert(ignore_permissions=True)
			do_doc.submit()
			delivery_orders.append(do_doc)

			order_index += 1

	return delivery_orders


def _create_demo_payout_logs(company, delivery_orders):
	"""Create demo Courier Payout Log records."""
	delivered_orders = [d for d in delivery_orders if d.delivery_status == "delivered" and d.payment_reconciled]
	if not delivered_orders:
		return

	# Payout Log 1 (Current Month)
	log1_orders = delivered_orders[:4]
	gross1 = sum(d.cod_amount for d in log1_orders)
	charges1 = len(log1_orders) * 120.0
	net1 = gross1 - charges1

	payout1 = frappe.get_doc({
		"doctype": "Courier Payout Log",
		"courier_provider": "Steadfast",
		"payment_id": "CPL-PAYOUT-001",
		"payout_date": today(),
		"reconciliation_status": "Complete",
		"gross_amount": gross1,
		"delivery_charges_deducted": charges1,
		"net_amount": net1,
		"items": [
			{
				"delivery_order": d.name,
				"consignment_id": d.consignment_id,
				"cod_amount": d.cod_amount,
				"delivery_charge": 120.0,
				"net_payout": d.cod_amount - 120.0,
				"status": "Reconciled",
			}
			for d in log1_orders
		],
	})
	try:
		payout1.insert(ignore_permissions=True)
	except Exception:
		pass


def _cleanup_existing_demo_data():
	"""Optional cleanup of previous demo records."""
	frappe.db.sql("DELETE FROM `tabDelivery Order` WHERE invoice_reference LIKE 'INV-10%'")
	frappe.db.sql("DELETE FROM `tabCourier Payout Log` WHERE payment_id LIKE 'CPL-PAYOUT-%'")


def _ensure_company() -> str:
	"""Get or create a demo company."""
	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	if company and frappe.db.exists("Company", company):
		return company

	companies = frappe.get_all("Company", fields=["name"])
	if companies:
		comp_name = companies[0].name
		frappe.defaults.set_user_default("Company", comp_name)
		return comp_name

	# Create demo company with chart of accounts
	comp = frappe.get_doc({
		"doctype": "Company",
		"company_name": "Paperware BD",
		"abbr": "PBD",
		"default_currency": "BDT",
		"country": "Bangladesh",
		"create_chart_of_accounts": 1,
		"chart_of_accounts": "Standard",
	})
	comp.flags.ignore_validate = True
	comp.flags.ignore_mandatory = True
	try:
		comp.insert(ignore_permissions=True)
	except Exception:
		# Direct DB fallback if chart wizard hits missing template exception
		frappe.db.sql("""
			INSERT INTO `tabCompany` (name, company_name, abbr, default_currency, country, creation, modified, owner, modified_by)
			VALUES ('Paperware BD', 'Paperware BD', 'PBD', 'BDT', 'Bangladesh', NOW(), NOW(), 'Administrator', 'Administrator')
			ON DUPLICATE KEY UPDATE name=name
		""")

	frappe.defaults.set_user_default("Company", "Paperware BD")
	frappe.db.set_single_value("Global Defaults", "default_company", "Paperware BD")
	return "Paperware BD"

