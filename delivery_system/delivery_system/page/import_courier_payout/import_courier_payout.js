// Copyright (c) 2024, primetechbd and contributors
// Import Courier Payout — Page JS
// Frappe Page: import-courier-payout

frappe.pages["import-courier-payout"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Import Courier Payout",
		single_column: true,
	});

	new CourierPayoutImporter(page, wrapper);
};

class CourierPayoutImporter {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.parsed_rows = [];
		this.column_map = {};
		this.file_type = null;

		this._setup_page_actions();
		this._render_ui();
	}

	// ─── Page toolbar buttons ─────────────────────────────────────────────
	_setup_page_actions() {
		this.page.set_secondary_action("Back to Payouts", () => {
			frappe.set_route("List", "Courier Payout");
		});
	}

	// ─── Main UI layout ───────────────────────────────────────────────────
	_render_ui() {
		$(this.wrapper).find(".page-content").empty();

		this.$container = $(`<div class="payout-importer container" style="max-width:1000px;margin:24px auto;"></div>`);
		$(this.wrapper).find(".page-content").append(this.$container);

		this._render_step1_upload();
	}

	// ─── STEP 1: File upload + column settings ────────────────────────────
	_render_step1_upload() {
		this.$container.html(`
		<div class="card" style="border:1px solid var(--border-color);border-radius:8px;padding:24px;background:var(--card-bg);">
			<h5 style="margin-bottom:16px;font-weight:600;">
				<span class="badge badge-primary" style="margin-right:8px;">1</span>
				Upload Payout File
			</h5>

			<div class="row">
				<div class="col-sm-6">
					<div class="form-group">
						<label class="control-label">Courier Provider <span class="text-danger">*</span></label>
						<select class="form-control" id="pyi-courier">
							<option value="">-- Select --</option>
						</select>
					</div>
				</div>
				<div class="col-sm-6">
					<div class="form-group">
						<label class="control-label">Payout Date <span class="text-danger">*</span></label>
						<input type="date" class="form-control" id="pyi-date" value="${frappe.datetime.get_today()}">
					</div>
				</div>
			</div>

			<div class="row">
				<div class="col-sm-6">
					<div class="form-group">
						<label class="control-label">File (Excel .xlsx / .xls / .csv / PDF) <span class="text-danger">*</span></label>
						<input type="file" class="form-control-file" id="pyi-file"
							accept=".xlsx,.xls,.csv,.pdf" style="padding:6px 0;">
					</div>
				</div>
				<div class="col-sm-3">
					<div class="form-group">
						<label class="control-label">Header Row # (Excel)</label>
						<input type="number" class="form-control" id="pyi-header-row" value="1" min="1" max="20">
						<small class="text-muted">Row number containing column headers</small>
					</div>
				</div>
				<div class="col-sm-3">
					<div class="form-group">
						<label class="control-label">Sheet Name (optional)</label>
						<input type="text" class="form-control" id="pyi-sheet" placeholder="First sheet">
					</div>
				</div>
			</div>

			<div class="row">
				<div class="col-sm-12">
					<div class="form-group">
						<label class="control-label">Auto Post Payment Entries?</label>
						<div class="checkbox">
							<label>
								<input type="checkbox" id="pyi-auto-pe" checked>
								Yes — create Payment Entries automatically (Customer clearing &amp; Bank settlement)
							</label>
						</div>
					</div>
				</div>
			</div>

			<button class="btn btn-primary" id="pyi-parse-btn">
				<i class="fa fa-upload"></i> Upload &amp; Parse
			</button>
		</div>

		<div id="pyi-step2" style="display:none;margin-top:20px;"></div>
		`);

		this._load_courier_providers();
		$("#pyi-parse-btn").on("click", () => this._upload_and_parse());
	}

	// ─── Load courier providers dropdown ─────────────────────────────────
	_load_courier_providers() {
		frappe.call({
			method: "frappe.client.get_list",
			args: { doctype: "Courier Provider", filters: { enabled: 1 }, fields: ["name", "courier_name"], limit: 50 },
			callback: (r) => {
				const $sel = $("#pyi-courier");
				(r.message || []).forEach((p) => {
					$sel.append(`<option value="${p.name}">${p.courier_name || p.name}</option>`);
				});
			},
		});
	}

	// ─── Upload & Parse ───────────────────────────────────────────────────
	_upload_and_parse() {
		const file = document.getElementById("pyi-file").files[0];
		const courier = $("#pyi-courier").val();
		const header_row = parseInt($("#pyi-header-row").val() || "1");
		const sheet = $("#pyi-sheet").val().trim();

		if (!courier) { frappe.msgprint("Please select a Courier Provider."); return; }
		if (!file) { frappe.msgprint("Please select a file to upload."); return; }

		const ext = file.name.split(".").pop().toLowerCase();
		if (!["xlsx", "xls", "csv", "pdf"].includes(ext)) {
			frappe.msgprint("Unsupported file type. Use .xlsx, .xls, .csv, or .pdf");
			return;
		}

		this.file_type = ext;
		this.courier_provider = courier;

		frappe.show_alert({ message: "Parsing file…", indicator: "blue" });

		const reader = new FileReader();
		reader.onload = (e) => {
			const base64 = btoa(
				new Uint8Array(e.target.result).reduce((d, b) => d + String.fromCharCode(b), "")
			);
			frappe.call({
				method: "delivery_system.payout_import.parse_payout_file",
				args: {
					file_content_b64: base64,
					file_name: file.name,
					file_ext: ext,
					header_row: header_row,
					sheet_name: sheet || null,
				},
				callback: (r) => {
					if (r.message && r.message.rows) {
						this._render_step2_map(r.message);
					} else {
						frappe.msgprint("Could not parse file. " + (r.message?.error || ""));
					}
				},
			});
		};
		reader.readAsArrayBuffer(file);
	}

	// ─── STEP 2: Column mapping + preview ────────────────────────────────
	_render_step2_map(parsed) {
		const { columns, rows } = parsed;
		this.parsed_data = parsed;

		// Guess initial mapping
		const guess = _guess_column_map(columns);

		const field_defs = [
			{ key: "consignment_id", label: "Consignment ID", required: false },
			{ key: "invoice", label: "Invoice / Order Ref", required: false },
			{ key: "tracking_code", label: "Tracking Code", required: false },
			{ key: "recipient_name", label: "Recipient Name", required: false },
			{ key: "recipient_phone", label: "Recipient Phone", required: false },
			{ key: "cod_amount", label: "COD Amount", required: false },
			{ key: "delivery_charge", label: "Delivery Charge", required: false },
			{ key: "net_amount", label: "Net Amount (received)", required: false },
			{ key: "payment_id", label: "Payment / Batch ID", required: false },
			{ key: "status", label: "Delivery Status", required: false },
		];

		const optionHtml = (selected) =>
			`<option value="">-- Skip --</option>` +
			columns.map((c) => `<option value="${c}" ${c === selected ? "selected" : ""}>${c}</option>`).join("");

		const mapRows = field_defs
			.map(
				(f) => `
			<tr>
				<td><strong>${f.label}</strong>${f.required ? ' <span class="text-danger">*</span>' : ""}</td>
				<td>
					<select class="form-control form-control-sm pyi-col-map" data-field="${f.key}">
						${optionHtml(guess[f.key] || "")}
					</select>
				</td>
			</tr>`
			)
			.join("");

		// Preview table (first 5 rows)
		const previewRows = rows.slice(0, 5);
		const previewHead = columns.map((c) => `<th style="white-space:nowrap;">${c}</th>`).join("");
		const previewBody = previewRows
			.map(
				(r) =>
					`<tr>${columns.map((c) => `<td style="white-space:nowrap;">${r[c] ?? ""}</td>`).join("")}</tr>`
			)
			.join("");

		$("#pyi-step2").show().html(`
		<div class="card" style="border:1px solid var(--border-color);border-radius:8px;padding:24px;background:var(--card-bg);">
			<h5 style="margin-bottom:16px;font-weight:600;">
				<span class="badge badge-primary" style="margin-right:8px;">2</span>
				Map Columns
				<small class="text-muted" style="font-size:13px;font-weight:400;margin-left:8px;">
					(${rows.length} data rows found)
				</small>
			</h5>

			<div class="row">
				<div class="col-sm-6">
					<table class="table table-bordered table-sm" style="background:#fff;">
						<thead><tr><th>Field</th><th>Column in file</th></tr></thead>
						<tbody>${mapRows}</tbody>
					</table>
				</div>
				<div class="col-sm-6">
					<p class="text-muted" style="font-size:12px;">
						<strong>Note:</strong> At least one of <em>Consignment ID</em>, <em>Invoice</em> or
						<em>Tracking Code</em> must be mapped so that Delivery Orders can be matched.
					</p>
					<p class="text-muted" style="font-size:12px;">
						Rows where no matching Delivery Order is found will be <strong>skipped</strong>
						but reported in the result summary.
					</p>
				</div>
			</div>

			<h6 style="margin-top:8px;">File Preview (first 5 rows)</h6>
			<div style="overflow-x:auto;max-height:220px;font-size:12px;">
				<table class="table table-sm table-bordered" style="background:#fff;">
					<thead><tr>${previewHead}</tr></thead>
					<tbody>${previewBody}</tbody>
				</table>
			</div>

			<div style="margin-top:16px;">
				<button class="btn btn-success" id="pyi-import-btn">
					<i class="fa fa-check-circle"></i> Create Payouts
				</button>
				<button class="btn btn-default" id="pyi-back-btn" style="margin-left:8px;">
					<i class="fa fa-arrow-left"></i> Back
				</button>
			</div>
		</div>

		<div id="pyi-result" style="margin-top:20px;"></div>
		`);

		$("#pyi-import-btn").on("click", () => this._do_import());
		$("#pyi-back-btn").on("click", () => {
			$("#pyi-step2").hide();
		});
	}

	// ─── STEP 3: Import ───────────────────────────────────────────────────
	_do_import() {
		const column_map = {};
		$(".pyi-col-map").each(function () {
			const field = $(this).data("field");
			const col = $(this).val();
			if (col) column_map[field] = col;
		});

		if (!column_map.consignment_id && !column_map.invoice && !column_map.tracking_code) {
			frappe.msgprint(
				"Please map at least one of: Consignment ID, Invoice, or Tracking Code."
			);
			return;
		}

		const auto_pe = $("#pyi-auto-pe").is(":checked");
		const payout_date = $("#pyi-date").val();

		frappe.show_alert({ message: "Creating payouts & payment entries…", indicator: "blue" });
		$("#pyi-import-btn").prop("disabled", true).text("Processing…");

		frappe.call({
			method: "delivery_system.payout_import.create_payouts_from_rows",
			args: {
				rows: this.parsed_data.rows,
				column_map: column_map,
				courier_provider: this.courier_provider,
				payout_date: payout_date,
				auto_post_payment_entry: auto_pe ? 1 : 0,
			},
			callback: (r) => {
				$("#pyi-import-btn").prop("disabled", false).text("Create Payouts");
				if (r.message) {
					this._render_result(r.message);
				}
			},
		});
	}

	// ─── Result summary ───────────────────────────────────────────────────
	_render_result(result) {
		const { created, skipped, errors, payout_names } = result;

		const payout_links = (payout_names || [])
			.map(
				(n) =>
					`<a href="/app/courier-payout/${encodeURIComponent(n)}" target="_blank">${n}</a>`
			)
			.join(", ");

		const skip_rows = (skipped || [])
			.slice(0, 20)
			.map((s) => `<li>${frappe.utils.escape_html(String(s))}</li>`)
			.join("");

		const err_rows = (errors || [])
			.slice(0, 10)
			.map((e) => `<li class="text-danger">${frappe.utils.escape_html(String(e))}</li>`)
			.join("");

		$("#pyi-result").html(`
		<div class="card" style="border:1px solid var(--border-color);border-radius:8px;padding:24px;background:var(--card-bg);">
			<h5 style="margin-bottom:16px;font-weight:600;">
				<span class="badge badge-success" style="margin-right:8px;">✓</span>
				Import Complete
			</h5>
			<ul class="list-unstyled">
				<li><strong>Payouts Created:</strong> ${created} ${payout_links ? "— " + payout_links : ""}</li>
				<li><strong>Rows Skipped:</strong> ${(skipped || []).length}</li>
				<li><strong>Errors:</strong> ${(errors || []).length}</li>
			</ul>
			${skip_rows ? `<details><summary>Skipped rows</summary><ul>${skip_rows}</ul></details>` : ""}
			${err_rows ? `<details><summary>Errors</summary><ul>${err_rows}</ul></details>` : ""}
			<div style="margin-top:12px;">
				<a href="/app/courier-payout" class="btn btn-default btn-sm">
					View All Payouts
				</a>
				<button class="btn btn-primary btn-sm" style="margin-left:8px;" onclick="location.reload()">
					Import Another File
				</button>
			</div>
		</div>
		`);

		$("html, body").animate({ scrollTop: $("#pyi-result").offset().top - 60 }, 400);
	}
}

// ─── Column name guesser (fuzzy matching) ─────────────────────────────────────
function _guess_column_map(columns) {
	const map = {};
	const patterns = {
		consignment_id: /consign|cid|parcel.?id/i,
		invoice: /invoice|order.?ref|ref.?no|order.?no|inv/i,
		tracking_code: /track/i,
		recipient_name: /recipient|customer|name|recip/i,
		recipient_phone: /phone|mobile|contact/i,
		cod_amount: /cod|cash.?on.?deliv/i,
		delivery_charge: /charge|fee|service/i,
		net_amount: /net|actual|paid|remit/i,
		payment_id: /payment.?id|batch|pay.?id|payout/i,
		status: /status|deliv.*status/i,
	};

	columns.forEach((col) => {
		for (const [field, re] of Object.entries(patterns)) {
			if (!map[field] && re.test(col)) {
				map[field] = col;
			}
		}
	});
	return map;
}

