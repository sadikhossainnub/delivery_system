#!/usr/bin/env python3
# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

"""
Script to fix Courier Account configuration issues.

Common Issues Fixed:
1. Encryption key errors (decrypt failures)
2. Missing Courier Account for company/provider combinations
3. Invalid or corrupted credentials

Run with:
    bench execute delivery_system.scripts.fix_courier_account_issues.run_fix

Or from bench console:
    from delivery_system.scripts.fix_courier_account_issues import *
    preview_issues()
    fix_all_issues()
"""

import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password


def preview_issues():
	"""Preview all courier account issues without fixing."""
	print("="*80)
	print("COURIER ACCOUNT ISSUES - PREVIEW")
	print("="*80)
	
	issues = analyze_courier_accounts()
	
	print(f"\n📊 Summary:")
	print(f"   Total Accounts: {issues['total']}")
	print(f"   ✓ Working: {issues['working']}")
	print(f"   ✗ Broken: {issues['broken']}")
	print(f"   ⚠️  Missing Company Coverage: {len(issues['missing_companies'])}")
	
	if issues['broken_accounts']:
		print(f"\n🔴 Broken Accounts ({len(issues['broken_accounts'])}):")
		for acc in issues['broken_accounts']:
			print(f"   • {acc['name']}: {acc['company']} / {acc['provider']} - {acc['error']}")
	
	if issues['missing_companies']:
		print(f"\n⚠️  Companies without Courier Account:")
		for company, providers in issues['missing_companies'].items():
			print(f"   • {company}: Missing {', '.join(providers)}")
	
	return issues


def analyze_courier_accounts():
	"""Analyze all courier accounts and identify issues."""
	settings = frappe.get_single("Courier Settings")
	
	issues = {
		"total": len(settings.courier_accounts),
		"working": 0,
		"broken": 0,
		"broken_accounts": [],
		"missing_companies": {},
		"working_accounts": []
	}
	
	for account in settings.courier_accounts:
		try:
			provider = frappe.db.get_value(
				"Courier Provider", 
				account.courier_provider, 
				["provider_code", "base_url", "enabled"], 
				as_dict=True
			)
			
			if not provider:
				issues['broken'] += 1
				issues['broken_accounts'].append({
					"name": account.name,
					"company": account.company,
					"provider": account.courier_provider,
					"error": "Provider not found"
				})
				continue
			
			if not provider.enabled:
				issues['broken'] += 1
				issues['broken_accounts'].append({
					"name": account.name,
					"company": account.company,
					"provider": account.courier_provider,
					"error": "Provider disabled"
				})
				continue
			
			# Skip manual providers
			if provider.provider_code in ("manual", "local"):
				issues['working'] += 1
				issues['working_accounts'].append(account.name)
				continue
			
			# Try to decrypt credentials
			secret_val = get_decrypted_password(
				"Courier Account", 
				account.name, 
				fieldname="secret_key", 
				raise_exception=False
			)
			
			api_key_val = get_decrypted_password(
				"Courier Account", 
				account.name, 
				fieldname="api_key", 
				raise_exception=False
			) or account.api_key
			
			if not secret_val:
				issues['broken'] += 1
				issues['broken_accounts'].append({
					"name": account.name,
					"company": account.company,
					"provider": account.courier_provider,
					"error": "Cannot decrypt secret_key (encryption key mismatch)"
				})
			elif not api_key_val:
				issues['broken'] += 1
				issues['broken_accounts'].append({
					"name": account.name,
					"company": account.company,
					"provider": account.courier_provider,
					"error": "Missing api_key"
				})
			else:
				issues['working'] += 1
				issues['working_accounts'].append(account.name)
		
		except Exception as e:
			issues['broken'] += 1
			issues['broken_accounts'].append({
				"name": account.name,
				"company": account.company,
				"provider": account.courier_provider,
				"error": str(e)
			})
	
	# Check for missing company coverage
	all_companies = frappe.get_all("Company", pluck="name")
	all_providers = frappe.get_all("Courier Provider", filters={"enabled": 1}, pluck="name")
	
	for company in all_companies:
		configured_providers = [
			acc.courier_provider 
			for acc in settings.courier_accounts 
			if acc.company == company
		]
		missing = set(all_providers) - set(configured_providers)
		if missing:
			issues['missing_companies'][company] = list(missing)
	
	return issues


def fix_encryption_issue(account_name, new_api_key=None, new_secret_key=None):
	"""Fix encryption issue for a specific account by re-setting credentials.
	
	Args:
		account_name: Name of the Courier Account
		new_api_key: New API key (if None, will prompt or use existing)
		new_secret_key: New Secret key (required)
	"""
	if not new_secret_key:
		frappe.throw("new_secret_key is required to fix encryption issues")
	
	# Get the settings doc (parent)
	settings = frappe.get_single("Courier Settings")
	
	# Find the account row
	account_row = None
	for acc in settings.courier_accounts:
		if acc.name == account_name:
			account_row = acc
			break
	
	if not account_row:
		frappe.throw(f"Courier Account {account_name} not found")
	
	# Update API key (plain text)
	if new_api_key:
		account_row.api_key = new_api_key
	
	# Set encrypted password for secret_key
	set_encrypted_password(
		"Courier Account",
		account_name,
		new_secret_key,
		fieldname="secret_key"
	)
	
	# Save parent doc
	settings.save(ignore_permissions=True)
	
	print(f"✓ Fixed encryption for {account_name}")
	return True


def create_missing_courier_account(company, courier_provider, api_key, secret_key):
	"""Create a new Courier Account for company/provider combination.
	
	Args:
		company: Company name
		courier_provider: Courier Provider name
		api_key: API Key
		secret_key: Secret Key
	"""
	settings = frappe.get_single("Courier Settings")
	
	# Check if already exists
	for acc in settings.courier_accounts:
		if acc.company == company and acc.courier_provider == courier_provider:
			print(f"⚠️  Account already exists for {company} / {courier_provider}")
			return acc.name
	
	# Add new row
	settings.append("courier_accounts", {
		"company": company,
		"courier_provider": courier_provider,
		"api_key": api_key,
		"secret_key": secret_key
	})
	
	settings.save(ignore_permissions=True)
	
	# Get the newly created row name
	for acc in settings.courier_accounts:
		if acc.company == company and acc.courier_provider == courier_provider:
			print(f"✓ Created Courier Account: {acc.name} for {company} / {courier_provider}")
			return acc.name
	
	return None


def fix_all_issues_interactive():
	"""Interactive fix - prompts user for credentials."""
	issues = preview_issues()
	
	if issues['broken'] == 0:
		print("\n✅ No broken accounts found!")
		return
	
	print("\n" + "="*80)
	print("FIXING BROKEN ACCOUNTS")
	print("="*80)
	
	for acc in issues['broken_accounts']:
		print(f"\n🔧 Fixing: {acc['name']} ({acc['company']} / {acc['provider']})")
		print(f"   Error: {acc['error']}")
		
		if "decrypt" in acc['error'].lower() or "encryption" in acc['error'].lower():
			print("\n   This account has encryption issues. You need to provide credentials again.")
			print("   Hint: Get these from your courier provider dashboard")
			
			api_key = input("   Enter API Key: ").strip()
			secret_key = input("   Enter Secret Key: ").strip()
			
			if api_key and secret_key:
				try:
					fix_encryption_issue(acc['name'], api_key, secret_key)
				except Exception as e:
					print(f"   ✗ Failed: {str(e)}")
			else:
				print("   ⏭️  Skipped (no credentials provided)")


def create_missing_accounts_for_company(company, provider_name, api_key, secret_key):
	"""Helper to create account for a company if missing."""
	return create_missing_courier_account(company, provider_name, api_key, secret_key)


def check_site_encryption_key():
	"""Check if site has proper encryption key configured."""
	try:
		site_config = frappe.get_site_config()
		
		if "encryption_key" not in site_config:
			print("⚠️  WARNING: No encryption_key in site_config.json")
			print("   Encrypted passwords will not work properly.")
			print("\n   To fix:")
			print("   1. Generate key: python -c 'from frappe.utils import get_encryption_key; print(get_encryption_key())'")
			print("   2. Add to sites/<site>/site_config.json:")
			print('      "encryption_key": "<generated-key>"')
			return False
		else:
			print("✓ Encryption key is configured")
			return True
	except Exception as e:
		print(f"✗ Error checking encryption key: {str(e)}")
		return False


def test_courier_connection(company, provider_code):
	"""Test if courier client can be created and connected."""
	try:
		from delivery_system.couriers import get_client
		
		client = get_client(provider_code, company)
		
		# Try ping if available
		if hasattr(client, 'ping'):
			result = client.ping()
			print(f"✓ Connection test passed: {result}")
		else:
			print(f"✓ Client created successfully (ping not available)")
		
		return True
	except Exception as e:
		print(f"✗ Connection test failed: {str(e)}")
		return False


def run_fix():
	"""Main fix function - shows preview and allows interactive fixing."""
	print("\n🔍 Checking site encryption key...")
	check_site_encryption_key()
	
	print("\n🔍 Analyzing courier accounts...")
	issues = preview_issues()
	
	if issues['broken'] == 0:
		print("\n✅ All courier accounts are working correctly!")
	else:
		print(f"\n⚠️  Found {issues['broken']} broken account(s)")
		
		response = input("\nDo you want to fix these issues interactively? (y/n): ").strip().lower()
		if response == 'y':
			fix_all_issues_interactive()
			
			# Re-analyze after fixing
			print("\n" + "="*80)
			print("RE-CHECKING AFTER FIXES")
			print("="*80)
			preview_issues()


# Quick access functions for common issues
def fix_steadfast_dress_up(api_key, secret_key):
	"""Quick fix for the specific error: Steadfast / Dress Up company."""
	try:
		# Check if account exists
		settings = frappe.get_single("Courier Settings")
		
		account_exists = False
		account_name = None
		
		for acc in settings.courier_accounts:
			provider_code = frappe.db.get_value("Courier Provider", acc.courier_provider, "provider_code")
			if acc.company == "Dress Up" and provider_code == "steadfast":
				account_exists = True
				account_name = acc.name
				break
		
		if account_exists:
			print(f"Found existing account: {account_name}")
			print("Re-setting credentials...")
			fix_encryption_issue(account_name, api_key, secret_key)
		else:
			print("Creating new Courier Account for Dress Up / Steadfast...")
			# Get Steadfast provider
			steadfast_provider = frappe.db.get_value(
				"Courier Provider",
				{"provider_code": "steadfast"},
				"name"
			)
			
			if not steadfast_provider:
				print("✗ Steadfast provider not found. Please create it first.")
				return False
			
			create_missing_courier_account("Dress Up", steadfast_provider, api_key, secret_key)
		
		print("\n✓ Testing connection...")
		return test_courier_connection("Dress Up", "steadfast")
		
	except Exception as e:
		print(f"✗ Error: {str(e)}")
		frappe.log_error(frappe.get_traceback(), "fix_steadfast_dress_up")
		return False


if __name__ == "__main__":
	run_fix()
