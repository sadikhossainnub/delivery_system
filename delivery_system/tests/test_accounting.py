# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# Unit tests for Delivery System Accounting Integration.
# Uses unittest.mock to test clearing entries, payout logs, variance, and reversals.

import json
import unittest
from unittest.mock import MagicMock, patch

import frappe

# Provide fallback for frappe when running outside bench site context
if not getattr(frappe.local, "site", None):
	frappe._ = lambda msg, *args, **kwargs: msg
	frappe.logger = lambda *a, **k: MagicMock()

	def _mock_throw(msg, exc=frappe.ValidationError, *args, **kwargs):
		if isinstance(exc, type) and issubclass(exc, Exception):
			raise exc(msg)
		raise frappe.ValidationError(msg)

	frappe.throw = _mock_throw

	# Mock frappe.db & defaults
	frappe.db = MagicMock()
	frappe.defaults = MagicMock()
	frappe.defaults.get_user_default.return_value = "Test Company"
	frappe.get_cached_value = lambda *a, **k: "TC"

import frappe.tests


class TestAccountingIntegration(unittest.TestCase):
	"""Tests for delivery_system.accounting module."""

	def _make_delivery_order(self, name="DS-2026-00001", cod_amount=1000):
		doc = MagicMock()
		doc.name = name
		doc.consignment_id = "CID123"
		doc.cod_amount = cod_amount
		doc.reference_doctype = "Sales Order"
		doc.reference_name = "SO-00001"
		doc.clearing_entry_posted = 0
		doc.clearing_journal_entry = None
		doc.reversal_journal_entry = None
		return doc

	@patch("delivery_system.accounting.frappe.db.get_single_value")
	@patch("delivery_system.accounting.frappe.get_single")
	def test_accounting_settings_fetch(self, mock_get_single, mock_get_single_value):
		from delivery_system.accounting import get_accounting_settings

		mock_settings = MagicMock()
		mock_settings.enable_accounting_automation = 1
		mock_settings.variance_threshold_auto_post = 50.0
		mock_settings.courier_accounts = []
		mock_get_single.return_value = mock_settings

		config = get_accounting_settings("Test Company")
		self.assertTrue(config["enabled"])
		self.assertEqual(config["threshold"], 50.0)

	@patch("delivery_system.accounting._append_log")
	@patch("delivery_system.accounting._get_customer_and_receivable_account")
	@patch("delivery_system.accounting.get_accounting_settings")
	@patch("delivery_system.accounting.frappe.get_doc")
	@patch("delivery_system.accounting.frappe.db.set_value")
	@patch("delivery_system.accounting.frappe.db.savepoint")
	def test_post_clearing_entry_success(
		self, mock_sp, mock_set_val, mock_get_doc, mock_settings, mock_cust_acc, mock_log
	):
		from delivery_system.accounting import post_clearing_entry

		mock_settings.return_value = {
			"enabled": True,
			"clearing_account": "Steadfast Clearing Account - TC",
			"threshold": 50.0,
		}
		mock_cust_acc.return_value = ("CUST-001", "Debtors - TC")

		mock_je = MagicMock()
		mock_je.name = "ACC-JV-2026-00001"
		mock_get_doc.return_value = mock_je

		do = self._make_delivery_order()
		result = post_clearing_entry(do)

		self.assertEqual(result, "ACC-JV-2026-00001")
		mock_je.insert.assert_called_once()
		mock_je.submit.assert_called_once()
		mock_set_val.assert_called_once_with(
			"Delivery Order",
			"DS-2026-00001",
			{"clearing_entry_posted": 1, "clearing_journal_entry": "ACC-JV-2026-00001"},
		)

	@patch("delivery_system.accounting.get_accounting_settings")
	def test_post_clearing_entry_disabled_skips(self, mock_settings):
		from delivery_system.accounting import post_clearing_entry

		mock_settings.return_value = {"enabled": False}
		do = self._make_delivery_order()

		result = post_clearing_entry(do)
		self.assertIsNone(result)

	@patch("delivery_system.accounting.get_accounting_settings")
	def test_post_variance_over_threshold_skips(self, mock_settings):
		from delivery_system.accounting import post_variance_entry

		mock_settings.return_value = {
			"enabled": True,
			"threshold": 50.0,
			"clearing_account": "Clearing - TC",
			"variance_account": "Variance - TC",
		}
		do = self._make_delivery_order()

		# Variance of 500 exceeds 50 threshold
		result = post_variance_entry(do, 500.0)
		self.assertIsNone(result)

	@patch("delivery_system.accounting._append_log")
	@patch("delivery_system.accounting.get_accounting_settings")
	@patch("delivery_system.accounting.frappe.get_doc")
	def test_post_variance_within_threshold(self, mock_get_doc, mock_settings, mock_log):
		from delivery_system.accounting import post_variance_entry

		mock_settings.return_value = {
			"enabled": True,
			"threshold": 50.0,
			"clearing_account": "Clearing - TC",
			"variance_account": "Variance - TC",
		}
		mock_je = MagicMock()
		mock_je.name = "ACC-JV-VAR-001"
		mock_get_doc.return_value = mock_je

		do = self._make_delivery_order()

		# Variance of 15 is within 50 threshold
		result = post_variance_entry(do, 15.0)
		self.assertEqual(result, "ACC-JV-VAR-001")
		mock_je.submit.assert_called_once()

	@patch("delivery_system.accounting.frappe.db.exists")
	@patch("delivery_system.accounting.frappe.get_doc")
	@patch("delivery_system.accounting.frappe.db.set_value")
	def test_post_payout_entries(self, mock_set_val, mock_get_doc, mock_exists):
		from delivery_system.accounting import post_payout_entries

		mock_exists.return_value = False
		mock_log_doc = MagicMock()
		mock_log_doc.name = "CPL-2026-00001"
		mock_get_doc.return_value = mock_log_doc

		do = self._make_delivery_order()
		payout_data = {
			"payment_id": "PAY100",
			"gross_amount": 1000,
			"charge_amount": 60,
			"payment_date": "2026-07-28",
		}

		res = post_payout_entries(payout_data, [do])
		self.assertTrue(res["success"])
		self.assertEqual(res["payment_id"], "PAY100")
		mock_set_val.assert_called_once_with(
			"Delivery Order", "DS-2026-00001", {"payment_reconciled": 1, "reconciled_payment_id": "PAY100"}
		)


if __name__ == "__main__":
	unittest.main()
