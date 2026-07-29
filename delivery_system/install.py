# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

"""
Installation and post-migration hooks for the Delivery System app.

Automatically creates Chart of Accounts entries (Clearing Account, Delivery
Charges, Courier Variance), Mode of Payment (Steadfast COD), and wires them
into Courier Settings for every installed ERPNext company.

Called on:
  - bench install-app delivery_system   → after_install
  - bench migrate                       → after_migrate / after_sync_fixtures
"""

import frappe
from frappe import _


def after_install():
	"""Run full accounting setup and custom fields creation after app installation."""
	frappe.logger("delivery_system").info("Delivery System: running after_install setup …")
	_create_courier_custom_fields()
	_setup_all_companies()
	_sync_existing_reference_links()
	frappe.db.commit()
	frappe.logger("delivery_system").info("Delivery System: after_install complete.")


def after_migrate():
	"""Re-run accounting setup and custom fields creation on every migrate (idempotent)."""
	_create_courier_custom_fields()
	_setup_all_companies()
	_sync_existing_reference_links()
	frappe.db.commit()


def _create_courier_custom_fields():
	"""Create courier custom fields on Sales Order and Delivery Note DocTypes."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	courier_fields = [
		{
			"fieldname": "delivery_system_section",
			"fieldtype": "Section Break",
			"label": "Courier",
			"insert_after": "customer",
			"collapsible": 1,
		},
		{
			"fieldname": "customer_mobile_no",
			"fieldtype": "Data",
			"label": "Customer Mobile No",
			"insert_after": "delivery_system_section",
			"fetch_from": "customer.mobile_no",
		},
		{
			"fieldname": "delivery_order_ref",
			"fieldtype": "Link",
			"label": "Delivery Order",
			"options": "Delivery Order",
			"insert_after": "customer_mobile_no",
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
		},
		{
			"fieldname": "courier_status",
			"fieldtype": "Data",
			"label": "Courier Status",
			"insert_after": "delivery_order_ref",
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
			"in_list_view": 1,
		},
	]

	custom_fields = {
		"Sales Order": courier_fields,
		"Delivery Note": courier_fields,
	}

	create_custom_fields(custom_fields, ignore_validate=True)


def _setup_all_companies():
	"""Iterate over all ERPNext companies and ensure accounting objects exist."""
	companies = frappe.get_all("Company", fields=["name", "abbr", "default_currency"])
	for company in companies:
		try:
			_setup_company_accounts(company.name)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Delivery System install: setup failed for company {company.name}",
			)


def _setup_company_accounts(company: str):
	"""
	For one company:
	1. Create GL accounts (Clearing, Delivery Charges, Courier Variance)
	2. Create Mode of Payment 'Steadfast COD'
	3. Wire everything into Courier Settings → courier_accounts child table
	"""
	abbr = frappe.get_cached_value("Company", company, "abbr") or ""

	# ── 1. Chart of Accounts ─────────────────────────────────────────────────

	clearing_acc = _ensure_account(
		company=company,
		account_name="Steadfast Clearing Account",
		abbr=abbr,
		root_type="Asset",
		account_type="Current Asset",
		parent_root_type="Asset",
		parent_account_type="Current Asset",
	)

	delivery_charge_acc = _ensure_account(
		company=company,
		account_name="Delivery Charges",
		abbr=abbr,
		root_type="Expense",
		account_type="Expense Account",
		parent_root_type="Expense",
	)

	variance_acc = _ensure_account(
		company=company,
		account_name="Courier Variance",
		abbr=abbr,
		root_type="Expense",
		account_type="Expense Account",
		parent_root_type="Expense",
	)

	# ── 2. Mode of Payment ───────────────────────────────────────────────────

	mop_name = "Steadfast COD"
	if not frappe.db.exists("Mode of Payment", mop_name):
		try:
			mop = frappe.get_doc({
				"doctype": "Mode of Payment",
				"mode_of_payment": mop_name,
				"type": "General",
			})
			mop.insert(ignore_permissions=True)
		except frappe.DuplicateEntryError:
			pass  # race condition on multi-site, safe to ignore
		except Exception:
			frappe.log_error(frappe.get_traceback(), "Delivery System: create Mode of Payment")

	# Ensure company-level account mapping exists in Mode of Payment
	try:
		mop_doc = frappe.get_doc("Mode of Payment", mop_name)
		existing_cos = {r.company for r in mop_doc.get("accounts", [])}
		if company not in existing_cos and clearing_acc:
			mop_doc.append("accounts", {
				"company": company,
				"default_account": clearing_acc,
			})
			mop_doc.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Delivery System: update Mode of Payment accounts")

	# ── 3. Wire into Courier Settings ────────────────────────────────────────

	_update_courier_settings(
		company=company,
		clearing_account=clearing_acc,
		delivery_charge_account=delivery_charge_acc,
		variance_account=variance_acc,
		mode_of_payment=mop_name,
	)


def _ensure_account(
	company: str,
	account_name: str,
	abbr: str,
	root_type: str,
	account_type: str,
	parent_root_type: str,
	parent_account_type: str | None = None,
) -> str:
	"""
	Get or create a leaf (non-group) GL account for the given company.
	Returns the full account name (e.g. 'Steadfast Clearing Account - ABC').
	"""
	full_name = f"{account_name} - {abbr}"

	if frappe.db.exists("Account", full_name):
		return full_name

	# Find appropriate parent group
	parent = _find_parent_account(company, parent_root_type, parent_account_type)
	if not parent:
		frappe.logger("delivery_system").warning(
			f"Delivery System: no suitable parent account for '{account_name}' in company {company}"
		)
		return full_name  # Return expected name anyway; will fail gracefully at GL-posting time

	try:
		acc = frappe.get_doc({
			"doctype": "Account",
			"account_name": account_name,
			"company": company,
			"parent_account": parent,
			"root_type": root_type,
			"account_type": account_type,
			"is_group": 0,
		})
		acc.insert(ignore_permissions=True)
		return acc.name
	except frappe.DuplicateEntryError:
		return full_name
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Delivery System: create account '{account_name}' for {company}",
		)
		return full_name


def _find_parent_account(
	company: str,
	root_type: str,
	account_type: str | None = None,
) -> str | None:
	"""Find the nearest group account to use as parent."""
	# Try specific account_type first
	if account_type:
		parent = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 1, "root_type": root_type, "account_type": account_type},
			"name",
		)
		if parent:
			return parent

	# Fall back to any group under this root_type
	return frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": root_type},
		"name",
	)


def _update_courier_settings(
	company: str,
	clearing_account: str,
	delivery_charge_account: str,
	variance_account: str,
	mode_of_payment: str,
):
	"""Upsert a row in Courier Settings → Courier Accounts for this company."""
	try:
		settings = frappe.get_single("Courier Settings")

		# Find existing row for this company (use first provider = Steadfast)
		existing_row = None
		for row in settings.courier_accounts:
			if row.company == company:
				existing_row = row
				break

		if existing_row:
			# Only fill empty fields — don't overwrite user-configured credentials
			if not existing_row.clearing_account:
				existing_row.clearing_account = clearing_account
			if not existing_row.delivery_charge_account:
				existing_row.delivery_charge_account = delivery_charge_account
			if not existing_row.variance_account:
				existing_row.variance_account = variance_account
			if not existing_row.default_mode_of_payment:
				existing_row.default_mode_of_payment = mode_of_payment
		else:
			# Create a placeholder row (API key must be filled by the user)
			settings.append("courier_accounts", {
				"company": company,
				"courier_provider": frappe.db.get_value("Courier Provider", {"provider_code": "steadfast"}, "name") or "Steadfast",
				"api_key": "",
				"secret_key": "",
				"clearing_account": clearing_account,
				"delivery_charge_account": delivery_charge_account,
				"variance_account": variance_account,
				"default_mode_of_payment": mode_of_payment,
			})

		settings.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Delivery System: update Courier Settings")


def _sync_existing_reference_links():
	"""Ensure all existing Delivery Order records update their parent SO/DN delivery_order_ref & courier_status."""
	dos = frappe.get_all(
		"Delivery Order",
		filters={"docstatus": ["!=", 2]},
		fields=["name", "reference_doctype", "reference_name", "delivery_status"],
	)
	for d in dos:
		if d.reference_doctype and d.reference_name:
			if frappe.db.exists(d.reference_doctype, d.reference_name):
				try:
					frappe.db.set_value(
						d.reference_doctype,
						d.reference_name,
						{
							"delivery_order_ref": d.name,
							"courier_status": d.delivery_status,
						},
					)
				except Exception:
					pass

