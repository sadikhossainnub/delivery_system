# Copyright (c) 2024, primetechbd and contributors
# For license information, please see license.txt

from frappe import _


def get_data():
	"""Dashboard data for Delivery Order connections tab."""
	return {
		"fieldname": "delivery_order",
		"transactions": [
			{
				"label": _("Reconciliation"),
				"items": ["Courier Payout Item"],
			},
		],
	}
