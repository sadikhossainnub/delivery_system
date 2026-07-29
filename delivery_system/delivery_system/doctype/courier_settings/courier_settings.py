# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


from frappe.utils.password import get_decrypted_password


class CourierSettings(Document):
	def validate(self):
		"""Auto-generate webhook secrets and calculate Webhook URLs for all courier accounts."""
		site_url = frappe.utils.get_url()
		webhook_endpoint = "/api/method/delivery_system.webhook.steadfast_webhook"

		for account in self.courier_accounts:
			if not account.webhook_secret or "*" in str(account.webhook_secret):
				account.webhook_secret = frappe.generate_hash(length=32)

			account.webhook_url = f"{site_url}{webhook_endpoint}"

	def get_account(self, provider_code: str, company: str | None = None) -> dict | None:
		"""
		Return the credentials dict for the given provider and company.
		Falls back to the first matching provider account if company is not specified.
		"""
		for account in self.courier_accounts:
			provider = frappe.db.get_value(
				"Courier Provider", account.courier_provider, ["provider_code", "base_url", "enabled"], as_dict=True
			)
			if not provider or not provider.enabled:
				continue
			if provider.provider_code != provider_code:
				continue
			if company and account.company != company:
				continue

			secret_val = get_decrypted_password(
				"Courier Account", account.name, fieldname="secret_key", raise_exception=False
			)
			api_key_val = get_decrypted_password(
				"Courier Account", account.name, fieldname="api_key", raise_exception=False
			) or account.api_key

			if not secret_val:
				frappe.log_error(
					f"Courier Account '{account.name}': secret_key could not be decrypted. "
					"Please re-save Courier Settings with the correct Secret Key.",
					"CourierSettings.get_account",
				)
				return None

			return {
				"api_key": api_key_val,
				"secret_key": secret_val,
				"webhook_secret": account.webhook_secret or None,
				"webhook_url": account.webhook_url or None,
				"base_url": provider.base_url,
				"company": account.company,
				"courier_provider": account.courier_provider,
			}
		return None


@frappe.whitelist()
def generate_new_webhook_secret(company: str, courier_provider: str) -> str:
	"""Regenerate a new 32-character webhook secret for a specific company and provider."""
	settings = frappe.get_single("Courier Settings")
	new_secret = frappe.generate_hash(length=32)

	updated = False
	for row in settings.courier_accounts:
		if row.company == company and row.courier_provider == courier_provider:
			row.webhook_secret = new_secret
			updated = True
			break

	if updated:
		settings.save(ignore_permissions=True)
		return new_secret
	else:
		frappe.throw(_("No Courier Account found for Company: {0} and Provider: {1}").format(company, courier_provider))
