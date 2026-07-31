# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

import unittest
import frappe
from delivery_system.api import calculate_cod_amount, _do_send_to_courier


class TestCODAmountCalculation(unittest.TestCase):
	def test_full_advance_paid(self):
		"""When customer pays full amount in advance, COD amount should be 0."""
		doc = frappe._dict(
			{
				"doctype": "Sales Order",
				"grand_total": 1000.0,
				"advance_paid": 1000.0,
			}
		)
		self.assertEqual(calculate_cod_amount(doc), 0.0)

	def test_net_total_paid(self):
		"""When customer pays only net total in advance, COD amount should equal the remaining delivery charge."""
		doc = frappe._dict(
			{
				"doctype": "Sales Order",
				"net_total": 1000.0,
				"grand_total": 1100.0,
				"advance_paid": 1000.0,
			}
		)
		self.assertEqual(calculate_cod_amount(doc), 100.0)

	def test_partial_advance_paid(self):
		"""When customer pays partial advance payment, COD amount should be remaining balance."""
		doc = frappe._dict(
			{
				"doctype": "Sales Order",
				"grand_total": 1500.0,
				"advance_paid": 300.0,
			}
		)
		self.assertEqual(calculate_cod_amount(doc), 1200.0)

	def test_zero_advance_paid(self):
		"""When no advance is paid, COD amount should be full grand total."""
		doc = frappe._dict(
			{
				"doctype": "Sales Order",
				"grand_total": 1500.0,
				"advance_paid": 0.0,
			}
		)
		self.assertEqual(calculate_cod_amount(doc), 1500.0)

	def test_is_paid_status(self):
		"""When document is marked as paid via flag or status, COD amount should be 0."""
		doc1 = frappe._dict({"doctype": "Sales Order", "grand_total": 500.0, "is_paid": 1})
		doc2 = frappe._dict({"doctype": "Sales Order", "grand_total": 500.0, "payment_status": "Paid"})
		doc3 = frappe._dict({"doctype": "Sales Order", "grand_total": 500.0, "status": "Paid"})
		doc4 = frappe._dict({"doctype": "Sales Order", "grand_total": 500.0, "per_paid": 100.0})
		doc5 = frappe._dict({"doctype": "Sales Order", "grand_total": 500.0, "status": "Completed"})

		self.assertEqual(calculate_cod_amount(doc1), 0.0)
		self.assertEqual(calculate_cod_amount(doc2), 0.0)
		self.assertEqual(calculate_cod_amount(doc3), 0.0)
		self.assertEqual(calculate_cod_amount(doc4), 0.0)
		self.assertEqual(calculate_cod_amount(doc5), 0.0)

	def test_outstanding_amount_priority(self):
		"""When outstanding_amount is set explicitly, it takes priority."""
		doc = frappe._dict(
			{
				"doctype": "Sales Order",
				"grand_total": 2000.0,
				"outstanding_amount": 150.0,
			}
		)
		self.assertEqual(calculate_cod_amount(doc), 150.0)

		doc_zero = frappe._dict(
			{
				"doctype": "Sales Order",
				"grand_total": 2000.0,
				"outstanding_amount": 0.0,
			}
		)
		self.assertEqual(calculate_cod_amount(doc_zero), 0.0)


if __name__ == "__main__":
	unittest.main()
