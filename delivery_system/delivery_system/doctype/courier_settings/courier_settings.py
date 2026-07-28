# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CourierSettings(Document):
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
			return {
				"api_key": account.api_key,
				"secret_key": account.get_password("secret_key"),
				"webhook_secret": account.get_password("webhook_secret") if account.webhook_secret else None,
				"base_url": provider.base_url,
				"company": account.company,
				"courier_provider": account.courier_provider,
			}
		return None
