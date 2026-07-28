# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Steadfast Courier API client
# Docs: https://portal.packzy.com/api/v1
#
# Base URL: https://portal.packzy.com/api/v1
# Auth headers: Api-Key, Secret-Key, Content-Type: application/json
#
# Endpoints implemented:
#   POST /create_order
#   POST /create_order/bulk-order
#   GET  /status_by_cid/{consignment_id}
#   GET  /status_by_invoice/{invoice}
#   GET  /status_by_trackingcode/{tracking_code}
#   GET  /get_balance
#   POST /create_return_request
#   GET  /get_return_request/{id}
#   GET  /get_return_requests
#   GET  /payments
#   GET  /payments/{payment_id}
#   GET  /police_stations

from __future__ import annotations

import json

import frappe
import requests

from delivery_system.couriers import BaseCourierClient

# Steadfast delivery type constants
DELIVERY_TYPE_HOME = "HD"
DELIVERY_TYPE_POINT = "PD"

# Map our internal delivery_type values → Steadfast values
DELIVERY_TYPE_MAP = {
	"Home Delivery": DELIVERY_TYPE_HOME,
	"Point Delivery": DELIVERY_TYPE_POINT,
}

_REQUEST_TIMEOUT = 30  # seconds


class Client(BaseCourierClient):
	"""Steadfast Courier API client.

	All public methods raise ``frappe.ValidationError`` on courier-side errors
	so the caller never needs to handle raw HTTP/requests exceptions.
	"""

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _headers(self) -> dict:
		return {
			"Api-Key": self.api_key,
			"Secret-Key": self.secret_key,
			"Content-Type": "application/json",
		}

	def _post(self, endpoint: str, payload: dict) -> dict:
		url = f"{self.base_url}/{endpoint.lstrip('/')}"
		try:
			resp = requests.post(url, json=payload, headers=self._headers(), timeout=_REQUEST_TIMEOUT)
		except requests.RequestException as exc:
			frappe.throw(
				frappe._("Network error communicating with Steadfast: {0}").format(str(exc)),
				frappe.ValidationError,
			)

		return self._handle_response(resp)

	def _get(self, endpoint: str, params: dict | None = None) -> dict:
		url = f"{self.base_url}/{endpoint.lstrip('/')}"
		try:
			resp = requests.get(
				url, params=params, headers=self._headers(), timeout=_REQUEST_TIMEOUT
			)
		except requests.RequestException as exc:
			frappe.throw(
				frappe._("Network error communicating with Steadfast: {0}").format(str(exc)),
				frappe.ValidationError,
			)

		return self._handle_response(resp)

	@staticmethod
	def _handle_response(resp: requests.Response) -> dict:
		"""Parse response and raise ValidationError on non-2xx."""
		try:
			data = resp.json()
		except ValueError:
			data = {"message": resp.text or "Unknown error"}

		if not resp.ok:
			error_msg = (
				data.get("message")
				or data.get("error")
				or data.get("errors")
				or f"HTTP {resp.status_code}"
			)
			if isinstance(error_msg, (dict, list)):
				error_msg = json.dumps(error_msg)
			frappe.throw(
				frappe._("Steadfast API error: {0}").format(error_msg),
				frappe.ValidationError,
			)

		return data

	@staticmethod
	def _build_order_payload(order_data: dict) -> dict:
		"""Convert our internal order_data dict to Steadfast payload format."""
		delivery_type_raw = order_data.get("delivery_type", "Home Delivery")
		delivery_type = DELIVERY_TYPE_MAP.get(delivery_type_raw, DELIVERY_TYPE_HOME)

		payload = {
			"invoice": order_data["invoice"],
			"recipient_name": order_data["recipient_name"],
			"recipient_phone": order_data["recipient_phone"],
			"recipient_address": (order_data.get("recipient_address") or "")[:250],
			"cod_amount": order_data.get("cod_amount", 0),
			"note": order_data.get("note", ""),
			"delivery_type": delivery_type,
		}
		return payload

	# ------------------------------------------------------------------
	# BaseCourierClient implementation
	# ------------------------------------------------------------------

	def create_order(self, order_data: dict) -> dict:
		"""Book a single consignment with Steadfast.

		Args:
			order_data: Must contain: invoice, recipient_name, recipient_phone,
				recipient_address, cod_amount. Optional: note, delivery_type.

		Returns:
			Dict with consignment_id, tracking_code, status (and full raw response).
		"""
		payload = self._build_order_payload(order_data)
		response = self._post("/create_order", payload)
		return self._normalise_single(response)

	def bulk_create(self, orders: list[dict]) -> list[dict]:
		"""Book up to 500 consignments in one API call.

		Steadfast returns results keyed by invoice number.
		"""
		if not orders:
			return []
		if len(orders) > 500:
			frappe.throw(
				frappe._("Steadfast bulk API supports a maximum of 500 orders per call. Got {0}.").format(
					len(orders)
				),
				frappe.ValidationError,
			)

		payload = {"data": [self._build_order_payload(o) for o in orders]}
		response = self._post("/create_order/bulk-order", payload)

		# Steadfast returns {"status": 200, "message": "...", "data": [...]}
		raw_list = response.get("data") or []
		results = []
		for item in raw_list:
			results.append(self._normalise_single(item))
		return results

	def get_status(
		self,
		invoice: str | None = None,
		consignment_id: str | None = None,
		tracking_code: str | None = None,
	) -> dict:
		"""Check delivery status. Provide exactly one of the three identifiers."""
		if consignment_id:
			raw = self._get(f"/status_by_cid/{consignment_id}")
		elif invoice:
			raw = self._get(f"/status_by_invoice/{invoice}")
		elif tracking_code:
			raw = self._get(f"/status_by_trackingcode/{tracking_code}")
		else:
			frappe.throw(
				frappe._("get_status requires consignment_id, invoice, or tracking_code."),
				frappe.ValidationError,
			)

		return self._normalise_status(raw)

	def get_balance(self) -> dict:
		"""Return current account balance."""
		return self._get("/get_balance")

	def create_return_request(self, consignment_id: str, reason: str = "") -> dict:
		"""Initiate a return / pickup request."""
		payload = {"consignment_id": consignment_id, "reason": reason}
		return self._post("/create_return_request", payload)

	def get_return_request(self, return_id: str) -> dict:
		return self._get(f"/get_return_request/{return_id}")

	def get_return_requests(self) -> list[dict]:
		response = self._get("/get_return_requests")
		return response.get("data") or response

	def get_payments(self) -> list[dict]:
		response = self._get("/payments")
		return response.get("data") or response

	def get_payment(self, payment_id: str) -> dict:
		return self._get(f"/payments/{payment_id}")

	def get_police_stations(self) -> list[dict]:
		response = self._get("/police_stations")
		return response.get("data") or response

	# ------------------------------------------------------------------
	# Response normalisation
	# ------------------------------------------------------------------

	@staticmethod
	def _normalise_single(raw: dict) -> dict:
		"""Normalise a Steadfast create_order response to our internal format."""
		consignment = raw.get("consignment") or raw
		return {
			"consignment_id": (
				str(consignment.get("consignment_id") or raw.get("consignment_id") or "")
			),
			"tracking_code": str(
				consignment.get("tracking_code") or raw.get("tracking_code") or ""
			),
			"invoice": str(consignment.get("invoice") or raw.get("invoice") or ""),
			"status": str(consignment.get("status") or raw.get("status") or "pending"),
			"raw": raw,
		}

	@staticmethod
	def _normalise_status(raw: dict) -> dict:
		"""Normalise a Steadfast status response to our internal format."""
		delivery_status = raw.get("delivery_status") or raw.get("status") or "unknown"
		return {
			"delivery_status": str(delivery_status).lower(),
			"consignment_id": str(raw.get("consignment_id") or ""),
			"tracking_code": str(raw.get("tracking_code") or ""),
			"invoice": str(raw.get("invoice") or ""),
			"raw": raw,
		}
