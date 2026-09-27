# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Unit tests for the Steadfast courier client and Delivery Order validations.
# Uses unittest.mock to avoid hitting the real Steadfast API.

import json
import re
import unittest
from unittest.mock import MagicMock, patch

import frappe

# Provide fallback for frappe._ and frappe.throw when running outside bench site context
if not getattr(frappe.local, "site", None):
	frappe._ = lambda msg, *args, **kwargs: msg
	frappe.logger = lambda *a, **k: MagicMock()

	def _mock_throw(msg, exc=frappe.ValidationError, *args, **kwargs):
		if isinstance(exc, type) and issubclass(exc, Exception):
			raise exc(msg)
		raise frappe.ValidationError(msg)

	frappe.throw = _mock_throw

import frappe.tests





class TestSteadfastClient(unittest.TestCase):
	"""Tests for delivery_system.couriers.steadfast.Client."""

	def _make_client(self):
		from delivery_system.couriers.steadfast import Client

		return Client(
			api_key="test_api_key",
			secret_key="test_secret_key",
			base_url="https://portal.packzy.com/api/v1",
		)

	# ------------------------------------------------------------------
	# Phone validation (done in Delivery Order controller, tested here
	# via the shared regex to keep tests framework-independent)
	# ------------------------------------------------------------------

	def test_valid_bd_phone(self):
		BD_PHONE_REGEX = re.compile(r"^01[3-9]\d{8}$")
		valid_phones = ["01712345678", "01912345678", "01812345678", "01312345678"]
		for p in valid_phones:
			self.assertIsNotNone(BD_PHONE_REGEX.match(p), f"Expected {p!r} to be valid")

	def test_invalid_bd_phone(self):
		BD_PHONE_REGEX = re.compile(r"^01[3-9]\d{8}$")
		invalid_phones = [
			"017123456",   # too short
			"019123456789",  # too long
			"01112345678",  # starts with 011 (not valid)
			"00712345678",  # starts with 007
			"abcdefghijk",  # non-numeric
			"",
		]
		for p in invalid_phones:
			self.assertIsNone(BD_PHONE_REGEX.match(p), f"Expected {p!r} to be invalid")

	# ------------------------------------------------------------------
	# Address truncation
	# ------------------------------------------------------------------

	def test_address_truncation(self):
		from delivery_system.couriers.steadfast import Client

		c = self._make_client()
		long_address = "A" * 600
		order_data = {
			"invoice": "INV-001",
			"recipient_name": "Test",
			"recipient_phone": "01712345678",
			"recipient_address": long_address,
			"cod_amount": 500,
		}
		payload = c._build_order_payload(order_data)
		self.assertEqual(len(payload["recipient_address"]), 490)

	def test_address_within_limit_unchanged(self):
		from delivery_system.couriers.steadfast import Client

		c = self._make_client()
		short_address = "Dhaka, Bangladesh"
		order_data = {
			"invoice": "INV-002",
			"recipient_name": "Test",
			"recipient_phone": "01712345678",
			"recipient_address": short_address,
			"cod_amount": 100,
		}
		payload = c._build_order_payload(order_data)
		self.assertEqual(payload["recipient_address"], short_address)

	# ------------------------------------------------------------------
	# create_order — mocked HTTP
	# ------------------------------------------------------------------

	@patch("delivery_system.couriers.steadfast.requests.post")
	def test_create_order_success(self, mock_post):
		from delivery_system.couriers.steadfast import Client

		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {
			"status": 200,
			"consignment": {
				"consignment_id": "CID123",
				"tracking_code": "TRK456",
				"invoice": "INV-001",
				"status": "pending",
			},
		}
		mock_post.return_value = mock_response

		c = self._make_client()
		result = c.create_order(
			{
				"invoice": "INV-001",
				"recipient_name": "John Doe",
				"recipient_phone": "01712345678",
				"recipient_address": "123 Dhaka",
				"cod_amount": 500,
			}
		)

		self.assertEqual(result["consignment_id"], "CID123")
		self.assertEqual(result["tracking_code"], "TRK456")
		mock_post.assert_called_once()

	@patch("delivery_system.couriers.steadfast.requests.post")
	def test_create_order_api_error_raises_validation(self, mock_post):
		"""Non-200 response must raise frappe.ValidationError, not raw HTTPError."""
		from delivery_system.couriers.steadfast import Client

		mock_response = MagicMock()
		mock_response.ok = False
		mock_response.status_code = 422
		mock_response.json.return_value = {"message": "Invalid phone number"}
		mock_post.return_value = mock_response

		c = self._make_client()
		with self.assertRaises(frappe.ValidationError) as ctx:
			c.create_order(
				{
					"invoice": "INV-ERR",
					"recipient_name": "Jane",
					"recipient_phone": "01712345678",
					"recipient_address": "Chittagong",
					"cod_amount": 0,
				}
			)
		self.assertIn("Invalid phone number", str(ctx.exception))

	# ------------------------------------------------------------------
	# get_status — mocked HTTP
	# ------------------------------------------------------------------

	@patch("delivery_system.couriers.steadfast.requests.get")
	def test_get_status_by_consignment_id(self, mock_get):
		from delivery_system.couriers.steadfast import Client

		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {
			"consignment_id": "CID123",
			"delivery_status": "delivered",
			"tracking_code": "TRK456",
		}
		mock_get.return_value = mock_response

		c = self._make_client()
		result = c.get_status(consignment_id="CID123")

		self.assertEqual(result["delivery_status"], "delivered")
		called_url = mock_get.call_args[0][0]
		self.assertIn("/status_by_cid/CID123", called_url)

	@patch("delivery_system.couriers.steadfast.requests.get")
	def test_get_status_by_invoice(self, mock_get):
		from delivery_system.couriers.steadfast import Client

		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {"delivery_status": "cancelled"}
		mock_get.return_value = mock_response

		c = self._make_client()
		result = c.get_status(invoice="INV-001")

		self.assertEqual(result["delivery_status"], "cancelled")
		called_url = mock_get.call_args[0][0]
		self.assertIn("/status_by_invoice/INV-001", called_url)

	def test_get_status_no_identifier_raises(self):
		"""Calling get_status with no identifier must raise ValidationError."""
		from delivery_system.couriers.steadfast import Client

		c = self._make_client()
		with self.assertRaises(frappe.ValidationError):
			c.get_status()

	# ------------------------------------------------------------------
	# bulk_create — mocked HTTP
	# ------------------------------------------------------------------

	@patch("delivery_system.couriers.steadfast.requests.post")
	def test_bulk_create_success(self, mock_post):
		from delivery_system.couriers.steadfast import Client

		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {
			"status": 200,
			"data": [
				{"consignment_id": "CID001", "tracking_code": "TRK001", "invoice": "INV-001", "status": "pending"},
				{"consignment_id": "CID002", "tracking_code": "TRK002", "invoice": "INV-002", "status": "pending"},
			],
		}
		mock_post.return_value = mock_response

		c = self._make_client()
		orders = [
			{"invoice": "INV-001", "recipient_name": "A", "recipient_phone": "01712345678", "recipient_address": "Dhaka", "cod_amount": 100},
			{"invoice": "INV-002", "recipient_name": "B", "recipient_phone": "01812345678", "recipient_address": "Ctg", "cod_amount": 200},
		]
		results = c.bulk_create(orders)

		self.assertEqual(len(results), 2)
		self.assertEqual(results[0]["consignment_id"], "CID001")
		self.assertEqual(results[1]["consignment_id"], "CID002")

	def test_bulk_create_over_limit_raises(self):
		from delivery_system.couriers.steadfast import Client

		c = self._make_client()
		orders = [{"invoice": f"INV-{i}"} for i in range(501)]
		with self.assertRaises(frappe.ValidationError):
			c.bulk_create(orders)

	# ------------------------------------------------------------------
	# Delivery type mapping
	# ------------------------------------------------------------------

	def test_delivery_type_home_mapping(self):
		from delivery_system.couriers.steadfast import Client

		c = self._make_client()
		payload = c._build_order_payload(
			{
				"invoice": "X",
				"recipient_name": "X",
				"recipient_phone": "01712345678",
				"recipient_address": "X",
				"delivery_type": "Home Delivery",
			}
		)
		self.assertEqual(payload["delivery_type"], 0)  # Steadfast API: 0 = Home Delivery

	def test_delivery_type_point_mapping(self):
		from delivery_system.couriers.steadfast import Client

		c = self._make_client()
		payload = c._build_order_payload(
			{
				"invoice": "X",
				"recipient_name": "X",
				"recipient_phone": "01712345678",
				"recipient_address": "X",
				"delivery_type": "Point Delivery",
			}
		)
		self.assertEqual(payload["delivery_type"], 1)  # Steadfast API: 1 = Point Delivery

	@patch("delivery_system.couriers.steadfast.requests.get")
	def test_get_payments(self, mock_get):
		from delivery_system.couriers.steadfast import Client

		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {
			"status": 200,
			"data": [
				{"consignment_id": "CID100", "payment_id": "PAY001", "amount": 1200},
			],
		}
		mock_get.return_value = mock_response

		c = self._make_client()
		payments = c.get_payments(date_from="2026-07-01", date_to="2026-07-28")

		self.assertEqual(len(payments), 1)
		self.assertEqual(payments[0]["payment_id"], "PAY001")

	def test_extract_charge_from_raw_response(self):
		from delivery_system.delivery_system.report.delivery_charge_vs_revenue.delivery_charge_vs_revenue import (
			extract_charge_from_raw_response,
		)

		raw = json.dumps({"consignment": {"delivery_charge": 80.0}})
		charge = extract_charge_from_raw_response(raw)
		self.assertEqual(charge, 80.0)

	@patch("delivery_system.delivery_system.report.delivery_charge_vs_revenue.delivery_charge_vs_revenue.fetch_delivery_charges_from_api")
	def test_delivery_charge_vs_revenue_report_data(self, mock_fetch_api):
		from delivery_system.delivery_system.report.delivery_charge_vs_revenue.delivery_charge_vs_revenue import (
			get_data,
		)

		mock_db = MagicMock()
		main_rows = [
			{
				"delivery_order": "DS-2026-00001",
				"reference_doctype": "Sales Order",
				"reference_name": "SO-001",
				"invoice_amount": 1000.0,
				"total_amount": 1000.0,
				"consignment_id": "CID100",
				"invoice_reference": "INV001",
				"courier_provider": "Steadfast",
				"delivery_status": "delivered",
				"raw_response": None,
			}
		]
		mock_db.sql.side_effect = lambda query, *args, **kwargs: main_rows if "FROM `tabDelivery Order`" in query else []
		mock_db.get_value.return_value = {
			"total_taxes_and_charges": 50.0,
			"total_net_weight": 1.5,
			"grand_total": 1000.0,
		}

		with patch.object(frappe, "db", mock_db):
			mock_fetch_api.return_value = {"CID100": {"charge": 75.0, "weight": 1.5}}
			rows = get_data({})
			self.assertEqual(len(rows), 1)
			self.assertEqual(rows[0]["sales_order"], "SO-001")
			self.assertEqual(rows[0]["courier_provider"], "Steadfast")
			self.assertEqual(rows[0]["consignment_id"], "CID100")
			self.assertEqual(rows[0]["total_amount"], 1000.0)
			self.assertEqual(rows[0]["total_taxes_and_charges"], 50.0)
			self.assertEqual(rows[0]["weight"], 1.5)
			self.assertEqual(rows[0]["delivery_charge"], 75.0)
			self.assertEqual(rows[0]["cod_collection_fee"], 10.0)
			self.assertEqual(rows[0]["net_margin"], 915.0)

	def test_text_sanitization(self):
		from delivery_system.couriers.steadfast import Client, _clean_text

		cleaned = _clean_text("Address {with} <disallowed> ; $ chars")
		self.assertEqual(cleaned, "Address  with   disallowed      chars")

	@patch("delivery_system.couriers.steadfast.requests.get")
	def test_ping_success(self, mock_get):
		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {"status": 200, "message": "Pong!"}
		mock_get.return_value = mock_response

		c = self._make_client()
		res = c.ping()
		self.assertEqual(res["message"], "Pong!")
		called_url = mock_get.call_args[0][0]
		self.assertEqual(called_url, "https://portal.packzy.com/api/v1/ping")

	@patch("delivery_system.couriers.steadfast.requests.post")
	def test_bulk_create_extended(self, mock_post):
		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {"status": 200, "data": [{"invoice": "INV-001", "status": "created"}]}
		mock_post.return_value = mock_response

		c = self._make_client()
		orders = [{"invoice": "INV-001", "recipient_name": "User", "recipient_phone": "01712345678", "recipient_address": "Dhaka"}]
		res = c.bulk_create_extended(orders)
		self.assertEqual(res["status"], 200)
		called_url = mock_post.call_args[0][0]
		self.assertIn("/create_order/bulk-order/extended", called_url)

	@patch("delivery_system.couriers.steadfast.requests.get")
	def test_get_status_with_return_status(self, mock_get):
		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {
			"consignment_id": "CID999",
			"delivery_status": "cancelled",
			"return_status": "cancelled_return_rider_assigned",
		}
		mock_get.return_value = mock_response

		c = self._make_client()
		res = c.get_status_with_return_status("CID999")
		self.assertEqual(res["delivery_status"], "cancelled")
		self.assertEqual(res["return_status"], "cancelled_return_rider_assigned")
		called_url = mock_get.call_args[0][0]
		self.assertIn("/status_with_return_status_by_cid/CID999", called_url)

	@patch("delivery_system.couriers.steadfast.requests.get")
	def test_get_trackings_by_invoice(self, mock_get):
		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {"status": 200, "trackings": [{"status": "in_review"}, {"status": "delivered"}]}
		mock_get.return_value = mock_response

		c = self._make_client()
		res = c.get_trackings_by_invoice("INV-789")
		self.assertEqual(res["status"], 200)
		called_url = mock_get.call_args[0][0]
		self.assertIn("/trackings_by_invoice/INV-789", called_url)

	@patch("delivery_system.couriers.steadfast.requests.post")
	def test_create_pickup_request(self, mock_post):
		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {"status": 200, "message": "Pickup requested"}
		mock_post.return_value = mock_response

		c = self._make_client()
		res = c.create_pickup_request(address_id="123", note="Pickup 5 parcels")
		self.assertEqual(res["status"], 200)
		called_url = mock_post.call_args[0][0]
		self.assertIn("/create_pickup_request", called_url)

	@patch("delivery_system.couriers.steadfast.requests.get")
	def test_fraud_check(self, mock_get):
		mock_response = MagicMock()
		mock_response.ok = True
		mock_response.json.return_value = {"status": 200, "score": 95, "total_delivered": 10}
		mock_get.return_value = mock_response

		c = self._make_client()
		res = c.fraud_check("01712345678")
		self.assertEqual(res["score"], 95)
		called_url = mock_get.call_args[0][0]
		self.assertIn("/fraud_check/score/01712345678", called_url)


if __name__ == "__main__":
	unittest.main()



