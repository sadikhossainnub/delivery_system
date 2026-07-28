# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

# Default base URLs per provider code
PROVIDER_DEFAULTS = {
	"steadfast": "https://portal.packzy.com/api/v1",
	"pathao": "https://hermes.pathao.com/api/v1",
	"redx": "https://openapi.redx.com.bd/v1.0.0-beta",
	"paperfly": "https://api.paperfly.com.bd/api",
	"ecourier": "https://ecourier.com.bd/api",
}


class CourierProvider(Document):
	def before_insert(self):
		if not self.base_url and self.provider_code:
			self.base_url = PROVIDER_DEFAULTS.get(self.provider_code, "")

	def validate(self):
		if self.provider_code and not self.base_url:
			self.base_url = PROVIDER_DEFAULTS.get(self.provider_code, "")
