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
 * Opens a dialog to collect recipient details then calls send_to_courier.
 */
delivery_system.show_send_dialog = function (frm, provider_code) {
	// Pre-fill from document where possible
	const customer_name =
		frm.doc.customer_name || frm.doc.customer || "";
	const address_display =
		frm.doc.shipping_address || frm.doc.customer_address || "";
	const cod = frm.doc.grand_total || frm.doc.rounded_total || 0;

	const dialog = new frappe.ui.Dialog({
		title: __("Send to Courier"),
		fields: [
			{
				fieldname: "recipient_name",
				fieldtype: "Data",
				label: __("Recipient Name"),
				default: customer_name,
				reqd: 1,
			},
			{
				fieldname: "recipient_phone",
				fieldtype: "Data",
				label: __("Recipient Phone (11-digit BD)"),
				reqd: 1,
			},
			{
				fieldname: "recipient_address",
				fieldtype: "Small Text",
				label: __("Recipient Address"),
				default: address_display ? frappe.utils.strip_html(address_display) : "",
				reqd: 1,
			},
			{ fieldname: "col1", fieldtype: "Column Break" },
			{
				fieldname: "cod_amount",
				fieldtype: "Currency",
				label: __("COD Amount"),
				default: cod,
			},
			{
				fieldname: "delivery_type",
				fieldtype: "Select",
				label: __("Delivery Type"),
				options: "Home Delivery\nPoint Delivery",
				default: "Home Delivery",
			},
			{
				fieldname: "note",
				fieldtype: "Small Text",
				label: __("Note"),
			},
		],
		primary_action_label: __("Book Courier"),
		primary_action({ recipient_name, recipient_phone, recipient_address, cod_amount, delivery_type, note }) {
			dialog.hide();
			frappe.show_progress(__("Booking with courier..."), 50, 100);
			frappe.call({
				method: "delivery_system.api.send_to_courier",
				args: {
					reference_doctype: frm.doc.doctype,
					reference_name: frm.doc.name,
					provider_code,
					recipient_name,
					recipient_phone,
					recipient_address,
					cod_amount,
					delivery_type,
					note,
				},
				callback(r) {
					frappe.hide_progress();
					if (r.message) {
						frappe.show_alert({
							message: __("Booked! Consignment ID: {0}", [r.message.consignment_id || "N/A"]),
							indicator: "green",
						}, 8);
						frm.reload_doc();
					}
				},
				error() {
					frappe.hide_progress();
				},
			});
		},
	});
	dialog.show();
};

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
					delivery_system.show_send_dialog(frm, providers[0].provider_code);
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
								delivery_system.show_send_dialog(frm, p.provider_code);
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
