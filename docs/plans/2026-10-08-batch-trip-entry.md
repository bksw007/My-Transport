# Batch Trip Entry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let a driver enter one route once, create a configurable number of numbered trips, and optionally create a reversed return-pickup trip for every round.

**Architecture:** Keep batch expansion in a small pure-Python module so the round and note rules can be tested without a database. The Flask route will validate the requested round count, build all rows, insert them atomically in one PostgreSQL statement, and attach each uploaded image to every generated trip while storing the image object only once. Shared image cleanup will delete the physical object only after its final database reference is removed.

**Tech Stack:** Flask/Jinja, vanilla JavaScript and CSS, psycopg/PostgreSQL, Supabase Storage, Python `unittest`.

---

### Task 1: Define and test batch expansion rules

**Files:**
- Create: `trip_batch.py`
- Create: `tests/test_trip_batch.py`

**Step 1: Write failing tests**

Cover the default single round, five numbered outbound rounds, reversed return-pickup rows, preservation of an existing note, and invalid round values.

**Step 2: Run tests and verify failure**

Run: `.venv/bin/python -m unittest tests/test_trip_batch.py -v`

Expected: FAIL because the helper module does not exist yet.

**Step 3: Implement the pure helpers**

Add `parse_round_count()` with a range of 1–100 and `build_trip_batch()` that returns outbound rows annotated `รอบ N`, plus reversed rows annotated `รอบ N · รับกลับ` when requested.

**Step 4: Run tests and verify success**

Run: `.venv/bin/python -m unittest tests/test_trip_batch.py -v`

Expected: all batch rule tests PASS.

### Task 2: Add the batch controls to the entry form

**Files:**
- Modify: `templates/index.html`
- Modify: `static/styles.css`

**Step 1: Add form controls**

After `ประเภทรถ`, add a numeric `จำนวนรอบ` field with default/minimum 1 and maximum 100, followed by an unchecked `รับสินค้ากลับ` checkbox.

**Step 2: Add live feedback**

Show a concise summary such as `จะบันทึก 10 รายการ · 5 เที่ยวไป + 5 เที่ยวกลับ`, and use the same count in the save-status modal.

**Step 3: Style for the existing mobile-first industrial-luxury theme**

Reuse the gold/dark tokens, provide a large touch target, and preserve the single-column mobile layout.

### Task 3: Create every trip atomically

**Files:**
- Modify: `app.py`

**Step 1: Parse and validate batch options**

Read `round_count` and `return_pickup`; return a Thai validation message without writing partial data when invalid.

**Step 2: Build and insert the full batch**

Use one parameterized multi-row `INSERT ... RETURNING id` with one shared timestamp so the batch remains ordered. Keep the existing submission token in the same transaction so retries cannot duplicate the batch.

**Step 3: Associate uploaded images safely**

Upload each selected file once and create an image-reference row for every generated trip.

**Step 4: Report the result**

Flash the exact number of created trip records and redirect to the monthly list.

### Task 4: Make shared-image deletion reference-safe

**Files:**
- Modify: `app.py`

**Step 1: Add reference detection**

After deleting image rows, query whether each storage path is still referenced by another trip.

**Step 2: Delete only unreferenced physical files**

Apply the helper to both edit-image deletion and whole-trip deletion so deleting one generated trip cannot break images on the remaining trips.

### Task 5: Verify end to end

**Files:**
- Test: `tests/test_trip_batch.py`
- Verify: `app.py`, `templates/index.html`, `static/styles.css`

**Step 1: Run automated checks**

Run the Python unit tests, Python compilation, JavaScript syntax check, and `git diff --check`.

**Step 2: Test the mobile UI**

Render the form at a mobile viewport and verify the default is one round, the checkbox is empty, five rounds plus return displays ten records, and the save modal reports the same total.

**Step 3: Review the final diff**

Confirm unrelated untracked files remain untouched and no secrets or service-role keys enter browser code.
