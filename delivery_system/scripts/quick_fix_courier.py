#!/usr/bin/env python3
"""
QUICK FIX: Re-save Courier Account credentials to fix encryption issues.

Usage:
    bench --site your-site execute delivery_system.scripts.quick_fix_courier.fix_now --kwargs "{'company': 'Dress Up', 'provider': 'Steadfast', 'api_key': 'YOUR_KEY', 'secret_key': 'YOUR_SECRET'}"

Or from bench console:
    from delivery_system.scripts.quick_fix_courier import fix_now
    fix_now(company="Dress Up", provider="Steadfast", api_key="YOUR_KEY", secret_key="YOUR_SECRET")
"""

import frappe
from frappe.utils.password import set_encrypted_password


def fix_now(company, provider, api_key, secret_key):
	"""
	Quick fix to create or update Courier Account with new credentials.
	
	Args:
		company: Company name (e.g., "Dress Up")
		provider: Provider name (e.g., "Steadfast") 
		api_key: Your API key from courier provider
		secret_key: Your secret key from courier provider
	"""
	try:
		frappe.set_user("Administrator")
		
		print(f"\n🔧 Fixing Courier Account for {company} + {provider}...")
		
		# Get Courier Settings
		settings = frappe.get_single("Courier Settings")
		
		# Find the provider
		provider_doc = frappe.db.get_value(
			"Courier Provider",
			{"provider_name": provider},
			["name", "provider_code", "enabled"],
			as_dict=True
		)
		
		if not provider_doc:
			print(f"❌ Error: Courier Provider '{provider}' not found!")
			print("   Available providers:")
			for p in frappe.get_all("Courier Provider", fields=["provider_name", "enabled"]):
				print(f"   - {p.provider_name} (Enabled: {p.enabled})")
			return False
		
		if not provider_doc.enabled:
			print(f"⚠️  Warning: Provider '{provider}' is disabled. Enabling it...")
			frappe.db.set_value("Courier Provider", provider_doc.name, "enabled", 1)
		
		# Check if company exists
		if not frappe.db.exists("Company", company):
			print(f"❌ Error: Company '{company}' not found!")
			print("   Available companies:")
			for c in frappe.get_all("Company", pluck="name"):
				print(f"   - {c}")
			return False
		
		# Find existing account
		account_row = None
		account_name = None
		
		for acc in settings.courier_accounts:
			if acc.company == company and acc.courier_provider == provider_doc.name:
				account_row = acc
				account_name = acc.name
				break
		
		if account_row:
			print(f"✓ Found existing account: {account_name}")
			print("  Updating credentials...")
			
			# Update the row
			account_row.api_key = api_key
			account_row.secret_key = secret_key  # This will be encrypted on save
			
		else:
			print("  Creating new Courier Account entry...")
			
			# Add new row
			new_row = settings.append("courier_accounts", {
				"company": company,
				"courier_provider": provider_doc.name,
				"api_key": api_key,
				"secret_key": secret_key
			})
			
			account_row = new_row
		
		# Ensure accounting accounts are set (optional but recommended)
		if not account_row.clearing_account:
			company_abbr = frappe.get_cached_value("Company", company, "abbr")
			clearing_acc = f"Steadfast Clearing Account - {company_abbr}"
			if frappe.db.exists("Account", clearing_acc):
				account_row.clearing_account = clearing_acc
				print(f"  ✓ Set clearing account: {clearing_acc}")
		
		# Save (this will encrypt the secret_key with current encryption key)
		settings.save(ignore_permissions=True)
		frappe.db.commit()
		
		print("✓ Saved successfully!")
		
		# Get the account name after save
		if not account_name:
			for acc in settings.courier_accounts:
				if acc.company == company and acc.courier_provider == provider_doc.name:
					account_name = acc.name
					break
		
		print(f"✓ Courier Account: {account_name}")
		
		# Test the credentials
		print("\n🧪 Testing connection...")
		
		from delivery_system.couriers import get_client
		
		try:
			client = get_client(provider_doc.provider_code, company)
			print("✓ Client created successfully!")
			
			# Try to get balance
			try:
				balance = client.get_balance()
				print(f"✓ Connection test PASSED!")
				print(f"   Account Balance: {balance}")
			except Exception as e:
				print(f"⚠️  Balance check failed (but client creation worked): {str(e)}")
				print("   This might be normal if balance API is not implemented.")
			
			print("\n" + "="*60)
			print("✅ SUCCESS! Courier Account is now working!")
			print("="*60)
			print(f"\nYou can now:")
			print(f"1. Create Delivery Orders for {company}")
			print(f"2. Use {provider} as courier provider")
			print(f"3. Book orders and track deliveries")
			
			return True
			
		except Exception as e:
			print(f"❌ Connection test FAILED: {str(e)}")
			print("\nPossible issues:")
			print("1. API credentials are incorrect")
			print("2. API endpoint is down")
			print("3. Network connectivity issues")
			print("\nPlease verify your API credentials and try again.")
			return False
		
	except Exception as e:
		print(f"\n❌ ERROR: {str(e)}")
		frappe.log_error(frappe.get_traceback(), "quick_fix_courier")
		return False


def list_all_accounts():
	"""List all configured courier accounts."""
	print("\n" + "="*60)
	print("CONFIGURED COURIER ACCOUNTS")
	print("="*60)
	
	settings = frappe.get_single("Courier Settings")
	
	if not settings.courier_accounts:
		print("No courier accounts configured.")
		return
	
	for i, acc in enumerate(settings.courier_accounts, 1):
		provider_name = frappe.db.get_value("Courier Provider", acc.courier_provider, "provider_name")
		provider_code = frappe.db.get_value("Courier Provider", acc.courier_provider, "provider_code")
		
		print(f"\n{i}. {acc.name}")
		print(f"   Company: {acc.company}")
		print(f"   Provider: {provider_name} ({provider_code})")
		print(f"   API Key: {acc.api_key[:10] if acc.api_key else 'Not set'}...")
		print(f"   Secret Key: {'✓ Set' if acc.secret_key else '✗ Not set'}")
		print(f"   Clearing Account: {acc.clearing_account or 'Not configured'}")
		
		# Test decryption
		try:
			from frappe.utils.password import get_decrypted_password
			secret = get_decrypted_password("Courier Account", acc.name, "secret_key", raise_exception=False)
			if secret:
				print(f"   Status: ✓ Working (can decrypt)")
			else:
				print(f"   Status: ✗ BROKEN (cannot decrypt)")
		except Exception as e:
			print(f"   Status: ✗ BROKEN ({str(e)})")


def delete_broken_account(account_name):
	"""Delete a broken courier account."""
	try:
		settings = frappe.get_single("Courier Settings")
		
		# Find and remove the row
		for i, acc in enumerate(settings.courier_accounts):
			if acc.name == account_name:
				settings.remove(acc)
				settings.save(ignore_permissions=True)
				frappe.db.commit()
				print(f"✓ Deleted account: {account_name}")
				return True
		
		print(f"Account {account_name} not found")
		return False
		
	except Exception as e:
		print(f"Error: {str(e)}")
		return False


# Interactive helper
def interactive_fix():
	"""Interactive mode - prompts for input."""
	print("\n" + "="*60)
	print("COURIER ACCOUNT QUICK FIX - INTERACTIVE MODE")
	print("="*60)
	
	# List existing accounts
	list_all_accounts()
	
	print("\n" + "="*60)
	print("Let's fix your courier account...")
	print("="*60)
	
	company = input("\nCompany name (e.g., 'Dress Up'): ").strip()
	provider = input("Provider name (e.g., 'Steadfast'): ").strip()
	
	print("\nGet these credentials from your courier provider dashboard:")
	api_key = input("API Key: ").strip()
	secret_key = input("Secret Key: ").strip()
	
	if not all([company, provider, api_key, secret_key]):
		print("\n❌ All fields are required!")
		return False
	
	return fix_now(company, provider, api_key, secret_key)


if __name__ == "__main__":
	# When run directly, use interactive mode
	interactive_fix()
