# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

"""
Migration patch to update existing Delivery Orders with new field structure.

This patch:
1. Migrates clearing_journal_entry values to appropriate new fields
2. Identifies Payment Entries vs Journal Entries and sets correct field
3. Fixes any unlinked Payment Entries by linking them to Sales Invoices
4. Sets accounting_error flag for records needing manual review
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute():
	"""Main migration function."""
	frappe.logger("delivery_system").info("Starting migration: migrate_clearing_entries_to_new_fields")
	
	# Get all Delivery Orders with clearing entries
	delivery_orders = frappe.db.sql("""
		SELECT 
			name, 
			clearing_journal_entry,
			reversal_journal_entry,
			clearing_entry_posted,
			cod_amount,
			reference_doctype,
			reference_name
		FROM `tabDelivery Order`
		WHERE docstatus < 2
		  AND (clearing_journal_entry IS NOT NULL OR reversal_journal_entry IS NOT NULL)
	""", as_dict=True)
	
	if not delivery_orders:
		frappe.logger("delivery_system").info("No Delivery Orders to migrate")
		return
	
	frappe.logger("delivery_system").info(f"Found {len(delivery_orders)} Delivery Orders to migrate")
	
	stats = {
		"total": len(delivery_orders),
		"payment_entries": 0,
		"journal_entries": 0,
		"unlinked_pes_fixed": 0,
		"errors": 0,
		"skipped": 0
	}
	
	for do in delivery_orders:
		try:
			migrate_delivery_order(do, stats)
		except Exception as exc:
			stats["errors"] += 1
			frappe.log_error(
				f"Error migrating DO {do.name}: {str(exc)}\n{frappe.get_traceback()}",
				"migrate_clearing_entries.error"
			)
	
	# Log summary
	frappe.logger("delivery_system").info(
		f"Migration complete: {stats['total']} total, "
		f"{stats['payment_entries']} PEs, "
		f"{stats['journal_entries']} JEs, "
		f"{stats['unlinked_pes_fixed']} unlinked PEs fixed, "
		f"{stats['errors']} errors, "
		f"{stats['skipped']} skipped"
	)
	
	frappe.db.commit()


def migrate_delivery_order(do_dict, stats):
	"""Migrate a single Delivery Order."""
	do_name = do_dict.name
	clearing_ref = do_dict.clearing_journal_entry
	reversal_ref = do_dict.reversal_journal_entry
	
	update_fields = {}
	
	# Migrate clearing entry
	if clearing_ref:
		# Check if it's a Payment Entry
		if frappe.db.exists("Payment Entry", clearing_ref):
			pe_doc = frappe.get_doc("Payment Entry", clearing_ref)
			update_fields["clearing_payment_entry"] = clearing_ref
			stats["payment_entries"] += 1
			
			# Check if PE has Sales Invoice reference
			has_si_ref = any(
				r.reference_doctype == "Sales Invoice" 
				for r in (pe_doc.references or [])
			)
			
			if not has_si_ref and pe_doc.docstatus == 1:
				# Unlinked Payment Entry - try to fix it
				fixed = fix_unlinked_payment_entry(do_dict, pe_doc, update_fields)
				if fixed:
					stats["unlinked_pes_fixed"] += 1
				else:
					# Mark for manual review
					update_fields["accounting_error"] = 1
					update_fields["pending_payment_entry"] = 1
					frappe.logger("delivery_system").warning(
						f"DO {do_name}: Unlinked PE {clearing_ref} could not be fixed automatically"
					)
		
		# Check if it's a Journal Entry (legacy)
		elif frappe.db.exists("Journal Entry", clearing_ref):
			# Keep in clearing_journal_entry field (already there)
			# No need to update
			stats["journal_entries"] += 1
			frappe.logger("delivery_system").info(
				f"DO {do_name}: Legacy JE {clearing_ref} preserved"
			)
		
		else:
			# Reference doesn't exist - mark for review
			update_fields["accounting_error"] = 1
			update_fields["clearing_entry_posted"] = 0
			frappe.logger("delivery_system").warning(
				f"DO {do_name}: Clearing entry {clearing_ref} not found"
			)
			stats["errors"] += 1
	
	# Migrate reversal entry
	if reversal_ref:
		# Check if it's a Payment Entry
		if frappe.db.exists("Payment Entry", reversal_ref):
			update_fields["reversal_payment_entry"] = reversal_ref
		
		# Check if it's a Journal Entry
		elif frappe.db.exists("Journal Entry", reversal_ref):
			# Keep in reversal_journal_entry field (already there)
			pass
		
		else:
			frappe.logger("delivery_system").warning(
				f"DO {do_name}: Reversal entry {reversal_ref} not found"
			)
	
	# Apply updates if any
	if update_fields:
		frappe.db.set_value("Delivery Order", do_name, update_fields)
		frappe.logger("delivery_system").debug(
			f"DO {do_name}: Updated fields {list(update_fields.keys())}"
		)


def fix_unlinked_payment_entry(do_dict, pe_doc, update_fields):
	"""Try to fix an unlinked Payment Entry by finding and linking to Sales Invoice."""
	do_name = do_dict.name
	
	try:
		# Find the Sales Invoice for this Delivery Order
		from delivery_system.accounting import _find_existing_sales_invoice
		
		# Create a mock doc object
		mock_do = frappe._dict({
			"name": do_name,
			"reference_doctype": do_dict.reference_doctype,
			"reference_name": do_dict.reference_name,
			"invoice_reference": frappe.db.get_value("Delivery Order", do_name, "invoice_reference")
		})
		
		sales_invoice = _find_existing_sales_invoice(mock_do)
		
		if not sales_invoice:
			frappe.logger("delivery_system").info(
				f"DO {do_name}: No Sales Invoice found to link PE {pe_doc.name}"
			)
			return False
		
		# Check if SI is submitted
		si_doc = frappe.get_doc("Sales Invoice", sales_invoice)
		if si_doc.docstatus != 1:
			frappe.logger("delivery_system").info(
				f"DO {do_name}: Sales Invoice {sales_invoice} not submitted, cannot link PE"
			)
			return False
		
		outstanding = flt(si_doc.outstanding_amount)
		if outstanding <= 0:
			# Already paid
			frappe.logger("delivery_system").info(
				f"DO {do_name}: Sales Invoice {sales_invoice} already fully paid"
			)
			update_fields["pending_payment_entry"] = 0
			return True
		
		# Check if adding this PE would overpay
		pe_amount = flt(pe_doc.paid_amount or pe_doc.received_amount)
		if pe_amount > outstanding:
			frappe.logger("delivery_system").warning(
				f"DO {do_name}: PE amount {pe_amount} exceeds SI outstanding {outstanding}"
			)
			# Don't auto-link to avoid overpayment
			return False
		
		# Cancel the old unlinked PE
		if pe_doc.docstatus == 1:
			pe_doc.cancel()
			frappe.logger("delivery_system").info(
				f"DO {do_name}: Cancelled unlinked PE {pe_doc.name}"
			)
		
		# Create new linked PE
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
		from frappe.utils import today
		
		try:
			new_pe = get_payment_entry("Sales Invoice", sales_invoice)
			new_pe.paid_to = pe_doc.paid_to
			new_pe.paid_amount = pe_amount
			new_pe.received_amount = pe_amount
			new_pe.posting_date = pe_doc.posting_date or today()
			new_pe.reference_no = pe_doc.reference_no
			new_pe.reference_date = pe_doc.reference_date or today()
			
			if new_pe.references:
				new_pe.references[0].allocated_amount = pe_amount
			
			new_pe.insert(ignore_permissions=True)
			new_pe.submit()
			
			# Update DO to point to new PE
			update_fields["clearing_payment_entry"] = new_pe.name
			update_fields["clearing_entry_posted"] = 1
			update_fields["pending_payment_entry"] = 0
			update_fields["accounting_error"] = 0
			
			frappe.logger("delivery_system").info(
				f"DO {do_name}: Created new linked PE {new_pe.name} for SI {sales_invoice}"
			)
			
			return True
			
		except Exception as exc:
			frappe.log_error(
				f"Failed to create new PE for DO {do_name}: {str(exc)}",
				"migrate_clearing_entries.create_pe_failed"
			)
			return False
	
	except Exception as exc:
		frappe.log_error(
			f"Error fixing unlinked PE for DO {do_name}: {str(exc)}",
			"migrate_clearing_entries.fix_unlinked_pe"
		)
		return False


def get_sales_invoice_for_payment_entry(pe_doc):
	"""Extract Sales Invoice from Payment Entry references."""
	if not pe_doc.references:
		return None
	
	for ref in pe_doc.references:
		if ref.reference_doctype == "Sales Invoice":
			return ref.reference_name
	
	return None
