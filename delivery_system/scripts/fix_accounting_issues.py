#!/usr/bin/env python3
# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

"""
Manual script to fix accounting issues in Delivery Orders.

Run with:
    bench execute delivery_system.scripts.fix_accounting_issues.run_fix --kwargs "{'site': 'your-site-name'}"

Or from bench console:
    from delivery_system.scripts.fix_accounting_issues import run_fix
    run_fix()
"""

import frappe
from frappe.utils import flt


def run_fix(site=None, dry_run=False):
	"""
	Main function to fix accounting issues.
	
	Args:
		site: Site name (optional, uses current site if in bench context)
		dry_run: If True, only report issues without fixing (default: False)
	"""
	if not frappe.db:
		if not site:
			print("ERROR: No site specified and not in bench context")
			return
		frappe.init(site=site)
		frappe.connect()
	
	print("="*80)
	print("Delivery Order Accounting Fix Script")
	print("="*80)
	print(f"Mode: {'DRY RUN (no changes)' if dry_run else 'LIVE (will make changes)'}")
	print()
	
	issues_found = {
		"unlinked_pes": [],
		"missing_si": [],
		"legacy_jes": [],
		"accounting_errors": [],
		"pending_payments": []
	}
	
	# 1. Find Delivery Orders with unlinked Payment Entries
	print("1. Checking for unlinked Payment Entries...")
	unlinked_pes = find_unlinked_payment_entries()
	issues_found["unlinked_pes"] = unlinked_pes
	print(f"   Found: {len(unlinked_pes)} unlinked Payment Entries")
	
	# 2. Find delivered DOs without Payment Entries
	print("\n2. Checking for delivered orders without Payment Entries...")
	missing_pes = find_delivered_without_payment_entries()
	issues_found["missing_si"] = missing_pes
	print(f"   Found: {len(missing_pes)} delivered orders without Payment Entries")
	
	# 3. Find legacy Journal Entries
	print("\n3. Checking for legacy Journal Entries...")
	legacy_jes = find_legacy_journal_entries()
	issues_found["legacy_jes"] = legacy_jes
	print(f"   Found: {len(legacy_jes)} legacy Journal Entries")
	
	# 4. Find orders with accounting errors
	print("\n4. Checking for orders with accounting errors...")
	accounting_errors = find_accounting_errors()
	issues_found["accounting_errors"] = accounting_errors
	print(f"   Found: {len(accounting_errors)} orders with accounting errors")
	
	# 5. Find orders pending payment entries
	print("\n5. Checking for orders pending payment entries...")
	pending_payments = find_pending_payment_entries()
	issues_found["pending_payments"] = pending_payments
	print(f"   Found: {len(pending_payments)} orders pending payment entries")
	
	# Summary
	print("\n" + "="*80)
	print("SUMMARY")
	print("="*80)
	total_issues = sum(len(v) for v in issues_found.values())
	print(f"Total issues found: {total_issues}")
	print()
	
	if total_issues == 0:
		print("✅ No issues found! All Delivery Orders are in good state.")
		return issues_found
	
	# Fix issues if not dry run
	if not dry_run:
		print("\n" + "="*80)
		print("FIXING ISSUES")
		print("="*80)
		
		fixed_count = 0
		failed_count = 0
		
		# Fix unlinked PEs
		if unlinked_pes:
			print(f"\nFixing {len(unlinked_pes)} unlinked Payment Entries...")
			for do_name, pe_name in unlinked_pes:
				try:
					if fix_unlinked_payment_entry_wrapper(do_name, pe_name):
						fixed_count += 1
						print(f"  ✓ Fixed DO {do_name}")
					else:
						failed_count += 1
						print(f"  ✗ Failed DO {do_name}")
				except Exception as e:
					failed_count += 1
					print(f"  ✗ Error DO {do_name}: {str(e)}")
		
		# Fix missing PEs
		if missing_pes:
			print(f"\nFixing {len(missing_pes)} delivered orders without Payment Entries...")
			for do_name in missing_pes:
				try:
					if create_missing_payment_entry(do_name):
						fixed_count += 1
						print(f"  ✓ Fixed DO {do_name}")
					else:
						failed_count += 1
						print(f"  ✗ Failed DO {do_name}")
				except Exception as e:
					failed_count += 1
					print(f"  ✗ Error DO {do_name}: {str(e)}")
		
		print("\n" + "="*80)
		print(f"Fixed: {fixed_count} | Failed: {failed_count}")
		print("="*80)
		
		frappe.db.commit()
	else:
		print("\n⚠️  DRY RUN - No changes made. Run with dry_run=False to fix issues.")
	
	return issues_found


def find_unlinked_payment_entries():
	"""Find Payment Entries without Sales Invoice references."""
	results = frappe.db.sql("""
		SELECT 
			do.name as do_name,
			do.clearing_journal_entry as pe_name
		FROM `tabDelivery Order` do
		WHERE do.docstatus < 2
		  AND do.clearing_entry_posted = 1
		  AND do.clearing_journal_entry IS NOT NULL
		  AND EXISTS (
		      SELECT 1 FROM `tabPayment Entry` pe
		      WHERE pe.name = do.clearing_journal_entry
		        AND pe.docstatus = 1
		        AND NOT EXISTS (
		            SELECT 1 FROM `tabPayment Entry Reference` per
		            WHERE per.parent = pe.name
		              AND per.reference_doctype = 'Sales Invoice'
		        )
		  )
	""", as_dict=True)
	
	return [(r.do_name, r.pe_name) for r in results]


def find_delivered_without_payment_entries():
	"""Find delivered DOs without Payment Entries."""
	results = frappe.db.sql("""
		SELECT name
		FROM `tabDelivery Order`
		WHERE docstatus < 2
		  AND delivery_status IN ('delivered', 'partial_delivered')
		  AND cod_amount > 0
		  AND (clearing_entry_posted = 0 OR clearing_entry_posted IS NULL)
		ORDER BY modified DESC
	""", as_dict=True)
	
	return [r.name for r in results]


def find_legacy_journal_entries():
	"""Find DOs using legacy Journal Entries."""
	results = frappe.db.sql("""
		SELECT 
			do.name as do_name,
			do.clearing_journal_entry as je_name
		FROM `tabDelivery Order` do
		WHERE do.docstatus < 2
		  AND do.clearing_entry_posted = 1
		  AND do.clearing_journal_entry IS NOT NULL
		  AND EXISTS (
		      SELECT 1 FROM `tabJournal Entry` je
		      WHERE je.name = do.clearing_journal_entry
		  )
	""", as_dict=True)
	
	return [(r.do_name, r.je_name) for r in results]


def find_accounting_errors():
	"""Find DOs marked with accounting errors."""
	results = frappe.db.sql("""
		SELECT name
		FROM `tabDelivery Order`
		WHERE docstatus < 2
		  AND accounting_error = 1
		ORDER BY modified DESC
	""", as_dict=True)
	
	return [r.name for r in results]


def find_pending_payment_entries():
	"""Find DOs pending payment entries."""
	results = frappe.db.sql("""
		SELECT name
		FROM `tabDelivery Order`
		WHERE docstatus < 2
		  AND pending_payment_entry = 1
		ORDER BY modified DESC
	""", as_dict=True)
	
	return [r.name for r in results]


def fix_unlinked_payment_entry_wrapper(do_name, pe_name):
	"""Fix a specific unlinked Payment Entry."""
	from delivery_system.accounting import _find_existing_sales_invoice
	
	try:
		# Load DO
		do_doc = frappe.get_doc("Delivery Order", do_name)
		
		# Find Sales Invoice
		sales_invoice = _find_existing_sales_invoice(do_doc)
		
		if not sales_invoice:
			print(f"    ⚠️  No Sales Invoice found for DO {do_name}")
			frappe.db.set_value("Delivery Order", do_name, {
				"pending_payment_entry": 1,
				"accounting_error": 1
			})
			return False
		
		# Cancel old unlinked PE
		old_pe = frappe.get_doc("Payment Entry", pe_name)
		if old_pe.docstatus == 1:
			old_pe.cancel()
		
		# Recreate with SI link
		from delivery_system.accounting import post_clearing_entry
		new_pe_name = post_clearing_entry(do_doc, force=True)
		
		if new_pe_name:
			print(f"    ✓ Created new PE {new_pe_name} linked to SI {sales_invoice}")
			return True
		else:
			print(f"    ✗ Failed to create new PE")
			return False
	
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"fix_unlinked_pe_{do_name}")
		return False


def create_missing_payment_entry(do_name):
	"""Create missing Payment Entry for delivered DO."""
	try:
		do_doc = frappe.get_doc("Delivery Order", do_name)
		
		from delivery_system.accounting import post_clearing_entry
		pe_name = post_clearing_entry(do_doc)
		
		if pe_name:
			print(f"    ✓ Created PE {pe_name}")
			return True
		else:
			print(f"    ✗ Failed to create PE (check logs)")
			return False
	
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"create_missing_pe_{do_name}")
		return False


# Convenience function for bench console
def preview():
	"""Preview issues without fixing (dry run)."""
	return run_fix(dry_run=True)


def fix_all():
	"""Fix all issues (live mode)."""
	return run_fix(dry_run=False)


if __name__ == "__main__":
	# When run directly, do a dry run
	run_fix(dry_run=True)
