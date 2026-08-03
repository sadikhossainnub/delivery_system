// Copyright (c) 2024, primetechbd and contributors
// For license information, please see license.txt
//
// Shared helpers used by both Sales Order and Delivery Note client scripts.
// This is intentionally NOT registered as a client script — it is inlined
// into the SO/DN scripts via delivery_system.utils namespace.

window.delivery_system = window.delivery_system || {};

delivery_system.STATUS_COLOURS = {
	pending: "orange",
	in_review: "yellow",
	delivered_approval_pending: "blue",
	partial_delivered_approval_pending: "blue",
	cancelled_approval_pending: "pink",
	delivered: "green",
	partial_delivered: "teal",
	cancelled: "red",
	hold: "grey",
	unknown: "grey",
};

delivery_system.TERMINAL_STATUSES = ["delivered", "cancelled", "partial_delivered"];

/**
 * Renders the courier_status as a coloured badge in the form's indicator area.
 */
delivery_system.render_courier_badge = function (frm) {
	var status = frm.doc.courier_status;
	if (!status) return;
	var colour = delivery_system.STATUS_COLOURS[status] || "grey";
	var label = "Courier: " + frappe.utils.to_title_case(status.replace(/_/g, " "));
	$(frm.fields_dict["courier_status"].wrapper)
		.find(".control-value")
		.html('<span class="indicator-pill ' + colour + '">' + label + '</span>');
};

/**
 * Safe HTML stripper utility
 */
delivery_system.strip_html = function (str) {
	if (!str) return "";
	try {
		return $("<div>").html(str).text().trim();
	} catch (e) {
		return String(str).replace(/<[^>]*>?/gm, "").trim();
	}
};

// Polyfill frappe.utils.strip_html if missing
if (typeof frappe !== "undefined") {
	frappe.utils = frappe.utils || {};
	if (typeof frappe.utils.strip_html !== "function") {
		frappe.utils.strip_html = delivery_system.strip_html;
	}
}

/**
 * Robustly fetches customer's mobile number from doc or database (Customer/Contact).
 * Uses plain function callbacks (not arrow functions) for maximum browser compatibility.
 */
delivery_system.get_customer_phone = function (frm, callback) {
	var phone = frm.doc.customer_mobile_no || frm.doc.contact_mobile || frm.doc.mobile_no || "";
	if (phone) {
		if (callback) callback(phone);
		return;
	}
	if (!frm.doc.customer) {
		if (callback) callback("");
		return;
	}

	frappe.db.get_value("Customer", frm.doc.customer, ["mobile_no", "customer_primary_contact"], function (r) {
		if (r && r.mobile_no) {
			if (frm.fields_dict && frm.fields_dict["customer_mobile_no"]) {
				frm.set_value("customer_mobile_no", r.mobile_no);
			}
			if (callback) callback(r.mobile_no);
		} else if (r && r.customer_primary_contact) {
			frappe.db.get_value("Contact", r.customer_primary_contact, ["mobile_no", "phone"], function (c) {
				var p = (c && (c.mobile_no || c.phone)) || "";
				if (p && frm.fields_dict && frm.fields_dict["customer_mobile_no"]) {
					frm.set_value("customer_mobile_no", p);
				}
				if (callback) callback(p);
			});
		} else {
			if (callback) callback("");
		}
	});
};

/**
 * Calculates the Cash On Delivery (COD) amount for a Sales Order / Delivery Note doc object.
 * Adjusts for advance payments or full upfront payment.
 */
delivery_system.get_cod_amount = function (doc) {
	if (!doc) return 0;

	if (doc.is_paid) return 0;

	var payment_status = String(doc.payment_status || "").trim().toLowerCase();
	if (["paid", "fully paid", "completed"].indexOf(payment_status) !== -1) return 0;

	var status = String(doc.status || "").trim().toLowerCase();
	if (["paid", "completed"].indexOf(status) !== -1) return 0;

	var per_paid = flt(doc.per_paid || 0);
	if (per_paid >= 100) return 0;

	var total = flt(doc.rounded_total || doc.grand_total || 0);

	if (doc.outstanding_amount !== undefined && doc.outstanding_amount !== null && doc.outstanding_amount !== "") {
		var outstanding = flt(doc.outstanding_amount);
		if (outstanding <= 0) return 0;
		return Math.max(0, outstanding);
	}

	var advance_paid = flt(doc.advance_paid || 0);
	var paid_amount = flt(doc.paid_amount || 0);
	var total_paid = Math.max(advance_paid, paid_amount);

	var cod = total - total_paid;
	if (cod <= 0.01) return 0;
	return Math.max(0, flt(cod.toFixed(2)));
};
/**
 * Primary send flow: Opens a new Delivery Order DocType form pre-filled with order details.
 */
delivery_system.do_send_to_courier = function (frm, provider_code) {
	delivery_system.get_customer_phone(frm, function (recipient_phone) {
		var customer_name  = frm.doc.customer_name || frm.doc.customer || "";
		var address_display = frm.doc.shipping_address || frm.doc.customer_address || "";
		var strip_func = delivery_system.strip_html
			|| (frappe.utils && frappe.utils.strip_html)
			|| function (s) { return s || ""; };
		var address_text = address_display ? strip_func(address_display) : "";

		frappe.call({
			method: "delivery_system.api.get_ref_cod_amount",
			args: { reference_doctype: frm.doc.doctype, reference_name: frm.doc.name },
			callback: function (r) {
				var server_cod = (r && r.message !== undefined && r.message !== null)
					? r.message : delivery_system.get_cod_amount(frm.doc);
				_open_new_delivery_order(server_cod);
			},
			error: function () {
				_open_new_delivery_order(delivery_system.get_cod_amount(frm.doc));
			},
		});

		function _open_new_delivery_order(prefill_cod) {
			var new_doc_opts = {
				reference_doctype: frm.doc.doctype,
				reference_name: frm.doc.name,
				recipient_name: customer_name,
				recipient_phone: recipient_phone,
				recipient_address: address_text,
				cod_amount: prefill_cod,
				delivery_type: "Home Delivery",
			};
			if (provider_code) {
				new_doc_opts.courier_provider = provider_code;
			}

			frappe.new_doc("Delivery Order", new_doc_opts);
		}
	});
};

/**
 * Add "Send to Courier" button with provider picker if allowed by Courier Settings.
 * Uses Frappe's native grouped button mechanism for multi-provider — works across all Frappe versions.
 */
delivery_system.add_send_button = function (frm) {
	frappe.call({
		method: "delivery_system.api.get_booking_config",
		callback: function (r) {
			if (!r || !r.message) return;
			var booking_doctype = r.message.booking_doctype;
			var providers = r.message.providers;

			// Hide button if this doctype is not allowed by Courier Settings
			if (booking_doctype && booking_doctype !== "Both" && booking_doctype !== frm.doc.doctype) {
				return;
			}

			if (!providers || !providers.length) return;

			if (providers.length === 1) {
				// Single provider — plain button
				frm.add_custom_button(__("Send to Courier"), function () {
					delivery_system.do_send_to_courier(frm, providers[0].provider_code);
				}).addClass("btn-primary");

			} else {
				// Multiple providers — Frappe native grouped buttons (no raw Bootstrap dropdown needed)
				for (var i = 0; i < providers.length; i++) {
					(function (provider) {
						frm.add_custom_button(provider.courier_name, function () {
							delivery_system.do_send_to_courier(frm, provider.provider_code);
						}, __("Send to Courier"));
					})(providers[i]);
				}

				// Style the group trigger as primary
				setTimeout(function () {
					var $group = frm.custom_buttons && frm.custom_buttons[__("Send to Courier")];
					if ($group) $group.addClass("btn-primary");
				}, 150);
			}
		},
	});
};

// Backward-compatibility aliases
delivery_system.open_delivery_order = function (frm, provider_code) {
	delivery_system.do_send_to_courier(frm, provider_code);
};
delivery_system.show_send_dialog = delivery_system.do_send_to_courier;

/**
 * Add "Track Delivery" and "Refresh Status" buttons when a Delivery Order exists.
 */
delivery_system.add_tracking_buttons = function (frm) {
	frm.add_custom_button(__("Track Delivery"), function () {
		frappe.set_route("Form", "Delivery Order", frm.doc.delivery_order_ref);
	}, __("Courier"));

	frm.add_custom_button(__("Refresh Status"), function () {
		frappe.show_progress(__("Syncing..."), 30, 100);
		frappe.call({
			method: "delivery_system.api.sync_single_status",
			args: { delivery_order_name: frm.doc.delivery_order_ref },
			callback: function (r) {
				frappe.hide_progress();
				if (r && r.message) {
					frappe.show_alert({
						message: __("Status: {0}", [r.message.status]),
						indicator: r.message.status === "delivered" ? "green" : "orange",
					}, 5);
					frm.reload_doc();
				}
			},
		});
	}, __("Courier"));
};

/**
 * Display a detailed popup with success/failed summary and exact error messages for each document.
 */
delivery_system.show_bulk_send_results = function (results) {
	if (!results || !results.length) return;

	var succeeded = results.filter(function (x) { return x.success; });
	var failed = results.filter(function (x) { return !x.success; });

	var html = '<div style="max-height: 420px; overflow-y: auto;">';
	html += '<p style="font-size: 14px; font-weight: bold; margin-bottom: 12px;">'
		+ __("Summary: {0} Succeeded, {1} Failed", [succeeded.length, failed.length])
		+ '</p>';

	if (failed.length) {
		html += '<div style="margin-top: 10px; margin-bottom: 15px;">';
		html += '<h5 style="color: #e74c3c; font-weight: bold; margin-bottom: 8px;">'
			+ __("Failed Orders & Error Reasons:")
			+ '</h5>';
		html += '<table class="table table-bordered" style="font-size: 13px; margin-bottom: 0;">'
			+ '<thead><tr style="background-color: #fce8e6;">'
			+ '<th style="width: 35%;">Document Name</th>'
			+ '<th style="width: 65%;">Error Reason</th>'
			+ '</tr></thead><tbody>';
		failed.forEach(function (item) {
			var ref = frappe.utils.escape_html(item.reference || item.name || "");
			var err = frappe.utils.escape_html(item.error || __("Unknown error"));
			html += '<tr>'
				+ '<td><strong>' + ref + '</strong></td>'
				+ '<td style="color: #c0392b; font-weight: 500;">' + err + '</td>'
				+ '</tr>';
		});
		html += '</tbody></table></div>';
	}

	if (succeeded.length) {
		html += '<div style="margin-top: 10px;">';
		html += '<h5 style="color: #27ae60; font-weight: bold; margin-bottom: 8px;">'
			+ __("Succeeded Orders:")
			+ '</h5>';
		html += '<ul style="margin-left: 20px; color: #27ae60;">';
		succeeded.forEach(function (item) {
			var ref = frappe.utils.escape_html(item.reference || item.name || "");
			var do_ref = item.delivery_order
				? " \u2192 (" + frappe.utils.escape_html(item.delivery_order) + ")"
				: "";
			html += '<li><strong>' + ref + '</strong>' + do_ref + '</li>';
		});
		html += '</ul></div>';
	}

	html += '</div>';

	frappe.msgprint({
		title: __("Bulk Courier Booking Results"),
		message: html,
		indicator: failed.length ? (succeeded.length ? "orange" : "red") : "green",
		wide: true,
	});
};
