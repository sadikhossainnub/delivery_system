#!/usr/bin/env python3
"""
Test script to diagnose why Payment Entry is not being created automatically
when Delivery Order status changes to 'delivered'.
"""

import frappe
from frappe.utils import today

def test_payment_entry_creation():
    """Test the payment entry creation flow"""
    
    print("\n" + "="*70)
    print("DIAGNOSTIC TEST: Automatic Payment Entry Creation")
    print("="*70)
    
    # Step 1: Check Courier Settings
    print("\n[1] Checking Courier Settings...")
    try:
        settings = frappe.get_single("Courier Settings")
        print(f"    ✓ enable_accounting_automation: {settings.enable_accounting_automation}")
        
        if not settings.enable_accounting_automation:
            print("    ❌ ISSUE FOUND: Accounting automation is DISABLED!")
            print("    → Fix: Enable it in Courier Settings")
            return
        
        if not settings.courier_accounts:
            print("    ❌ ISSUE FOUND: No Courier Accounts configured!")
            return
        
        for acc in settings.courier_accounts:
            print(f"    ✓ Company: {acc.company}")
            print(f"      Provider: {acc.courier_provider}")
            print(f"      Clearing Account: {acc.clearing_account or 'NOT SET ❌'}")
            
            if not acc.clearing_account:
                print(f"    ❌ ISSUE FOUND: Clearing account not set for {acc.company}")
                
    except Exception as e:
        print(f"    ❌ ERROR: {e}")
        return
    
    # Step 2: Find a test Delivery Order
    print("\n[2] Finding a test Delivery Order...")
    try:
        do_list = frappe.get_all("Delivery Order",
            filters={
                "docstatus": 1,
                "delivery_status": "delivered"
            },
            fields=["name", "delivery_status", "cod_amount", 
                   "clearing_entry_posted", "clearing_journal_entry",
                   "reference_doctype", "reference_name"],
            limit=1
        )
        
        if not do_list:
            print("    ❌ No delivered orders found for testing")
            print("    → Create a test order and mark it as delivered")
            return
        
        do = do_list[0]
        print(f"    ✓ Found: {do.name}")
        print(f"      Status: {do.delivery_status}")
        print(f"      COD Amount: {do.cod_amount}")
        print(f"      Clearing Entry Posted: {do.clearing_entry_posted}")
        print(f"      Payment Entry: {do.clearing_journal_entry or 'None'}")
        
        if do.clearing_entry_posted and do.clearing_journal_entry:
            print(f"    ✓ Payment Entry already exists: {do.clearing_journal_entry}")
            
            # Check if it exists
            if frappe.db.exists("Payment Entry", do.clearing_journal_entry):
                pe = frappe.get_doc("Payment Entry", do.clearing_journal_entry)
                print(f"      Status: {pe.docstatus}")
                print(f"      Amount: {pe.paid_amount}")
            else:
                print(f"    ❌ Payment Entry {do.clearing_journal_entry} doesn't exist!")
        else:
            print("    ⚠️  No payment entry posted yet")
        
        # Step 3: Check Reference Document
        print(f"\n[3] Checking Reference Document...")
        if do.reference_doctype and do.reference_name:
            print(f"    Reference: {do.reference_doctype} - {do.reference_name}")
            
            if frappe.db.exists(do.reference_doctype, do.reference_name):
                ref_doc = frappe.get_doc(do.reference_doctype, do.reference_name)
                print(f"    ✓ Company: {ref_doc.company}")
                print(f"      Customer: {ref_doc.customer}")
                
                # Check for Sales Invoice
                print(f"\n[4] Checking for Sales Invoice...")
                from delivery_system.accounting import get_or_create_sales_invoice
                
                try:
                    do_doc = frappe.get_doc("Delivery Order", do.name)
                    sinv = get_or_create_sales_invoice(do_doc, auto_create=False)
                    
                    if sinv:
                        print(f"    ✓ Sales Invoice found: {sinv}")
                        sinv_doc = frappe.get_doc("Sales Invoice", sinv)
                        print(f"      Grand Total: {sinv_doc.grand_total}")
                        print(f"      Outstanding: {sinv_doc.outstanding_amount}")
                        print(f"      Status: {sinv_doc.status}")
                    else:
                        print(f"    ❌ No Sales Invoice found!")
                        print(f"    → This is likely the issue!")
                        print(f"    → Sales Invoice is required for Payment Entry")
                        
                except Exception as e:
                    print(f"    ❌ ERROR checking Sales Invoice: {e}")
                    import traceback
                    print(traceback.format_exc())
                
            else:
                print(f"    ❌ Reference document doesn't exist!")
        else:
            print(f"    ❌ No reference document linked!")
        
        # Step 5: Try to manually trigger
        print(f"\n[5] Attempting Manual Trigger...")
        try:
            from delivery_system.accounting import post_clearing_entry
            
            do_doc = frappe.get_doc("Delivery Order", do.name)
            result = post_clearing_entry(do_doc, force=False, auto_create_invoice=True)
            
            if result:
                print(f"    ✓ SUCCESS! Payment Entry created: {result}")
            else:
                print(f"    ⚠️  No Payment Entry created")
                print(f"    → Check the conditions in post_clearing_entry()")
                
        except Exception as e:
            print(f"    ❌ ERROR: {e}")
            import traceback
            print(traceback.format_exc())
        
    except Exception as e:
        print(f"    ❌ ERROR: {e}")
        import traceback
        print(traceback.format_exc())
    
    print("\n" + "="*70)
    print("DIAGNOSIS COMPLETE")
    print("="*70)

if __name__ == "__main__":
    # Run in Frappe context
    import sys
    sys.path.insert(0, "/home/prime/frappe-bench/apps/frappe")
    
    frappe.init(site="your-site-name")
    frappe.connect()
    
    test_payment_entry_creation()
    
    frappe.db.commit()
    frappe.destroy()
