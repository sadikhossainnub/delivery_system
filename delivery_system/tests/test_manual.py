# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Unit tests for Manual Delivery Courier Client.

import unittest
from unittest.mock import MagicMock, patch

import frappe

# Provide fallback for frappe._ when running outside bench site context
if not getattr(frappe.local, "site", None):
	frappe._ = lambda msg, *args, **kwargs: msg
	frappe.logger = lambda *a, **k: MagicMock()

	def _mock_throw(msg, exc=frappe.ValidationError, *args, **kwargs):
		if isinstance(exc, type) and issubclass(exc, Exception):
			raise exc(msg)
		raise frappe.ValidationError(msg)

	frappe.throw = _mock_throw


class TestManualCourierClient(unittest.TestCase):
	"""Tests for delivery_system.couriers.manual.Client."""

	def _make_client(self):
		from delivery_system.couriers.manual import Client

		return Client()

	def test_create_order(self):
		client = self._make_client()
		order_data = {
			"invoice": "SO-2026-0001",
			"recipient_name": "Rahim Ahmed",
			"recipient_phone": "01712345678",
			"recipient_address": "Mirpur-10, Dhaka",
			"cod_amount": 1500.0,
			"delivery_type": "Home Delivery",
		}

		result = client.create_order(order_data)

		self.assertEqual(result["consignment_id"], "MAN-SO-2026-0001")
		self.assertEqual(result["tracking_code"], "MAN-SO-2026-0001")
		self.assertEqual(result["status"], "pending")
		self.assertEqual(result["raw"]["provider"], "manual")
		self.assertEqual(result["raw"]["recipient_name"], "Rahim Ahmed")

	def test_bulk_create(self):
		client = self._make_client()
		orders = [
			{"invoice": "SO-001", "recipient_name": "User 1", "cod_amount": 500},
			{"invoice": "SO-002", "recipient_name": "User 2", "cod_amount": 1000},
		]

		results = client.bulk_create(orders)

		self.assertEqual(len(results), 2)
		self.assertEqual(results[0]["consignment_id"], "MAN-SO-001")
		self.assertEqual(results[1]["consignment_id"], "MAN-SO-002")

	def test_get_balance(self):
		client = self._make_client()
		bal = client.get_balance()
		self.assertEqual(bal["current_balance"], 0.0)

	def test_ping(self):
		client = self._make_client()
		res = client.ping()
		self.assertEqual(res["status"], 200)

	def test_create_return_request(self):
		client = self._make_client()
		res = client.create_return_request("MAN-SO-001", reason="Customer unavailable")
		self.assertEqual(res["status"], "success")
		self.assertEqual(res["consignment_id"], "MAN-SO-001")

	def test_get_status_no_args_raises(self):
		client = self._make_client()
		with self.assertRaises(frappe.ValidationError):
			client.get_status()

	def test_get_status_not_found_returns_pending(self):
		client = self._make_client()
		res = client.get_status(consignment_id="MAN-999999")
		self.assertEqual(res["delivery_status"], "pending")
		self.assertEqual(res["consignment_id"], "MAN-999999")

	def test_fraud_check_empty_phone(self):
		client = self._make_client()
		res = client.fraud_check("")
		self.assertEqual(res["score"], 100)
		self.assertEqual(res["total_orders"], 0)


if __name__ == "__main__":
	unittest.main()
