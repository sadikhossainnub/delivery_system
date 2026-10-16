# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt
#
# payout_import.py — Whitelisted API for the "Import Courier Payout" page.
#
# Flow:
#   1. parse_payout_file()  — decode base64 file, parse Excel/CSV/PDF,
#                             return columns + raw row dicts to the browser.
#   2. create_payouts_from_rows() — receive rows + column_map from the browser,
#                                   match Delivery Orders, create Courier Payout
#                                   records, optionally post Journal Entries.
#
# Supported file types: .xlsx, .xls, .csv, .pdf

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, nowdate, today


# ---------------------------------------------------------------------------
# Step 1: Parse the uploaded file
# ---------------------------------------------------------------------------


@frappe.whitelist()
def parse_payout_file(
	file_content_b64: str,
	file_name: str,
	file_ext: str,
	header_row: int = 1,
	sheet_name: str | None = None,
) -> dict:
	"""Decode and parse an Excel / CSV / PDF file.

	Returns:
		{
			"columns": [...],
			"rows":    [{"col_a": val, "col_b": val, ...}, ...],
			"total":   int,
		}
	"""
	frappe.only_for(["Delivery Manager", "System Manager"])

	try:
		raw_bytes = base64.b64decode(file_content_b64)
	except Exception:
		frappe.throw(_("Could not decode file content. Ensure the upload succeeded."))

	ext = (file_ext or "").lower().strip(".")

	try:
		if ext in ("xlsx", "xls"):
			return _parse_excel(raw_bytes, header_row=int(header_row or 1), sheet_name=sheet_name)
		elif ext == "csv":
			return _parse_csv(raw_bytes, header_row=int(header_row or 1))
		elif ext == "pdf":
			return _parse_pdf(raw_bytes)
		else:
			frappe.throw(_("Unsupported file type: {0}").format(ext))
	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "payout_import.parse_payout_file")
		return {"error": str(exc), "rows": [], "columns": []}


# ---------------------------------------------------------------------------
# Step 2: Create Courier Payout records from parsed rows
# ---------------------------------------------------------------------------


@frappe.whitelist()
def create_payouts_from_rows(
	rows: list | str,
	column_map: dict | str,
	courier_provider: str,
	payout_date: str | None = None,
	auto_post_payment_entry: int = 1,
	auto_post_journal_entry: int | None = None,
) -> dict:
	"""Match rows to Delivery Orders and create Courier Payout records.

	Args:
		rows:            List of row dicts from parse_payout_file.
		column_map:      Mapping of field_key -> column_name_in_file.
		courier_provider: Courier Provider document name.
		payout_date:     Defaults to today.
		auto_post_payment_entry: 1 = create Payment Entries (Customer clearing & Bank settlement).

	Returns:
		{
			"created":      int,
			"skipped":      [str, ...],
			"errors":       [str, ...],
			"payout_names": [str, ...],
		}
	"""
	frappe.only_for(["Delivery Manager", "System Manager"])

	if isinstance(rows, str):
		rows = json.loads(rows)
	if isinstance(column_map, str):
		column_map = json.loads(column_map)

	if not rows:
		frappe.throw(_("No rows to import."))
	if not courier_provider:
		frappe.throw(_("Courier Provider is required."))

	payout_date = payout_date or today()
	if auto_post_journal_entry is not None:
		do_pe = bool(int(auto_post_journal_entry or 0))
	else:
		do_pe = bool(int(auto_post_payment_entry or 0))

	created = 0
	skipped = []
	errors = []
	payout_names = []

	# --- Group rows by payment_id (if mapped), otherwise treat each row separately ---
	payment_id_col = column_map.get("payment_id")

	# Try to find a unique payment_id in the file (Steadfast batches everything under one payment)
	all_payment_ids = set()
	if payment_id_col:
		all_payment_ids = {str(r.get(payment_id_col) or "").strip() for r in rows if r.get(payment_id_col)}

	if all_payment_ids and len(all_payment_ids) == 1:
		# Single batch payout (typical Steadfast statement)
		payment_id = all_payment_ids.pop()
		result = _process_batch(
			rows=rows,
			column_map=column_map,
			courier_provider=courier_provider,
			payment_id=payment_id,
			payout_date=payout_date,
			do_pe=do_pe,
		)
		if result.get("payout_name"):
			created += 1
			payout_names.append(result["payout_name"])
		skipped.extend(result.get("skipped", []))
		errors.extend(result.get("errors", []))

	elif all_payment_ids and len(all_payment_ids) > 1:
		# Multiple payment batches in the same file
		from itertools import groupby

		sorted_rows = sorted(rows, key=lambda r: str(r.get(payment_id_col) or ""))
		for pid, group in groupby(sorted_rows, key=lambda r: str(r.get(payment_id_col) or "")):
			group_rows = list(group)
			result = _process_batch(
				rows=group_rows,
				column_map=column_map,
				courier_provider=courier_provider,
				payment_id=pid or _generate_payment_id(courier_provider, payout_date),
				payout_date=payout_date,
				do_pe=do_pe,
			)
			if result.get("payout_name"):
				created += 1
				payout_names.append(result["payout_name"])
			skipped.extend(result.get("skipped", []))
			errors.extend(result.get("errors", []))
	else:
		# No payment_id column — treat all rows as one payout
		payment_id = _generate_payment_id(courier_provider, payout_date)
		result = _process_batch(
			rows=rows,
			column_map=column_map,
			courier_provider=courier_provider,
			payment_id=payment_id,
			payout_date=payout_date,
			do_pe=do_pe,
		)
		if result.get("payout_name"):
			created += 1
			payout_names.append(result["payout_name"])
		skipped.extend(result.get("skipped", []))
		errors.extend(result.get("errors", []))

	frappe.db.commit()

	return {
		"created": created,
		"skipped": skipped,
		"errors": errors,
		"payout_names": payout_names,
	}


# ---------------------------------------------------------------------------
# Internal batch processor
# ---------------------------------------------------------------------------


def _process_batch(
	rows: list[dict],
	column_map: dict,
	courier_provider: str,
	payment_id: str,
	payout_date: str,
	do_pe: bool,
) -> dict:
	"""Process one payment batch: match rows → create Courier Payout."""

	skipped = []
	errors = []

	# --- Deduplicate: skip if this payment_id already imported ---
	if frappe.db.exists("Courier Payout", {"payment_id": payment_id}):
		return {
			"payout_name": None,
			"skipped": [f"Payment ID '{payment_id}' already imported — skipped entire batch."],
			"errors": [],
		}

	matched_orders = []  # [{delivery_order, cod_amount, charge, net}, ...]
	gross_total = 0.0
	charge_total = 0.0
	net_total = 0.0

	cid_col = column_map.get("consignment_id")
	inv_col = column_map.get("invoice")
	tc_col = column_map.get("tracking_code")
	cod_col = column_map.get("cod_amount")
	charge_col = column_map.get("delivery_charge")
	net_col = column_map.get("net_amount")
	status_col = column_map.get("status")

	for idx, row in enumerate(rows, start=1):
		cid = _cell(row, cid_col)
		inv = _cell(row, inv_col)
		tc = _cell(row, tc_col)
		cod = flt(_cell(row, cod_col))
		charge = flt(_cell(row, charge_col))
		net = flt(_cell(row, net_col))
		new_status = (_cell(row, status_col) or "").lower() or None

		# --- Find Delivery Order ---
		do_name = _find_delivery_order(cid, inv, tc)

		if not do_name:
			skipped.append(
				f"Row {idx}: No Delivery Order found for "
				f"consignment_id={cid!r} invoice={inv!r} tracking_code={tc!r}"
			)
			# Still count financials for the batch totals
			gross_total += cod
			charge_total += charge
			net_total += net or (cod - charge)
			continue

		# Update delivery status if provided and different
		if new_status:
			try:
				_update_delivery_status(do_name, new_status)
			except Exception:
				pass  # non-fatal

		gross_total += cod
		charge_total += charge
		net_total += net or (cod - charge)

		matched_orders.append(
			{
				"name": do_name,
				"cod_amount": cod,
				"charge": charge,
				"net": net or (cod - charge),
			}
		)

	# --- Create Courier Payout record ---
	try:
		payout_doc = frappe.get_doc(
			{
				"doctype": "Courier Payout",
				"courier_provider": courier_provider,
				"payment_id": payment_id,
				"payout_date": payout_date,
				"gross_amount": gross_total,
				"delivery_charges_deducted": charge_total,
				"net_amount": net_total if net_total else (gross_total - charge_total),
				"reconciliation_status": "Complete" if matched_orders else "Partial",
				"raw_response": json.dumps(
					{"source": "file_import", "rows": len(rows), "matched": len(matched_orders)},
					ensure_ascii=False,
				),
			}
		)

	# --- Optional: auto-post Payment Entries (Customer clearing & Bank settlement) ---
		settlement_pe_name = None
		if do_pe:
			from delivery_system.accounting import post_clearing_entry, post_payout_entries

			# 1. Ensure clearing Payment Entry (Customer -> Clearing Account) is posted and applied to Sales Invoice
			for mo in matched_orders:
				try:
					do_doc = frappe.get_doc("Delivery Order", mo["name"])
					post_clearing_entry(do_doc, auto_create_invoice=True)
				except Exception as exc:
					errors.append(f"Order {mo['name']}: failed to post invoice payment: {exc}")
					frappe.log_error(frappe.get_traceback(), "payout_import.auto_clearing_pe")

			# 2. Post Bank settlement Payment Entry (Internal Transfer: Clearing -> Bank)
			try:
				do_docs = [frappe.get_doc("Delivery Order", mo["name"]) for mo in matched_orders]
				payout_data = {
					"payment_id": payment_id,
					"payment_date": payout_date,
					"gross_amount": gross_total,
					"charge_amount": charge_total,
					"net_amount": net_total,
					"courier_provider": courier_provider,
				}
				pe_result = post_payout_entries(payout_data, do_docs)
				settlement_pe_name = (
					pe_result.get("payout_payment_entry") or pe_result.get("payout_journal_entry")
				)
			except Exception as exc:
				errors.append(f"Courier Payout {payout_doc.name} created but Payment Entry failed: {exc}")
				frappe.log_error(frappe.get_traceback(), "payout_import.auto_pe")

		# Linked Delivery Orders child table
		for mo in matched_orders:
			do_doc = frappe.get_doc("Delivery Order", mo["name"])
			clearing_pe = getattr(do_doc, "clearing_journal_entry", None)
			payout_doc.append(
				"linked_journal_entries",
				{
					"delivery_order": mo["name"],
					"amount": mo["cod_amount"],
					"payment_entry": clearing_pe or settlement_pe_name,
					"journal_entry": clearing_pe or settlement_pe_name,
				},
			)

		if settlement_pe_name:
			payout_doc.linked_payment_entry = settlement_pe_name

		payout_doc.insert(ignore_permissions=True)

		# Mark delivery orders as reconciled
		for mo in matched_orders:
			frappe.db.set_value(
				"Delivery Order",
				mo["name"],
				{
					"payment_reconciled": 1,
					"reconciled_payment_id": payment_id,
				},
			)

		return {
			"payout_name": payout_doc.name,
			"skipped": skipped,
			"errors": errors,
		}

	except frappe.ValidationError:
		raise
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "payout_import._process_batch")
		errors.append(f"Failed to create Courier Payout: {exc}")
		return {"payout_name": None, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# File parsers
# ---------------------------------------------------------------------------


def _parse_excel(raw_bytes: bytes, header_row: int = 1, sheet_name: str | None = None) -> dict:
	"""Parse .xlsx or .xls using openpyxl (xlsx) or xlrd (xls)."""
	try:
		import openpyxl
	except ImportError:
		frappe.throw(
			_("openpyxl is required to read Excel files. Run: bench pip install openpyxl")
		)

	wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)

	if sheet_name and sheet_name in wb.sheetnames:
		ws = wb[sheet_name]
	else:
		ws = wb.active

	all_rows = list(ws.iter_rows(values_only=True))
	wb.close()

	if not all_rows:
		frappe.throw(_("The Excel file appears to be empty."))

	header_idx = header_row - 1  # 0-based
	if header_idx >= len(all_rows):
		frappe.throw(_("Header row {0} does not exist in the file.").format(header_row))

	raw_headers = all_rows[header_idx]
	columns = [str(h).strip() if h is not None else f"Col_{i}" for i, h in enumerate(raw_headers)]

	rows = []
	for raw_row in all_rows[header_idx + 1 :]:
		if all(v is None or str(v).strip() == "" for v in raw_row):
			continue  # skip blank rows
		row_dict = {}
		for i, col in enumerate(columns):
			val = raw_row[i] if i < len(raw_row) else None
			row_dict[col] = str(val).strip() if val is not None else ""
		rows.append(row_dict)

	return {"columns": columns, "rows": rows, "total": len(rows)}


def _parse_csv(raw_bytes: bytes, header_row: int = 1) -> dict:
	"""Parse .csv file. Tries UTF-8, falls back to latin-1."""
	import csv

	for encoding in ("utf-8-sig", "utf-8", "latin-1"):
		try:
			text = raw_bytes.decode(encoding)
			break
		except UnicodeDecodeError:
			continue
	else:
		frappe.throw(_("Could not decode CSV file. Ensure it is UTF-8 or latin-1 encoded."))

	reader = csv.reader(io.StringIO(text))
	all_rows_raw = list(reader)

	if not all_rows_raw:
		frappe.throw(_("CSV file is empty."))

	header_idx = header_row - 1
	if header_idx >= len(all_rows_raw):
		frappe.throw(_("Header row {0} does not exist.").format(header_row))

	columns = [h.strip() or f"Col_{i}" for i, h in enumerate(all_rows_raw[header_idx])]

	rows = []
	for raw_row in all_rows_raw[header_idx + 1 :]:
		if all(v.strip() == "" for v in raw_row):
			continue
		row_dict = {}
		for i, col in enumerate(columns):
			row_dict[col] = raw_row[i].strip() if i < len(raw_row) else ""
		rows.append(row_dict)

	return {"columns": columns, "rows": rows, "total": len(rows)}


def _parse_pdf(raw_bytes: bytes) -> dict:
	"""Parse a PDF payout statement using pdfplumber.

	Extracts the largest table found across all pages.
	Falls back to line-by-line text extraction if no table is found.
	"""
	try:
		import pdfplumber
	except ImportError:
		frappe.throw(
			_(
				"pdfplumber is required to read PDF files. "
				"Run: bench pip install pdfplumber"
			)
		)

	all_table_rows: list[list] = []
	header: list[str] = []

	with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
		for page in pdf.pages:
			tables = page.extract_tables()
			for table in tables:
				if not table:
					continue
				if not header:
					# First non-empty row is the header
					header = [str(c).strip() if c else f"Col_{i}" for i, c in enumerate(table[0])]
					data_start = 1
				else:
					data_start = 0

				for row in table[data_start:]:
					if row and any(c for c in row if c and str(c).strip()):
						all_table_rows.append(row)

	if not header and not all_table_rows:
		# Fallback: try text extraction with regex for tabular data
		return _parse_pdf_text_fallback(raw_bytes)

	if not header:
		frappe.throw(_("Could not extract a table from the PDF. Try converting to Excel or CSV."))

	rows = []
	for raw_row in all_table_rows:
		row_dict = {}
		for i, col in enumerate(header):
			val = raw_row[i] if i < len(raw_row) else None
			row_dict[col] = str(val).strip() if val is not None else ""
		rows.append(row_dict)

	return {"columns": header, "rows": rows, "total": len(rows)}


def _parse_pdf_text_fallback(raw_bytes: bytes) -> dict:
	"""Last-resort PDF text parser: splits lines and tokenises by whitespace."""
	import pdfplumber

	lines = []
	with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
		for page in pdf.pages:
			text = page.extract_text() or ""
			lines.extend(text.splitlines())

	# Collapse blank lines
	non_blank = [l.strip() for l in lines if l.strip()]
	if not non_blank:
		frappe.throw(_("No text found in the PDF."))

	# Use the first line as a pseudo-header if it looks tabular (multiple tokens)
	header_line = non_blank[0]
	columns = re.split(r"\s{2,}", header_line)
	if len(columns) < 2:
		columns = header_line.split()

	rows = []
	for line in non_blank[1:]:
		tokens = re.split(r"\s{2,}", line)
		if len(tokens) < 2:
			tokens = line.split()
		row_dict = {columns[i]: (tokens[i] if i < len(tokens) else "") for i in range(len(columns))}
		rows.append(row_dict)

	return {"columns": columns, "rows": rows, "total": len(rows)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cell(row: dict, col: str | None) -> str:
	"""Safe cell reader."""
	if not col:
		return ""
	return str(row.get(col) or "").strip()


def _find_delivery_order(
	consignment_id: str, invoice: str, tracking_code: str
) -> str | None:
	"""Find submitted Delivery Order by any of the three identifiers."""
	filters_list = []
	if consignment_id:
		filters_list.append({"consignment_id": consignment_id, "docstatus": 1})
	if invoice:
		filters_list.append({"invoice_reference": invoice, "docstatus": 1})
	if tracking_code:
		filters_list.append({"tracking_code": tracking_code, "docstatus": 1})

	for flt_dict in filters_list:
		name = frappe.db.get_value("Delivery Order", flt_dict, "name")
		if name:
			return name
	return None


def _update_delivery_status(do_name: str, new_status: str):
	"""Update delivery_status field on Delivery Order (non-fatal helper)."""
	allowed = [
		"pending", "delivered", "partial_delivered", "cancelled",
		"hold", "exceptional", "unknown", "in_review",
	]
	if new_status.lower() not in allowed:
		return
	current = frappe.db.get_value("Delivery Order", do_name, "delivery_status")
	if current != new_status:
		frappe.db.set_value("Delivery Order", do_name, {
			"delivery_status": new_status,
			"last_synced_on": frappe.utils.now_datetime(),
		})


def _generate_payment_id(courier_provider: str, payout_date: str) -> str:
	"""Generate a unique payment_id when the file doesn't contain one."""
	prefix = (courier_provider or "IMP").upper()[:8].replace(" ", "")
	ts = frappe.utils.now_datetime().strftime("%Y%m%d%H%M%S")
	return f"{prefix}-{payout_date}-{ts}"

