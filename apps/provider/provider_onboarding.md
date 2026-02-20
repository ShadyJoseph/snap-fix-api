# Provider Onboarding Requirements & Flow - MVP v1.0

## 📋 What Providers Need to Upload

### **REQUIRED Documents** (Cannot proceed without these)

| Document                               | Type  | Purpose               | Max Size | Accepted Formats    |
| -------------------------------------- | ----- | --------------------- | -------- | ------------------- |
| **NID Front**                          | Image | Identity verification | 5MB      | JPG, JPEG, PNG, PDF |
| **NID Back**                           | Image | Identity verification | 5MB      | JPG, JPEG, PNG, PDF |
| **Police Clearance Certificate (PCC)** | File  | Background check      | 5MB      | JPG, JPEG, PNG, PDF |

### **OPTIONAL Documents** (Recommended but not required)

| Document                     | Type  | Purpose            | Max Size | Accepted Formats    |
| ---------------------------- | ----- | ------------------ | -------- | ------------------- |
| **Professional Certificate** | File  | Skill verification | 5MB      | JPG, JPEG, PNG, PDF |
| **Profile Photo**            | Image | Profile display    | 5MB      | JPG, JPEG, PNG      |

---

## 👤 Personal Information Required

### **REQUIRED Fields**

| Field             | Validation                         | Purpose          |
| ----------------- | ---------------------------------- | ---------------- |
| **First Name**    | Max 100 chars                      | Legal name       |
| **Last Name**     | Max 100 chars                      | Legal name       |
| **Email**         | Valid email, unique in system      | Account login    |
| **Phone**         | Format: +999999999 (9-15 digits)   | Contact          |
| **Date of Birth** | Must be 18+ years old              | Age verification |
| **Address**       | Text field                         | Service location |
| **Region**        | Must select from available regions | Operating area   |

### **CALCULATED Fields** (Automatic)

| Field   | Calculation                   | Purpose              |
| ------- | ----------------------------- | -------------------- |
| **Age** | Calculated from date_of_birth | Automatic validation |

---

## 💼 Professional Information Required

### **REQUIRED Fields**

| Field                   | Validation                           | Purpose          |
| ----------------------- | ------------------------------------ | ---------------- |
| **Category**            | Select one from available categories | Service type     |
| **Hourly Rate**         | Decimal ≥ 0                          | Initial pricing  |
| **Years of Experience** | Integer ≥ 0                          | Experience level |

### **OPTIONAL Fields**

| Field   | Purpose                                |
| ------- | -------------------------------------- |
| **Bio** | Description of services and experience |

---

## ✅ Eligibility Criteria

### **Automatic Validations (System Enforced)**

```
✓ Age: Must be 18 years or older
✓ Email: Must be unique (not registered in system)
✓ Phone: Must match format +999999999 (9-15 digits)
✓ File Size: Each document ≤ 5MB
✓ File Format: Only JPG, JPEG, PNG, PDF accepted
✓ Required Fields: All marked fields must be filled
✓ Required Documents: NID Front, NID Back, PCC must be uploaded
```

### **Manual Review Criteria (Admin Checks)**

```
□ NID Photos: Clear, readable, matches applicant name
□ PCC: Valid, recent (recommend within 6 months)
□ Professional Certificate: Valid if provided
□ Information Accuracy: Name, phone, address verification
□ Category Match: Experience aligns with selected category
□ Pricing: Hourly rate is reasonable for category/region
```

---

## 🔄 Complete Onboarding Flow

### **1. SUBMISSION Phase**

```
Provider → Fills Application Form
         ↓
System → Validates all fields
         ↓
System → Validates file sizes/formats
         ↓
System → Checks email uniqueness
         ↓
System → Checks age ≥ 18
         ↓
Status: PENDING
```

**What Happens:**

- Application auto-saved with status `PENDING`
- Timestamp: `submitted_at` recorded
- Application visible in admin dashboard

---

### **2. REVIEW Phase**

```
Admin → Views application in dashboard
      ↓
Admin → Clicks "Move to Review"
      ↓
Status: UNDER_REVIEW
```

**What Happens:**

- Status changes to `UNDER_REVIEW`
- `reviewed_by` = admin user
- `reviewed_at` = current timestamp
- Admin can now see document preview
- Admin reviews all documents and information

---

### **3. DECISION Phase**

Admin has **3 options**:

#### **Option A: APPROVE** ✓

```
Admin → Clicks "Approve" or Changes status to "Approved"
      ↓
System → Creates Provider Account (Transaction)
       ↓
       1. Generate temporary password
       2. Create Provider user account
       3. Transfer documents to Provider
       4. Add selected category
       5. Link Provider to Onboarding
       ↓
Status: APPROVED
Provider Account: CREATED
```

**What Happens:**

- Provider account created with:
  - Email, name, phone from application
  - Region and address from application
  - Hourly rate and experience from application
  - Documents transferred (NID → id_document, etc.)
  - Category assigned
  - `verification_status = VERIFIED`
  - `is_verified = True`
  - `is_active = True`
- Onboarding status → `APPROVED`
- `approved_at` timestamp recorded
- Admin receives success message in dashboard
- Provider can now login with email and password

#### **Option B: REQUEST CHANGES** ⚠️

```
Admin → Changes status to "Changes Required"
      ↓
Admin → Fills "Change Requests" field
      ↓
Status: CHANGES_REQUIRED
```

**What Happens:**

- Status → `CHANGES_REQUIRED`
- `change_requests` field filled with specific issues
- `reviewed_at` timestamp recorded
- Provider must submit new application with corrections
- Original application kept for reference

#### **Option C: REJECT** ✗

```
Admin → Changes status to "Rejected"
      ↓
Admin → Fills "Rejection Reason" field
      ↓
Status: REJECTED
```

**What Happens:**

- Status → `REJECTED`
- `rejection_reason` field filled
- `rejected_at` timestamp recorded
- No provider account created
- Application archived in system
- Provider can submit new application if they wish

---

## 📊 State Machine Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    ONBOARDING STATES                        │
└─────────────────────────────────────────────────────────────┘

         START (Provider Submits)
                  │
                  ▼
         ┌─────────────────┐
         │    PENDING      │ ← Initial state
         │   (Submitted)   │
         └────────┬────────┘
                  │
                  │ Admin: Move to Review
                  ▼
         ┌─────────────────┐
         │  UNDER_REVIEW   │ ← Admin reviewing
         │   (Reviewing)   │
         └────────┬────────┘
                  │
      ┌───────────┼───────────┐
      │           │           │
      │           │           │
   APPROVE    CHANGES      REJECT
      │        REQUIRED       │
      │           │           │
      ▼           ▼           ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ APPROVED │ │ CHANGES  │ │ REJECTED │
│ Provider │ │ REQUIRED │ │   END    │
│ Created! │ │ New App  │ │          │
└──────────┘ └──────────┘ └──────────┘
   (END)        (END)         (END)


Legend:
━━━━  Normal flow
END    Terminal state (no further changes)
```

---

## 🔒 Security & Validation

### **Input Validation**

```python
# Automatic validations before save
✓ Age: Calculated from date_of_birth, must be ≥ 18
✓ Email: Must not exist in User table
✓ Phone: Regex validation
✓ Files: Size ≤ 5MB each
✓ Files: Extension in [jpg, jpeg, png, pdf]
✓ Required fields: Cannot be blank
```

### **File Upload Security**

```python
# Each file is validated for:
1. File Extension: Only allowed types
2. File Size: Maximum 5MB
3. Upload Path: Organized by document type
   - NID Front: onboarding/nid/front/
   - NID Back: onboarding/nid/back/
   - PCC: onboarding/pcc/
   - Certificates: onboarding/certificates/
   - Photos: onboarding/photos/
```

### **Data Privacy**

```python
# Document access:
- Only admin users can view onboarding documents
- Documents transferred to provider after approval
- Original onboarding documents preserved for audit
- Sensitive data protected by Django permissions
```

---

## 🎯 Admin Dashboard Actions

### **List View Actions**

| Action                   | Applies To                | Result                    |
| ------------------------ | ------------------------- | ------------------------- |
| **Move to Review**       | PENDING, CHANGES_REQUIRED | Sets to UNDER_REVIEW      |
| **Approve Applications** | UNDER_REVIEW              | Creates Provider accounts |
| **Reject Applications**  | UNDER_REVIEW              | Marks as REJECTED         |

### **Detail View Actions**

When viewing a single application:

1. **View Documents** - Preview NID, PCC in admin
2. **Review Details** - Check all personal/professional info
3. **Add Admin Notes** - Internal notes (not visible to provider)
4. **Change Status** - Manually change state
5. **Add Rejection Reason** - Required when rejecting
6. **Add Change Requests** - Specific items to fix
7. **View Provider Account** - Link to created provider (if approved)

---

## 🔄 Resubmission Flow

```
Provider applies → REJECTED or CHANGES_REQUIRED
                  ↓
Provider submits NEW application
(New record, new documents)
                  ↓
Starts at PENDING again
```

**Note:** Each application is a separate record. Provider must submit new application if previous was rejected or changes were requested.

---

## ⚙️ Technical Implementation

### **State Transition Methods**

```python
# FSM Methods (models.py)

move_to_review(admin_user)
├─ Can be called from: PENDING, CHANGES_REQUIRED
├─ Sets status: UNDER_REVIEW
└─ Records: reviewed_by, reviewed_at

approve(admin_user)
├─ Can be called from: UNDER_REVIEW
├─ Creates Provider account (atomic transaction)
├─ Transfers documents
├─ Sets status: APPROVED
└─ Records: provider, approved_at

reject(admin_user, reason)
├─ Can be called from: UNDER_REVIEW
├─ Sets status: REJECTED
└─ Records: rejection_reason, rejected_at

request_changes(admin_user, change_requests)
├─ Can be called from: UNDER_REVIEW
├─ Sets status: CHANGES_REQUIRED
└─ Records: change_requests, reviewed_at
```

---

## ⚡ Quick Reference

### **Provider Journey**

```
1. Provider fills form (10 min)
   ↓
2. Uploads documents (5 min)
   ↓
3. Submits application
   ↓
4. Waits for admin review (24-48 hours SLA)
   ↓
5a. APPROVED → Account created, can login
5b. REJECTED → Can submit new application
5c. CHANGES → Must submit new corrected application
```

### **Admin Journey**

```
1. View pending applications
   ↓
2. Click application
   ↓
3. Review documents & info (5-10 min)
   ↓
4. Make decision:
   - Approve → Account auto-created ✓
   - Reject → Add reason ✗
   - Request Changes → List issues ⚠️
   ↓
5. Application moves to terminal state
```
