import json

import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"fieldname": "delivery_order",
			"label": _("Delivery Order"),
			"fieldtype": "Link",
			"options": "Delivery Order",
			"width": 140,
		},
		{
			"fieldname": "sales_order",
			"label": _("Sales Order"),
			"fieldtype": "Link",
			"options": "Sales Order",
			"width": 140,
		},
		{
			"fieldname": "delivery_note",
			"label": _("Delivery Note"),
			"fieldtype": "Link",
			"options": "Delivery Note",
			"width": 140,
		},
		{
			"fieldname": "courier_provider",
			"label": _("Courier Provider"),
			"fieldtype": "Link",
			"options": "Courier Provider",
			"width": 130,
		},
		{
			"fieldname": "consignment_id",
			"label": _("Consignment ID"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "total_amount",
			"label": _("Total (BDT)"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "total_taxes_and_charges",
			"label": _("Total Taxes and Charges (BDT)"),
			"fieldtype": "Currency",
			"width": 160,
		},
		{
			"fieldname": "weight",
			"label": _("Weight"),
			"fieldtype": "Float",
			"width": 100,
		},
		{
			"fieldname": "delivery_status",
			"label": _("Delivery Status"),
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"fieldname": "delivery_charge",
			"label": _("Delivery Charge"),
			"fieldtype": "Currency",
			"width": 120,
		},
		{
			"fieldname": "cod_collection_fee",
			"label": _("COD Fee"),
			"fieldtype": "Currency",
			"width": 110,
		},
		{
			"fieldname": "net_margin",
			"label": _("Net Margin After Cost"),
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def get_data(filters):
	conditions, values = build_conditions(filters)

	sql = f"""
		SELECT
			do.name AS delivery_order,
			do.reference_doctype,
			do.reference_name,
			do.courier_provider,
			do.consignment_id,
			do.delivery_status,
			do.cod_amount AS total_amount,
			do.invoice_reference,
			do.raw_response
		FROM `tabDelivery Order` do
		WHERE do.docstatus = 1
			{conditions}
		ORDER BY do.creation DESC
	"""

	rows = frappe.db.sql(sql, values, as_dict=True)
	if not rows:
		return []

	api_data_map = fetch_delivery_charges_from_api(filters)

	result_data = []
	for row in rows:
		ref_dt = row.get("reference_doctype")
		ref_dn = row.get("reference_name")
		do_name = row.get("delivery_order")
		cid = str(row.get("consignment_id") or "").strip()
		inv = str(row.get("invoice_reference") or "").strip()

		sales_order = None
		delivery_note = None
		taxes_and_charges = 0.0
		doc_weight = 0.0

		if ref_dt == "Sales Order":
			sales_order = ref_dn
			dn_list = frappe.db.sql(
				"""
				SELECT DISTINCT parent FROM `tabDelivery Note Item`
				WHERE against_sales_order = %s
				LIMIT 1
				""",
				(ref_dn,),
				as_dict=True,
			)
			if dn_list:
				delivery_note = dn_list[0].get("parent") if isinstance(dn_list[0], dict) else dn_list[0][0]

			so_details = frappe.db.get_value(
				"Sales Order",
				ref_dn,
				["total_taxes_and_charges", "total_net_weight", "grand_total"],
				as_dict=True,
			)
			if so_details:
				taxes_and_charges = float(so_details.get("total_taxes_and_charges") or 0.0)
				doc_weight = float(so_details.get("total_net_weight") or 0.0)
				if not row.get("total_amount"):
					row["total_amount"] = float(so_details.get("grand_total") or 0.0)
				if not doc_weight:
					item_w = frappe.db.sql(
						"""
						SELECT SUM(
							CASE
								WHEN soi.total_weight > 0 THEN soi.total_weight
								WHEN soi.weight_per_unit > 0 THEN soi.qty * soi.weight_per_unit
								WHEN i.weight_per_unit > 0 THEN soi.qty * i.weight_per_unit
								ELSE 0
							END
						)
						FROM `tabSales Order Item` soi
						LEFT JOIN `tabItem` i ON i.name = soi.item_code
						WHERE soi.parent = %s
						""",
						(ref_dn,),
					)
					if item_w and item_w[0][0]:
						doc_weight = float(item_w[0][0])

		elif ref_dt == "Delivery Note":
			delivery_note = ref_dn
			so_list = frappe.db.sql(
				"""
				SELECT DISTINCT against_sales_order FROM `tabDelivery Note Item`
				WHERE parent = %s AND against_sales_order IS NOT NULL AND against_sales_order != ''
				LIMIT 1
				""",
				(ref_dn,),
				as_dict=True,
			)
			if so_list:
				sales_order = so_list[0].get("against_sales_order") if isinstance(so_list[0], dict) else so_list[0][0]

			dn_details = frappe.db.get_value(
				"Delivery Note",
				ref_dn,
				["total_taxes_and_charges", "total_net_weight", "grand_total"],
				as_dict=True,
			)
			if dn_details:
				taxes_and_charges = float(dn_details.get("total_taxes_and_charges") or 0.0)
				doc_weight = float(dn_details.get("total_net_weight") or 0.0)
				if not row.get("total_amount"):
					row["total_amount"] = float(dn_details.get("grand_total") or 0.0)
				if not doc_weight:
					item_w = frappe.db.sql(
						"""
						SELECT SUM(
							CASE
								WHEN dni.total_weight > 0 THEN dni.total_weight
								WHEN dni.weight_per_unit > 0 THEN dni.qty * dni.weight_per_unit
								WHEN i.weight_per_unit > 0 THEN dni.qty * i.weight_per_unit
								ELSE 0
							END
						)
						FROM `tabDelivery Note Item` dni
						LEFT JOIN `tabItem` i ON i.name = dni.item_code
						WHERE dni.parent = %s
						""",
						(ref_dn,),
					)
					if item_w and item_w[0][0]:
						doc_weight = float(item_w[0][0])

		api_weight = extract_weight_from_raw_response(row.get("raw_response"))

		map_weight = None
		charge = None
		if cid and cid in api_data_map:
			charge = api_data_map[cid].get("charge")
			map_weight = api_data_map[cid].get("weight")
		elif inv and inv in api_data_map:
			charge = api_data_map[inv].get("charge")
			map_weight = api_data_map[inv].get("weight")
		elif do_name and do_name in api_data_map:
			charge = api_data_map[do_name].get("charge")
			map_weight = api_data_map[do_name].get("weight")

		if map_weight is not None and float(map_weight) > 0:
			weight = float(map_weight)
		elif api_weight is not None and float(api_weight) > 0:
			weight = float(api_weight)
		else:
			weight = float(doc_weight or 0.0)

		if charge is None and row.get("raw_response"):
			charge = extract_charge_from_raw_response(row.get("raw_response"))

		if charge is None:
			charge = get_payout_log_charge(do_name)

		if charge is None:
			charge = 60.00

		charge = float(charge)
		tot_amt = float(row.get("total_amount") or 0.0)
		cod_fee = round(tot_amt * 0.01, 2)
		net_margin = tot_amt - (charge + cod_fee)

		result_data.append(
			{
				"delivery_order": do_name,
				"sales_order": sales_order,
				"delivery_note": delivery_note,
				"courier_provider": row.get("courier_provider"),
				"consignment_id": cid,
				"total_amount": tot_amt,
				"total_taxes_and_charges": taxes_and_charges,
				"weight": weight,
				"delivery_status": row.get("delivery_status"),
				"delivery_charge": charge,
				"cod_collection_fee": cod_fee,
				"net_margin": net_margin,
			}
		)

	return result_data


def fetch_delivery_charges_from_api(filters=None):
	"""Fetch payments, delivery charges, and weight from Courier API."""
	charge_map = {}
	try:
		from delivery_system.couriers import get_client

		provider_code = None
		if filters and filters.get("courier_provider"):
			p_val = filters.get("courier_provider")
			provider_code = frappe.db.get_value("Courier Provider", p_val, "provider_code") or p_val

		if not provider_code:
			default_provider = frappe.db.get_single_value("Courier Settings", "default_provider")
			if default_provider:
				provider_code = (
					frappe.db.get_value("Courier Provider", default_provider, "provider_code")
					or default_provider
				)

		if not provider_code:
			provider_code = "steadfast"

		client = get_client(provider_code)

		date_from = filters.get("from_date") if filters else None
		date_to = filters.get("to_date") if filters else None

		if hasattr(client, "get_payments"):
			raw_payments = client.get_payments(date_from=date_from, date_to=date_to)
			for p in raw_payments:
				cid = str(p.get("consignment_id") or p.get("cid") or "").strip()
				inv = str(p.get("invoice") or "").strip()
				do_name = str(p.get("delivery_order") or "").strip()

				chg = (
					p.get("delivery_charge")
					or p.get("charge")
					or p.get("delivery_fee")
					or p.get("charge_amount")
				)
				wt = (
					p.get("weight")
					or p.get("total_weight")
					or p.get("consignment_weight")
					or p.get("package_weight")
					or p.get("actual_weight")
					or p.get("item_weight")
				)
				entry = {
					"charge": float(chg) if chg is not None else None,
					"weight": float(wt) if wt is not None else None,
				}
				if cid:
					charge_map[cid] = entry
				if inv:
					charge_map[inv] = entry
				if do_name:
					charge_map[do_name] = entry
	except Exception:
		pass

	return charge_map


def extract_charge_from_raw_response(raw_response_str):
	"""Extract delivery charge from raw JSON API response."""
	if not raw_response_str:
		return None
	try:
		data = json.loads(raw_response_str) if isinstance(raw_response_str, str) else raw_response_str
		if isinstance(data, dict):
			consignment = data.get("consignment") or data.get("order") or data.get("data") or data
			if isinstance(consignment, dict):
				for key in ("delivery_charge", "charge", "delivery_fee", "charge_amount"):
					if key in consignment and consignment[key] is not None:
						return float(consignment[key])
	except Exception:
		pass
	return None


def extract_weight_from_raw_response(raw_response_str):
	"""Extract weight from raw JSON API response."""
	if not raw_response_str:
		return None
	try:
		data = json.loads(raw_response_str) if isinstance(raw_response_str, str) else raw_response_str
		if isinstance(data, dict):
			dict_sources = [
				data.get("consignment"),
				data.get("order"),
				data.get("data"),
				data,
			]
			weight_keys = (
				"weight",
				"total_weight",
				"package_weight",
				"consignment_weight",
				"item_weight",
				"actual_weight",
				"parcel_weight",
			)
			for source in dict_sources:
				if isinstance(source, dict):
					for key in weight_keys:
						if key in source and source[key] is not None:
							try:
								return float(source[key])
							except (ValueError, TypeError):
								pass
	except Exception:
		pass
	return None


def get_payout_log_charge(delivery_order_name):
	"""Query courier payout log for recorded charges."""
	if not delivery_order_name:
		return None
	try:
		res = frappe.db.sql(
			"""
			SELECT cpl.delivery_charges_deducted
			FROM `tabCourier Payout Item` cpli
			JOIN `tabCourier Payout` cpl ON cpl.name = cpli.parent
			WHERE cpli.delivery_order = %s
			LIMIT 1
			""",
			(delivery_order_name,),
		)
		if res and res[0][0] is not None:
			return float(res[0][0])
	except Exception:
		pass
	return None


def build_conditions(filters):
	conditions = []
	values = {}

	if filters.get("from_date"):
		conditions.append("DATE(do.creation) >= %(from_date)s")
		values["from_date"] = filters["from_date"]

	if filters.get("to_date"):
		conditions.append("DATE(do.creation) <= %(to_date)s")
		values["to_date"] = filters["to_date"]

	if filters.get("courier_provider"):
		conditions.append("do.courier_provider = %(courier_provider)s")
		values["courier_provider"] = filters["courier_provider"]

	if filters.get("delivery_status"):
		conditions.append("do.delivery_status = %(delivery_status)s")
		values["delivery_status"] = filters["delivery_status"]

	if filters.get("company"):
		conditions.append(
			"""(
				(do.reference_doctype = 'Sales Order' AND EXISTS (
					SELECT 1 FROM `tabSales Order` so
					WHERE so.name = do.reference_name AND so.company = %(company)s
				))
				OR
				(do.reference_doctype = 'Delivery Note' AND EXISTS (
					SELECT 1 FROM `tabDelivery Note` dn
					WHERE dn.name = do.reference_name AND dn.company = %(company)s
				))
			)"""
		)
		values["company"] = filters["company"]

	cond_str = ("AND " + " AND ".join(conditions)) if conditions else ""
	return cond_str, values

