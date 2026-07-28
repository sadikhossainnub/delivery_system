# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Courier abstraction layer.
# To add a new courier:
#   1. Create `couriers/<provider_code>.py` implementing BaseCourierClient
#   2. Add the provider_code to the REGISTRY dict below
#   3. Add a fixture record in Courier Provider with the same provider_code

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
	pass


class BaseCourierClient(ABC):
	"""Abstract base class for all courier API clients.

	Subclasses must implement every abstract method.
	All methods should raise ``frappe.ValidationError`` on courier-side errors
	(non-2xx HTTP responses, validation failures, etc.) so the UI can display
	a clean message without exposing raw HTTP exceptions.
	"""

	def __init__(self, api_key: str, secret_key: str, base_url: str):
		self.api_key = api_key
		self.secret_key = secret_key
		self.base_url = base_url.rstrip("/")

	# ------------------------------------------------------------------
	# Required implementations
	# ------------------------------------------------------------------

	@abstractmethod
	def create_order(self, order_data: dict) -> dict:
		"""Book a single consignment.

		Args:
			order_data: Dict with keys: invoice, recipient_name, recipient_phone,
				recipient_address, cod_amount, note (optional), delivery_type (optional).

		Returns:
			Dict with at minimum: consignment_id, tracking_code, status
		"""

	@abstractmethod
	def bulk_create(self, orders: list[dict]) -> list[dict]:
		"""Book multiple consignments in one API call (where supported).

		Args:
			orders: List of order_data dicts (same schema as create_order).

		Returns:
			List of result dicts in the same order as ``orders``.
		"""

	@abstractmethod
	def get_status(
		self,
		invoice: str | None = None,
		consignment_id: str | None = None,
		tracking_code: str | None = None,
	) -> dict:
		"""Check delivery status using any one of the three identifiers.

		Returns:
			Dict with at minimum: status, consignment_id (optional: tracking_code, message)
		"""

	@abstractmethod
	def get_balance(self) -> dict:
		"""Return the current account balance."""

	@abstractmethod
	def create_return_request(self, consignment_id: str, reason: str = "") -> dict:
		"""Initiate a return / pickup request for a consignment."""

	# ------------------------------------------------------------------
	# Optional helper (may be overridden)
	# ------------------------------------------------------------------

	def get_return_request(self, return_id: str) -> dict:
		raise NotImplementedError

	def get_return_requests(self) -> list[dict]:
		raise NotImplementedError

	def get_payments(self) -> list[dict]:
		raise NotImplementedError

	def get_payment(self, payment_id: str) -> dict:
		raise NotImplementedError


# ---------------------------------------------------------------------------
# Provider registry — maps provider_code → module path
# ---------------------------------------------------------------------------

REGISTRY: dict[str, str] = {
	"steadfast": "delivery_system.couriers.steadfast",
	"pathao": "delivery_system.couriers.pathao",
	"redx": "delivery_system.couriers.redx",
}


def get_client(provider_code: str, company: str | None = None) -> BaseCourierClient:
	"""Factory: read credentials from Courier Settings and return the correct client.

	Args:
		provider_code: Must match a key in ``REGISTRY`` and a Courier Provider record.
		company: When provided, looks for a Courier Account matching this company.
			If ``None``, uses the first account that matches the provider.

	Raises:
		frappe.ValidationError: If no matching credentials are found or the
			provider module is not in the registry.
	"""
	if provider_code not in REGISTRY:
		frappe.throw(
			frappe._("Courier provider '{0}' is not supported.").format(provider_code),
			frappe.ValidationError,
		)

	settings = frappe.get_single("Courier Settings")
	credentials = settings.get_account(provider_code, company)

	if not credentials:
		frappe.throw(
			frappe._(
				"No Courier Account found for provider '{0}'"
				"{1}. Please configure it in Courier Settings."
			).format(provider_code, f" / company '{company}'" if company else ""),
			frappe.ValidationError,
		)

	# Dynamically import the provider module
	import importlib

	module = importlib.import_module(REGISTRY[provider_code])
	client_class = module.Client  # each module must expose a `Client` class

	return client_class(
		api_key=credentials["api_key"],
		secret_key=credentials["secret_key"],
		base_url=credentials["base_url"],
	)
