# Delivery System

**ERPNext Courier Integration for Bangladeshi courier services**

A production-ready Frappe custom app for ERPNext v15/v16 that integrates Bangladeshi courier services — starting with **Steadfast Courier** — and architected to add Pathao, RedX, Paperfly, and eCourier with minimal effort.

---

## Features

- **One-click booking** from Sales Order or Delivery Note
- **Bulk send** from list views (up to 500 orders per batch)
- **Automatic status sync** every 30 minutes via scheduled jobs
- **Manual refresh** button on form
- **Return request** initiation from the Delivery Order form
- **Inbound webhook** support for real-time status push
- **Per-company API credentials** via the `Courier Account` child table
- **Courier Delivery Status** reconciliation report
- **Full audit log** on every Delivery Order

---

## Supported Couriers

| Courier    | Status        | Provider Code |
|------------|---------------|---------------|
| Steadfast  | ✅ Implemented | `steadfast`   |
| Pathao     | 🔜 Stub        | `pathao`      |
| RedX       | 🔜 Stub        | `redx`        |
| Paperfly   | 🔜 Stub        | `paperfly`    |
| eCourier   | 🔜 Stub        | `ecourier`    |

---

## Installation

### 1. Get the app

```bash
# From your bench directory:
bench get-app delivery_system /path/to/delivery_system
# OR from git:
bench get-app delivery_system https://github.com/primetechbd/delivery_system
```

### 2. Install on a site

```bash
bench --site <your-site-name> install-app delivery_system
```

### 3. Run migrations

```bash
bench --site <your-site-name> migrate
```

This will:
- Create all DocTypes (Courier Provider, Courier Settings, Delivery Order, etc.)
- Add `courier_status` and `delivery_order_ref` custom fields to Sales Order and Delivery Note
- Load the Steadfast fixture record

---

## Configuration

### Courier Settings

1. Navigate to **Delivery System → Courier Settings**
2. Set **Default Provider** to `Steadfast`
3. In the **Courier Accounts** table, add a row:
   - **Company**: Your ERPNext company
   - **Courier Provider**: `Steadfast`
   - **API Key**: Your Steadfast API key (from portal.packzy.com)
   - **Secret Key**: Your Steadfast secret key
4. Enable **Auto Sync Status** (default ON)
5. Save

> **Security note**: The Secret Key is stored as a `Password` field (encrypted at rest). It is never returned to the browser or logged anywhere.

### Multiple Companies

Add one row per company in the **Courier Accounts** table. The `get_client()` factory automatically selects credentials by matching `provider_code` + `company` from the linked Sales Order/Delivery Note.

---

## Usage

### Booking from a Sales Order / Delivery Note

1. Open a submitted Sales Order or Delivery Note
2. Click **Send to Courier** (appears in the top toolbar)
3. Fill in recipient details, COD amount, and delivery type
4. Click **Book Courier**

The app will:
- Create a `Delivery Order` record (auto-named `DS-YYYY-XXXXX`)
- Call the Steadfast API
- Store the `Consignment ID` and `Tracking Code`
- Submit the Delivery Order
- Update `courier_status` on the SO/DN

### Tracking & Refresh

- **Track Delivery** button → opens the Delivery Order form
- **Refresh Status** button → calls the courier API immediately and updates the status

### Bulk Send

From the Sales Order or Delivery Note list view:
1. Select multiple records (checkboxes)
2. Click **Actions → Send Selected to Courier**

### Inbound Webhook (Steadfast Push)

Configure the webhook URL in your Steadfast merchant portal:

```
https://<your-site>/api/method/delivery_system.webhook.steadfast_webhook
```

The webhook updates Delivery Order status in the background via a queued job.

---

## Architecture

### Courier Abstraction Layer

```
delivery_system/couriers/
├── __init__.py          # BaseCourierClient + get_client() factory
├── steadfast.py         # Full Steadfast implementation
├── pathao.py            # Stub
└── redx.py              # Stub
```

**Adding a new courier** = one file:

```python
# delivery_system/couriers/myprovider.py
from delivery_system.couriers import BaseCourierClient

class Client(BaseCourierClient):
    def create_order(self, order_data): ...
    def bulk_create(self, orders): ...
    def get_status(self, invoice=None, consignment_id=None, tracking_code=None): ...
    def get_balance(self): ...
    def create_return_request(self, consignment_id, reason=""): ...
```

Then add `"myprovider": "delivery_system.couriers.myprovider"` to the `REGISTRY` in `couriers/__init__.py`.

---

## Running Tests

```bash
cd /path/to/frappe-bench
bench run-tests --app delivery_system
```

Or run the standalone unit tests (no Frappe site required for most):

```bash
python -m pytest delivery_system/tests/ -v
```

---

## DocTypes

| DocType | Type | Description |
|---|---|---|
| Courier Provider | Regular | Master list of supported couriers |
| Courier Settings | Single | Global settings + per-company credentials |
| Courier Account | Child Table | API credentials per company+provider |
| Delivery Order | Submittable | Core consignment tracking record |
| Delivery Order Log | Child Table | Audit log of status changes |

---

## Roles

| Role | Permissions |
|---|---|
| **Delivery Manager** | Full access to all Delivery System doctypes including settings |
| **Sales User** | Can trigger Send to Courier; read-only access to Delivery Orders |
| **System Manager** | Full access |

---

## License

MIT
