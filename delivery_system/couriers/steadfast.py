# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Steadfast Courier API client (Packzy API v1)
# Docs: https://portal.packzy.com/api/v1
#
# Base URL: https://portal.packzy.com/api/v1
# Auth headers: Api-Key, Secret-Key, Content-Type: application/json
#
# All 18 endpoints implemented:
#   GET  /ping
#   POST /create_order
#   POST /create_order/bulk-order
#   POST /create_order/bulk-order/extended
#   GET  /status_by_cid/{consignment_id}
#   GET  /status_with_return_status_by_cid/{consignment_id}
#   GET  /status_by_invoice/{invoice}
#   GET  /status_by_trackingcode/{tracking_code}
#   GET  /trackings_by_invoice/{invoice}
#   POST /create_pickup_request
#   POST /create_return_request
#   GET  /get_return_requests
#   GET  /get_return_request/{id}
#   GET  /get_balance
#   GET  /payments
#   GET  /payments/{payment_id}
#   GET  /police_stations
#   GET  /fraud_check/score/{phone}

from __future__ import annotations

import json

import frappe
import requests

from delivery_system.couriers import BaseCourierClient

# Steadfast delivery type constants (API expects numeric 0/1)
DELIVERY_TYPE_HOME = 0   # Home Delivery
DELIVERY_TYPE_POINT = 1  # Point Delivery / Steadfast Hub Pick Up

# Map our internal delivery_type values → Steadfast numeric values
DELIVERY_TYPE_MAP = {
	"Home Delivery": DELIVERY_TYPE_HOME,
	"Point Delivery": DELIVERY_TYPE_POINT,
	"HD": DELIVERY_TYPE_HOME,
	"PD": DELIVERY_TYPE_POINT,
	"0": DELIVERY_TYPE_HOME,
	"1": DELIVERY_TYPE_POINT,
}

_REQUEST_TIMEOUT = 30  # seconds
_STRIP_CHARS = ("{", "}", ";", "<", ">", "$")


def _clean_text(text: str | None) -> str:
	"""Replace disallowed characters '{', '}', ';', '<', '>', '$' with spaces as specified by API spec."""
	if not text:
		return ""
	result = str(text)
	for ch in _STRIP_CHARS:
		result = result.replace(ch, " ")
	return result


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
	def _handle_response(resp: requests.Response) -> dict | list:
		"""Parse response and raise ValidationError on non-2xx."""
		try:
			data = resp.json()
		except ValueError:
			data = {"message": resp.text or "Unknown error"}

		if not resp.ok:
			error_msg = f"HTTP {resp.status_code}"
			if isinstance(data, dict):
				error_msg = (
					data.get("message")
					or data.get("error")
					or data.get("errors")
					or error_msg
				)
			elif isinstance(data, list):
				error_msg = str(data)

			if isinstance(error_msg, (dict, list)):
				error_msg = json.dumps(error_msg)
			frappe.throw(
				frappe._("Steadfast API error: {0}").format(error_msg),
				frappe.ValidationError,
			)

		return data

	@staticmethod
	def _build_order_payload(order_data: dict) -> dict:
		"""Convert our internal order_data dict to Steadfast payload format.

		Applies character limit truncation and strips disallowed characters.
		Limits per API docs:
		- invoice: max 100 chars
		- recipient_name: max 100 chars
		- recipient_phone: max 40 chars
		- recipient_address: max 490 chars
		- note: max 480 chars
		"""
		delivery_type_raw = order_data.get("delivery_type", "Home Delivery")
		# API expects numeric: 0 = Home Delivery, 1 = Point Delivery
		delivery_type = DELIVERY_TYPE_MAP.get(str(delivery_type_raw), DELIVERY_TYPE_HOME)

		invoice = _clean_text(order_data.get("invoice") or "")[:100]
		recipient_name = _clean_text(order_data.get("recipient_name") or "")[:100]
		recipient_phone = str(order_data.get("recipient_phone") or "").strip()[:40]
		recipient_address = _clean_text(order_data.get("recipient_address") or "")[:490]
		note = _clean_text(order_data.get("note") or "")[:480]

		payload = {
			"invoice": invoice,
			"recipient_name": recipient_name,
			"recipient_phone": recipient_phone,
			"recipient_address": recipient_address,
			"cod_amount": float(order_data.get("cod_amount") or 0),
			"note": note,
			"delivery_type": delivery_type,
		}
		return payload

	# ------------------------------------------------------------------
	# BaseCourierClient implementation & updated API endpoints
	# ------------------------------------------------------------------

	def ping(self) -> dict:
		"""Service check — GET /ping (No API key needed)."""
		url = f"{self.base_url}/ping"
		try:
			resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
		except requests.RequestException as exc:
			frappe.throw(
				frappe._("Network error communicating with Steadfast: {0}").format(str(exc)),
				frappe.ValidationError,
			)

		return self._handle_response(resp)

	def create_order(self, order_data: dict) -> dict:
		"""Book a single consignment with Steadfast (POST /create_order)."""
		payload = self._build_order_payload(order_data)
		response = self._post("/create_order", payload)
		if isinstance(response, list) and response:
			return self._normalise_single(response[0])
		return self._normalise_single(response if isinstance(response, dict) else {})

	def bulk_create(self, orders: list[dict]) -> list[dict]:
		"""Book up to 500 consignments in one API call (POST /create_order/bulk-order)."""
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

		if isinstance(response, list):
			raw_list = response
		elif isinstance(response, dict):
			raw_list = response.get("data") or response.get("orders") or [response]
		else:
			raw_list = []

		results = []
		for item in raw_list:
			if isinstance(item, dict):
				results.append(self._normalise_single(item))
		return results

	def bulk_create_extended(self, orders: list[dict]) -> list[dict] | dict:
		"""Book up to 500 consignments with per-field validation messages (POST /create_order/bulk-order/extended)."""
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
		return self._post("/create_order/bulk-order/extended", payload)

	def get_status(
		self,
		invoice: str | None = None,
		consignment_id: str | None = None,
		tracking_code: str | None = None,
		return_status: bool = False,
	) -> dict:
		"""Check delivery status. Provide exactly one of the three identifiers."""
		if consignment_id:
			endpoint = (
				f"/status_with_return_status_by_cid/{consignment_id}"
				if return_status
				else f"/status_by_cid/{consignment_id}"
			)
			raw = self._get(endpoint)
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

	def get_status_with_return_status(self, consignment_id: str) -> dict:
		"""GET /status_with_return_status_by_cid/{consignment_id}."""
		return self.get_status(consignment_id=consignment_id, return_status=True)

	def get_trackings_by_invoice(self, invoice: str) -> dict | list:
		"""GET /trackings_by_invoice/{invoice} — Every step a parcel has been through."""
		return self._get(f"/trackings_by_invoice/{invoice}")

	def create_pickup_request(
		self, address_id: str | int | None = None, note: str = "", **kwargs
	) -> dict:
		"""POST /create_pickup_request — Ask for a rider to collect from one of your addresses."""
		payload = {}
		if address_id is not None:
			payload["address_id"] = address_id
		if note:
			payload["note"] = _clean_text(note)[:480]
		payload.update(kwargs)
		return self._post("/create_pickup_request", payload)

	def create_return_request(self, consignment_id: str, reason: str = "") -> dict:
		"""POST /create_return_request — Initiate a return request."""
		payload = {"consignment_id": consignment_id, "reason": _clean_text(reason)[:480]}
		return self._post("/create_return_request", payload)

	def get_return_request(self, return_id: str) -> dict:
		"""GET /get_return_request/{id}."""
		return self._get(f"/get_return_request/{return_id}")

	def get_return_requests(self, page: int | None = None) -> list[dict] | dict:
		"""GET /get_return_requests — Your return requests, newest first, ten to a page."""
		params = {"page": page} if page else None
		response = self._get("/get_return_requests", params=params)
		if isinstance(response, dict):
			return response.get("data") or response
		return response

	def get_balance(self) -> dict:
		"""GET /get_balance — Return current account balance."""
		return self._get("/get_balance")

	def get_payments(
		self, page: int | None = None, date_from: str | None = None, date_to: str | None = None
	) -> list[dict] | dict:
		"""GET /payments — Payouts made to you, ten to a page."""
		params = {}
		if page:
			params["page"] = page
		if date_from:
			params["start_date"] = date_from
		if date_to:
			params["end_date"] = date_to
		response = self._get("/payments", params=params if params else None)
		if isinstance(response, dict):
			return response.get("data") or response.get("payments") or response
		elif isinstance(response, list):
			return response
		return []

	def get_payment(self, payment_id: str) -> dict:
		"""GET /payments/{payment_id} — One payout with every parcel it settled."""
		return self._get(f"/payments/{payment_id}")

	def get_police_stations(self) -> list[dict] | dict:
		"""GET /police_stations — Every thana delivered to, with its district."""
		response = self._get("/police_stations")
		if isinstance(response, dict):
			return response.get("data") or response
		return response

	def fraud_check(self, phone: str) -> dict:
		"""GET /fraud_check/score/{phone} — Customer's delivery record and score."""
		clean_phone = str(phone).strip()
		return self._get(f"/fraud_check/score/{clean_phone}")

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
		return_status = raw.get("return_status") or raw.get("return_delivery_status") or ""
		return {
			"delivery_status": str(delivery_status).lower(),
			"return_status": str(return_status).lower() if return_status else "",
			"consignment_id": str(raw.get("consignment_id") or ""),
			"tracking_code": str(raw.get("tracking_code") or ""),
			"invoice": str(raw.get("invoice") or ""),
			"raw": raw,
		}

