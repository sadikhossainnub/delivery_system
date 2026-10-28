# Dashboard.py - Bug Analysis Report

## 🐛 Identified Issues

### **Issue #1: Company Filter Not Implemented**
**Severity:** HIGH
**Functions Affected:**
- `get_stuck_deliveries_count()`
- `get_monthly_cod_collected()`
- `get_monthly_delivery_charges()`
- `get_daily_delivery_trend()`
- `get_monthly_cod_trend()`
- `get_monthly_charges_trend()`
- `get_success_rate()`
- `get_reconciliation_rate()`

**Problem:**
```python
def get_stuck_deliveries_count(company=None):
    # company parameter accepted but NEVER used in query!
    filters = {
        "delivery_status": ["in", ["pending", "in_review"]],
        "creation": ["<=", add_days(today(), -min_days)],
        "docstatus": ["<", 2],
    }
    # Missing: company filter
```

**Impact:** Multi-company setup এ wrong data show করবে

---

### **Issue #2: Missing Error Handling**
**Severity:** MEDIUM
**Functions Affected:** Almost all functions

**Problem:**
```python
result = frappe.db.sql("""...""", as_dict=True)
total = flt(result[0].total)  # ❌ What if result is empty?
```

**Impact:** Empty result এ crash করবে

---

### **Issue #3: Cache Key Collision**
**Severity:** MEDIUM
**Function:** `get_courier_balance_card()`

**Problem:**
```python
cache_key = "steadfast_balance_card"  # ❌ Same key for all companies!
```

**Impact:** Multi-company setup এ wrong balance show করবে

---

### **Issue #4: SQL Injection Risk**
**Severity:** HIGH
**Functions:** Multiple chart functions

**Problem:**
```python
params = [str(start_date), str(end_date)]  # ❌ Direct string conversion
frappe.db.sql("""... WHERE DATE(creation) BETWEEN %s AND %s""", params)
```

**Impact:** SQL injection possible if date manipulation করা যায়

---

### **Issue #5: Hardcoded Provider Code**
**Severity:** LOW
**Function:** `get_courier_balance_card()`

**Problem:**
```python
client = get_client("steadfast")  # ❌ Hardcoded!
```

**Impact:** Other courier providers এর জন্য কাজ করবে না

---

### **Issue #6: Missing Null Checks**
**Severity:** MEDIUM

**Problem:**
```python
min_days = frappe.db.get_single_value("Courier Settings", "min_days_pending") or 3
# ❌ What if Courier Settings doesn't exist?
```

---

### **Issue #7: Incomplete Company-to-Order Mapping**
**Severity:** HIGH
**Function:** `get_stuck_deliveries_count()`

**Problem:**
```python
# Comment says: "Filter by company via reference doctype"
# But NO CODE TO DO IT!
if company:
    # Filter by company via reference doctype
    pass  # ❌ Not implemented!
```

---

### **Issue #8: Incorrect Date Filtering**
**Severity:** MEDIUM
**Function:** `get_daily_delivery_trend()`

**Problem:**
```python
# Delivered by last_synced_on
delivered_data = frappe.db.sql("""
    WHERE DATE(last_synced_on) BETWEEN %s AND %s
""")
# ❌ last_synced_on can be NULL or future date
```

---

### **Issue #9: Missing Validation**
**Severity:** LOW

**Problem:**
```python
def get_monthly_cod_trend(company=None, months=6):
    months = int(months or 6)  # ❌ What if months = "abc"?
```

---

### **Issue #10: Incomplete Clearing Account Logic**
**Severity:** MEDIUM
**Function:** `get_clearing_account_balance()`

**Problem:**
```python
clearing_account = _get_clearing_account(company)
if not clearing_account:
    return {"value": 0, "fieldtype": "Currency"}
# ❌ Should warn user that clearing account not configured
```

---

## 📊 Summary

| Severity | Count |
|----------|-------|
| HIGH     | 4     |
| MEDIUM   | 5     |
| LOW      | 1     |
| **Total**| **10**|

