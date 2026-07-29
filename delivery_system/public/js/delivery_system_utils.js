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
	const status = frm.doc.courier_status;
	if (!status) return;
	const colour = delivery_system.STATUS_COLOURS[status] || "grey";
	const label = "Courier: " + frappe.utils.to_title_case(status.replace(/_/g, " "));
	$(frm.fields_dict["courier_status"].wrapper)
		.find(".control-value")
		.html(`<span class="indicator-pill ${colour}">${label}</span>`);
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
 * Robustly fetches customer's mobile number from doc or database (Customer/Contact)
 */
delivery_system.get_customer_phone = function (frm, callback) {
	let phone = frm.doc.customer_mobile_no || frm.doc.contact_mobile || frm.doc.mobile_no || "";
	if (phone) {
		if (callback) callback(phone);
		return;
	}
	if (!frm.doc.customer) {
		if (callback) callback("");
		return;
	}

	frappe.db.get_value("Customer", frm.doc.customer, ["mobile_no", "customer_primary_contact"], (r) => {
		if (r && r.mobile_no) {
			if (frm.fields_dict && frm.fields_dict["customer_mobile_no"]) {
				frm.set_value("customer_mobile_no", r.mobile_no);
			}
			if (callback) callback(r.mobile_no);
		} else if (r && r.customer_primary_contact) {
			frappe.db.get_value("Contact", r.customer_primary_contact, ["mobile_no", "phone"], (c) => {
				const p = (c && (c.mobile_no || c.phone)) || "";
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
 * Opens a new Delivery Order DocType form pre-populated with reference details.
 */
delivery_system.open_delivery_order = function (frm, provider_code) {
	delivery_system.get_customer_phone(frm, function (recipient_phone) {
		const customer_name =
			frm.doc.customer_name || frm.doc.customer || "";
		const address_display =
			frm.doc.shipping_address || frm.doc.customer_address || "";
		const cod = frm.doc.grand_total || frm.doc.rounded_total || 0;

		const strip_func = delivery_system.strip_html || (frappe.utils && frappe.utils.strip_html) || function(s) { return s || ""; };
		const address_text = address_display ? strip_func(address_display) : "";

		const route_options = {
			reference_doctype: frm.doc.doctype,
			reference_name: frm.doc.name,
			recipient_name: customer_name,
			recipient_phone: recipient_phone,
			recipient_address: address_text,
			cod_amount: cod,
			delivery_type: "Home Delivery",
		};

		if (provider_code) {
			frappe.db.get_value("Courier Provider", { provider_code: provider_code, enabled: 1 }, "name", (r) => {
				if (r && r.name) {
					route_options.courier_provider = r.name;
				}
				frappe.route_options = route_options;
				frappe.new_doc("Delivery Order");
			});
		} else {
			frappe.route_options = route_options;
			frappe.new_doc("Delivery Order");
		}
	});
};

delivery_system.show_send_dialog = delivery_system.open_delivery_order;

/**
 * Add "Send to Courier" button with provider picker if allowed by Courier Settings.
 */
delivery_system.add_send_button = function (frm) {
	frappe.call({
		method: "delivery_system.api.get_booking_config",
		callback(r) {
			if (!r.message) return;
			const { booking_doctype, providers } = r.message;

			// Hide button if this doctype is not allowed by Courier Settings
			if (booking_doctype && booking_doctype !== "Both" && booking_doctype !== frm.doc.doctype) {
				return;
			}

			if (!providers || !providers.length) return;

			if (providers.length === 1) {
				frm.add_custom_button(__("Send to Courier"), () => {
					delivery_system.open_delivery_order(frm, providers[0].provider_code);
				}).addClass("btn-primary");
			} else {
				// Multiple providers — add a dropdown
				const btn = frm.add_custom_button(__("Send to Courier ▾"), () => {});
				btn.addClass("btn-primary");
				const menu = $("<ul class='dropdown-menu'>").appendTo(btn.parent());
				providers.forEach(p => {
					menu.append(
						$("<li>").append(
							$("<a>").text(p.courier_name).click(() => {
								delivery_system.open_delivery_order(frm, p.provider_code);
							})
						)
					);
				});
				btn.parent().addClass("dropdown").attr("data-toggle", "dropdown");
			}
		},
	});
};

/**
 * Add "Track Delivery" and "Refresh Status" buttons when a Delivery Order exists.
 */
delivery_system.add_tracking_buttons = function (frm) {
	frm.add_custom_button(__("Track Delivery"), () => {
		frappe.set_route("Form", "Delivery Order", frm.doc.delivery_order_ref);
	}, __("Courier"));

	frm.add_custom_button(__("Refresh Status"), () => {
		frappe.show_progress(__("Syncing..."), 30, 100);
		frappe.call({
			method: "delivery_system.api.sync_single_status",
			args: { delivery_order_name: frm.doc.delivery_order_ref },
			callback(r) {
				frappe.hide_progress();
				if (r.message) {
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

	const succeeded = results.filter((x) => x.success);
	const failed = results.filter((x) => !x.success);

	let html = `<div style="max-height: 420px; overflow-y: auto;">`;
	html += `<p style="font-size: 14px; font-weight: bold; margin-bottom: 12px;">` +
		__("Summary: {0} Succeeded, {1} Failed", [succeeded.length, failed.length]) +
		`</p>`;

	if (failed.length) {
		html += `<div style="margin-top: 10px; margin-bottom: 15px;">`;
		html += `<h5 style="color: #e74c3c; font-weight: bold; margin-bottom: 8px;">` +
			__("Failed Orders & Error Reasons:") +
			`</h5>`;
		html += `<table class="table table-bordered style="font-size: 13px; margin-bottom: 0;">
			<thead>
				<tr style="background-color: #fce8e6;">
					<th style="width: 35%;">Document Name</th>
					<th style="width: 65%;">Error Reason</th>
				</tr>
			</thead>
			<tbody>`;
		failed.forEach((item) => {
			const ref = frappe.utils.escape_html(item.reference || item.name || "");
			const err = frappe.utils.escape_html(item.error || __("Unknown error"));
			html += `<tr>
				<td><strong>${ref}</strong></td>
				<td style="color: #c0392b; font-weight: 500;">${err}</td>
			</tr>`;
		});
		html += `</tbody></table></div>`;
	}

	if (succeeded.length) {
		html += `<div style="margin-top: 10px;">`;
		html += `<h5 style="color: #27ae60; font-weight: bold; margin-bottom: 8px;">` +
			__("Succeeded Orders:") +
			`</h5>`;
		html += `<ul style="margin-left: 20px; color: #27ae60;">`;
		succeeded.forEach((item) => {
			const ref = frappe.utils.escape_html(item.reference || item.name || "");
			const do_ref = item.delivery_order ? ` → (${frappe.utils.escape_html(item.delivery_order)})` : "";
			html += `<li><strong>${ref}</strong> ${do_ref}</li>`;
		});
		html += `</ul></div>`;
	}

	html += `</div>`;

	frappe.msgprint({
		title: __("Bulk Courier Booking Results"),
		message: html,
		indicator: failed.length ? (succeeded.length ? "orange" : "red") : "green",
		wide: true,
	});
};

