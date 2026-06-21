#!/usr/bin/env python3
"""
generate_data.py
Generates all dummy seed data for AI FrontLine Agent:
  - 10 sales reps
  - 100 Vietnamese customer profiles
  - Product portfolio assignments per customer
  - Contracts (with clauses + coverages for Banca/Insurance)
  - ~8,000+ transactions

Output: /data/seeds/*.json
Single source of truth — both seed_postgres.py and seed_neo4j.py read from these files.
"""

import json
import random
import os
from datetime import date, timedelta

random.seed(42)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "seeds")

# ── Vietnamese name data ──────────────────────────────────────────────────────

SURNAMES = [
    'Nguyễn', 'Trần', 'Lê', 'Phạm', 'Hoàng', 'Huỳnh', 'Phan', 'Vũ', 'Võ',
    'Đặng', 'Bùi', 'Đỗ', 'Hồ', 'Ngô', 'Dương', 'Lý', 'Lưu', 'Trịnh', 'Đinh'
]

MALE_MIDDLE = [
    'Văn', 'Đức', 'Minh', 'Quang', 'Hữu', 'Trọng', 'Xuân', 'Tiến',
    'Công', 'Mạnh', 'Quốc', 'Thành', 'Kiên', 'Đình', 'Hoàng', 'Ngọc', 'Trung'
]

FEMALE_MIDDLE = [
    'Thị', 'Thu', 'Minh', 'Ngọc', 'Bích', 'Thùy', 'Mỹ', 'Kim',
    'Phương', 'Hồng', 'Khánh', 'Bảo', 'Thanh'
]

MALE_GIVEN = [
    'An', 'Tuấn', 'Huy', 'Anh', 'Bình', 'Nam', 'Nghĩa', 'Phúc', 'Dũng',
    'Vinh', 'Hùng', 'Bảo', 'Long', 'Cường', 'Khoa', 'Sơn', 'Hiếu', 'Toàn',
    'Nhật', 'Thắng', 'Tùng', 'Đạt', 'Phát', 'Khánh', 'Hải', 'Liêm', 'Trực'
]

FEMALE_GIVEN = [
    'Hương', 'Lan', 'Mai', 'Hà', 'Châu', 'Anh', 'Hoa', 'Ngọc', 'Linh',
    'Duyên', 'Ngân', 'Thảo', 'Nhung', 'Hằng', 'Trinh', 'Trang', 'Tâm',
    'Hân', 'Yến', 'Nhi', 'Vy', 'Giang', 'Phương', 'Diệp', 'Oanh', 'Thúy'
]

CITIES = [
    ('Hồ Chí Minh', 0.40), ('Hà Nội', 0.30), ('Đà Nẵng', 0.10),
    ('Cần Thơ', 0.05), ('Hải Phòng', 0.05), ('Nha Trang', 0.03),
    ('Huế', 0.03), ('Vũng Tàu', 0.04),
]

OCCUPATIONS = [
    'Kế toán trưởng', 'Kỹ sư phần mềm', 'Bác sĩ', 'Giáo viên', 'Luật sư',
    'Kiến trúc sư', 'Giám đốc kinh doanh', 'Chuyên viên ngân hàng',
    'Dược sĩ', 'Quản lý dự án', 'Chủ doanh nghiệp', 'Marketing Manager',
    'Kỹ sư xây dựng', 'Chuyên viên tài chính', 'Nhân viên kinh doanh',
    'Bác sĩ nha khoa', 'Kỹ sư điện tử', 'Chuyên viên nhân sự', 'Giám đốc điều hành'
]

SEGMENT_DIST = ['Standard'] * 40 + ['Gold'] * 35 + ['Platinum'] * 20 + ['Elite'] * 5

CREDIT_SCORE_RANGE = {
    'Standard': (500, 649), 'Gold': (650, 739),
    'Platinum': (740, 799), 'Elite': (800, 850)
}

INCOME_RANGE = {
    'Standard': ['< 10 triệu VND/tháng', '10-20 triệu VND/tháng'],
    'Gold':     ['20-30 triệu VND/tháng', '30-50 triệu VND/tháng'],
    'Platinum': ['50-100 triệu VND/tháng', '100-200 triệu VND/tháng'],
    'Elite':    ['200-500 triệu VND/tháng', '> 500 triệu VND/tháng']
}

# ── Product catalogue ─────────────────────────────────────────────────────────

PRODUCTS = {
    'CASA': {
        'product_id': 'PROD-CASA-01',
        'product_name': 'TCB Tài khoản thanh toán',
        'product_type': 'CASA'
    },
    'CREDIT_GOLD': {
        'product_id': 'PROD-CC-GOLD',
        'product_name': 'TCB Thẻ tín dụng Gold',
        'product_type': 'CREDIT_CARD',
        'tier': 'GOLD',
        'credit_limit': 50_000_000
    },
    'CREDIT_PLATINUM': {
        'product_id': 'PROD-CC-PLAT',
        'product_name': 'TCB Thẻ tín dụng Platinum',
        'product_type': 'CREDIT_CARD',
        'tier': 'PLATINUM',
        'credit_limit': 150_000_000
    },
    'CREDIT_ELITE': {
        'product_id': 'PROD-CC-ELITE',
        'product_name': 'TCB Thẻ tín dụng Elite',
        'product_type': 'CREDIT_CARD',
        'tier': 'ELITE',
        'credit_limit': 500_000_000
    },
    'BANCA_LIFE': {
        'product_id': 'PROD-BANCA-01',
        'product_name': 'TCB Banca Life Protection Plus',
        'product_type': 'BANCASSURANCE',
        'insurer': 'Prudential Vietnam'
    },
    'BANCA_WEALTH': {
        'product_id': 'PROD-BANCA-02',
        'product_name': 'TCB Banca Wealth Secure',
        'product_type': 'BANCASSURANCE',
        'insurer': 'Manulife Vietnam'
    },
    'TERM_DEPOSIT_STD': {
        'product_id': 'PROD-TD-STD',
        'product_name': 'TCB Tiền gửi có kỳ hạn Standard',
        'product_type': 'TERM_DEPOSIT'
    },
    'TERM_DEPOSIT_PLUS': {
        'product_id': 'PROD-TD-PLUS',
        'product_name': 'TCB Tiền gửi có kỳ hạn Plus',
        'product_type': 'TERM_DEPOSIT'
    },
    'PERSONAL_LOAN': {
        'product_id': 'PROD-LOAN-PER',
        'product_name': 'TCB Vay tiêu dùng cá nhân',
        'product_type': 'PERSONAL_LOAN'
    },
    'HOME_LOAN': {
        'product_id': 'PROD-LOAN-HOME',
        'product_name': 'TCB Vay mua nhà',
        'product_type': 'HOME_LOAN'
    },
    'CERT_DEPOSIT': {
        'product_id': 'PROD-CD-01',
        'product_name': 'TCB Chứng chỉ tiền gửi',
        'product_type': 'CERTIFICATE_OF_DEPOSIT'
    },
    'TRAVEL_INSURANCE': {
        'product_id': 'PROD-INS-TRAVEL',
        'product_name': 'TCB Bảo hiểm du lịch',
        'product_type': 'NON_LIFE_INSURANCE'
    },
    'ACCIDENT_INSURANCE': {
        'product_id': 'PROD-INS-ACC',
        'product_name': 'TCB Bảo hiểm tai nạn cá nhân',
        'product_type': 'NON_LIFE_INSURANCE'
    },
    'BUSINESS_LENDING': {
        'product_id': 'PROD-BIZ-LOAN',
        'product_name': 'TCB Cho vay doanh nghiệp vừa và nhỏ',
        'product_type': 'BUSINESS_LENDING'
    }
}

# ── Vietnamese merchants ──────────────────────────────────────────────────────
# (name, category, min_amount_vnd, max_amount_vnd)

MERCHANTS = [
    ('Grab', 'TRANSPORT', 45_000, 450_000),
    ('Be', 'TRANSPORT', 40_000, 380_000),
    ('Xanh SM', 'TRANSPORT', 70_000, 550_000),
    ('Bách Hóa Xanh', 'GROCERY', 80_000, 1_800_000),
    ('VinMart', 'GROCERY', 120_000, 2_500_000),
    ('Co.opMart', 'GROCERY', 150_000, 3_500_000),
    ('AEON Mall', 'GROCERY', 250_000, 5_000_000),
    ('Highlands Coffee', 'DINING', 55_000, 220_000),
    ('Phúc Long', 'DINING', 45_000, 190_000),
    ('The Coffee House', 'DINING', 50_000, 210_000),
    ("Gong Cha", 'DINING', 50_000, 160_000),
    ("Pizza 4P's", 'DINING', 300_000, 2_200_000),
    ('Nhà hàng Ngon', 'DINING', 400_000, 2_800_000),
    ('KFC Vietnam', 'DINING', 80_000, 400_000),
    ('Shopee', 'ECOMMERCE', 100_000, 8_000_000),
    ('Lazada', 'ECOMMERCE', 150_000, 6_000_000),
    ('Tiki', 'ECOMMERCE', 120_000, 4_500_000),
    ('Vinmec Hospital', 'HEALTHCARE', 500_000, 12_000_000),
    ('Pharmacity', 'HEALTHCARE', 60_000, 600_000),
    ('FV Hospital', 'HEALTHCARE', 800_000, 18_000_000),
    ('An Khang Pharmacy', 'HEALTHCARE', 50_000, 500_000),
    ('EVN - Tiền điện', 'UTILITIES', 200_000, 2_000_000),
    ('VNPT - Internet', 'UTILITIES', 200_000, 450_000),
    ('Viettel', 'UTILITIES', 100_000, 500_000),
    ('FPT Telecom', 'UTILITIES', 180_000, 400_000),
    ('Vietnam Airlines', 'TRAVEL', 1_200_000, 14_000_000),
    ('VietJet Air', 'TRAVEL', 800_000, 7_500_000),
    ('Bamboo Airways', 'TRAVEL', 900_000, 8_000_000),
    ('Booking.com', 'TRAVEL', 1_500_000, 18_000_000),
    ('Agoda', 'TRAVEL', 1_200_000, 14_000_000),
    ('VUS English Center', 'EDUCATION', 2_000_000, 8_000_000),
    ('ILA Vietnam', 'EDUCATION', 2_200_000, 9_000_000),
    ('CGV Cinema', 'ENTERTAINMENT', 90_000, 380_000),
    ('Galaxy Cinema', 'ENTERTAINMENT', 85_000, 360_000),
    ('Sendo', 'ECOMMERCE', 100_000, 3_000_000),
]

TODAY = date(2026, 6, 20)
PERIOD_START = date(2025, 6, 20)

# ── Helpers ───────────────────────────────────────────────────────────────────

def rand_date(start: date, end: date) -> date:
    if start >= end:
        return start
    return start + timedelta(days=random.randint(0, (end - start).days))

def weighted_choice(items_weights):
    items  = [x[0] for x in items_weights]
    weights = [x[1] for x in items_weights]
    return random.choices(items, weights=weights)[0]

def save_json(data, filename):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    count = len(data) if isinstance(data, list) else len(data)
    print(f"  ✓ {filename}  ({count} records)")

# ── Generators ────────────────────────────────────────────────────────────────

def generate_reps(n=10):
    rep_roster = [
        ('Trần Minh Tuấn', 'M', 'Chi nhánh Quận 1'),
        ('Lê Thị Hương',   'F', 'Chi nhánh Hoàn Kiếm'),
        ('Phạm Văn Đức',   'M', 'Chi nhánh Hải Châu'),
        ('Nguyễn Thu Hà',  'F', 'Chi nhánh Ninh Kiều'),
        ('Hoàng Quang Huy','M', 'Chi nhánh Lê Chân'),
        ('Vũ Ngọc Anh',    'F', 'Chi nhánh Quận 3'),
        ('Đặng Thành Long','M', 'Chi nhánh Ba Đình'),
        ('Bùi Thị Lan',    'F', 'Chi nhánh Thanh Khê'),
        ('Ngô Tiến Dũng',  'M', 'Chi nhánh Bình Thạnh'),
        ('Hồ Kim Ngân',    'F', 'Chi nhánh Cầu Giấy'),
    ]
    return [
        {
            "rep_id":    f"REP-{str(i+1).zfill(3)}",
            "full_name": name,
            "gender":    gender,
            "email":     f"rep{str(i+1).zfill(3)}@tcb.com.vn",
            "phone":     f"090{random.randint(1000000, 9999999)}",
            "branch":    branch,
            "active":    True
        }
        for i, (name, gender, branch) in enumerate(rep_roster[:n])
    ]


def generate_customers(n=100):
    segments = SEGMENT_DIST[:n]
    random.shuffle(segments)
    customers = []

    for i in range(n):
        gender  = random.choice(['M', 'F'])
        surname = random.choice(SURNAMES)
        middle  = random.choice(MALE_MIDDLE if gender == 'M' else FEMALE_MIDDLE)
        given   = random.choice(MALE_GIVEN  if gender == 'M' else FEMALE_GIVEN)
        segment = segments[i]

        birth_year = {
            'Standard': random.randint(1990, 2002),
            'Gold':     random.randint(1980, 1995),
            'Platinum': random.randint(1972, 1990),
            'Elite':    random.randint(1965, 1982),
        }[segment]

        dob = rand_date(date(birth_year, 1, 1), date(birth_year, 12, 31))

        cs_min, cs_max = CREDIT_SCORE_RANGE[segment]
        lp_range = {
            'Standard': (500,   5_000),
            'Gold':     (5_000, 20_000),
            'Platinum': (20_000,80_000),
            'Elite':    (80_000,200_000)
        }[segment]

        yr_min, yr_max = {'Standard':(1,3),'Gold':(2,6),'Platinum':(3,8),'Elite':(5,10)}[segment]
        years_back = random.randint(yr_min, yr_max)
        rel_since  = rand_date(date(2026 - years_back, 1, 1), date(2026 - years_back, 12, 31))

        customers.append({
            "customer_id":        f"CUST-{str(i+1).zfill(3)}",
            "full_name":          f"{surname} {middle} {given}",
            "date_of_birth":      dob.isoformat(),
            "gender":             gender,
            "phone":              f"0{random.choice(['9','8'])}{random.randint(10000000,99999999)}",
            "email":              f"khach{str(i+1).zfill(3)}@gmail.com",
            "national_id":        f"{random.randint(79, 96):03d}{random.randint(100000000,999999999)}",
            "city":               weighted_choice(CITIES),
            "occupation":         random.choice(OCCUPATIONS),
            "income_range":       random.choice(INCOME_RANGE[segment]),
            "segment":            segment,
            "kyc_status":         random.choices(['Verified','Pending','Expired'], weights=[0.85,0.10,0.05])[0],
            "credit_score":       random.randint(cs_min, cs_max),
            "loyalty_points":     random.randint(*lp_range),
            "relationship_since": rel_since.isoformat(),
            "assigned_rep_id":    f"REP-{str((i % 10) + 1).zfill(3)}"
        })

    return customers


def assign_portfolio(customers):
    portfolio = {}
    for c in customers:
        seg = c['segment']
        cid = c['customer_id']
        products = ['CASA']

        # Credit card — tier by segment
        cc_prob = {'Standard': 0.40, 'Gold': 0.70, 'Platinum': 0.85, 'Elite': 1.0}
        if random.random() < cc_prob[seg]:
            if seg == 'Standard':
                products.append('CREDIT_GOLD')
            elif seg == 'Gold':
                products.append(random.choices(['CREDIT_GOLD', 'CREDIT_PLATINUM'], weights=[0.80, 0.20])[0])
            elif seg == 'Platinum':
                products.append(random.choices(['CREDIT_PLATINUM', 'CREDIT_GOLD'], weights=[0.80, 0.20])[0])
            else:
                products.append(random.choices(['CREDIT_ELITE', 'CREDIT_PLATINUM'], weights=[0.70, 0.30])[0])

        # Term deposit
        if random.random() < {'Standard':0.20,'Gold':0.35,'Platinum':0.55,'Elite':0.70}[seg]:
            products.append(random.choice(['TERM_DEPOSIT_STD', 'TERM_DEPOSIT_PLUS']))

        # Personal loan
        if random.random() < {'Standard':0.35,'Gold':0.30,'Platinum':0.20,'Elite':0.10}[seg]:
            products.append('PERSONAL_LOAN')

        # Home loan
        if random.random() < {'Standard':0.05,'Gold':0.15,'Platinum':0.25,'Elite':0.20}[seg]:
            products.append('HOME_LOAN')

        # Banca (key product for contract reasoning tests)
        if random.random() < {'Standard':0.10,'Gold':0.28,'Platinum':0.45,'Elite':0.65}[seg]:
            products.append(random.choice(['BANCA_LIFE', 'BANCA_WEALTH']))

        # Non-life insurance
        if random.random() < {'Standard':0.10,'Gold':0.20,'Platinum':0.32,'Elite':0.45}[seg]:
            products.append(random.choice(['TRAVEL_INSURANCE', 'ACCIDENT_INSURANCE']))

        # Certificate of deposit
        if random.random() < {'Standard':0.05,'Gold':0.10,'Platinum':0.18,'Elite':0.35}[seg]:
            products.append('CERT_DEPOSIT')

        # Business lending
        if random.random() < {'Standard':0.02,'Gold':0.08,'Platinum':0.15,'Elite':0.30}[seg]:
            products.append('BUSINESS_LENDING')

        portfolio[cid] = products

    return portfolio


def build_contracts(customers, portfolio):
    contracts = []
    cust_map  = {c['customer_id']: c for c in customers}
    ctr       = 1

    for cust_id, prod_keys in portfolio.items():
        cust = cust_map[cust_id]
        seg  = cust['segment']
        rel_since = date.fromisoformat(cust['relationship_since'])

        for pk in prod_keys:
            prod = PRODUCTS[pk]
            pt   = prod['product_type']
            cid  = f"{pt[:3]}-{cust_id[5:]}-{str(ctr).zfill(4)}"
            ctr += 1

            earliest = max(rel_since, date(2020, 1, 1))
            start    = rand_date(earliest, TODAY - timedelta(days=60))

            base = {
                "contract_id":   cid,
                "customer_id":   cust_id,
                "product_type":  pt,
                "product_id":    prod['product_id'],
                "product_name":  prod['product_name'],
                "status":        "ACTIVE",
                "start_date":    start.isoformat(),
                "end_date":      None,
                "key_amount":    0,
                "key_rate":      None,
                "extra_fields":  {},
                "clauses":       [],
                "coverages":     [],
                "benefits":      []
            }

            # ── CASA ─────────────────────────────────────────────────────────
            if pk == 'CASA':
                bal = random.randint(5_000_000, 200_000_000)
                if seg in ('Platinum', 'Elite'):
                    bal = random.randint(100_000_000, 1_500_000_000)
                base['key_amount']  = bal
                base['extra_fields'] = {
                    "account_number": f"TCB{random.randint(10000000000,99999999999)}",
                    "account_type":   "PAYMENT",
                    "current_balance": bal,
                    "daily_limit":    50_000_000 if seg == 'Standard' else 200_000_000
                }

            # ── Credit Card ───────────────────────────────────────────────────
            elif pk in ('CREDIT_GOLD', 'CREDIT_PLATINUM', 'CREDIT_ELITE'):
                limit = prod['credit_limit']
                tier  = prod['tier']
                base['end_date']    = (start + timedelta(days=365*3)).isoformat()
                base['key_amount']  = limit
                base['extra_fields'] = {
                    "tier":                tier,
                    "credit_limit":        limit,
                    "statement_date":      random.randint(1, 25),
                    "payment_due_days":    45,
                    "current_outstanding": random.randint(0, int(limit * 0.55))
                }
                if tier == 'GOLD':
                    base['benefits'] = [
                        {"benefit_type": "CASHBACK",     "description": "Hoàn tiền 1.5% mọi giao dịch, 3x điểm ăn uống & mua sắm"},
                        {"benefit_type": "LOUNGE_ACCESS","description": "2 lượt phòng chờ sân bay nội địa / năm"}
                    ]
                elif tier == 'PLATINUM':
                    base['benefits'] = [
                        {"benefit_type": "CASHBACK",        "description": "Hoàn tiền 2% mọi giao dịch, 5x điểm du lịch & ăn uống"},
                        {"benefit_type": "LOUNGE_ACCESS",   "description": "Không giới hạn phòng chờ sân bay nội địa"},
                        {"benefit_type": "TRAVEL_INSURANCE","description": "Bảo hiểm du lịch miễn phí đến 500,000,000 VND"},
                        {"benefit_type": "GOLF",            "description": "2 lượt chơi golf / tháng tại các sân đối tác"}
                    ]
                else:
                    base['benefits'] = [
                        {"benefit_type": "CASHBACK",     "description": "Hoàn tiền 3% mọi giao dịch, 10x điểm chi tiêu cao cấp"},
                        {"benefit_type": "LOUNGE_ACCESS","description": "Priority Pass — không giới hạn, hơn 1,300 phòng chờ quốc tế"},
                        {"benefit_type": "CONCIERGE",    "description": "Dịch vụ concierge cá nhân 24/7"},
                        {"benefit_type": "GOLF",         "description": "4 lượt golf / tháng — sân cao cấp trong và ngoài nước"},
                        {"benefit_type": "INSURANCE",    "description": "Bảo hiểm toàn cầu đến 2,000,000,000 VND"}
                    ]

            # ── Banca ─────────────────────────────────────────────────────────
            elif pk in ('BANCA_LIFE', 'BANCA_WEALTH'):
                annual_premium = random.choice([3_000_000, 5_000_000, 8_000_000, 10_000_000, 15_000_000])
                if seg in ('Platinum', 'Elite'):
                    annual_premium = random.choice([15_000_000, 20_000_000, 30_000_000])
                sum_assured = annual_premium * random.randint(40, 100)
                tenor_years = random.choice([5, 10, 15, 20])
                end = start + timedelta(days=365 * tenor_years)
                continuous_months = (TODAY - start).days // 30

                # Key test: qualifies for VIP medical if >= 12 months + Gold+
                qualifies = continuous_months >= 12 and seg in ('Gold', 'Platinum', 'Elite')

                base['end_date']   = end.isoformat()
                base['key_amount'] = annual_premium
                base['extra_fields'] = {
                    "annual_premium":    annual_premium,
                    "sum_assured":       sum_assured,
                    "tenor_years":       tenor_years,
                    "continuous_months": continuous_months,
                    "premium_frequency": random.choice(["ANNUAL","SEMI_ANNUAL","QUARTERLY"]),
                    "beneficiary":       random.choice(["Vợ/chồng","Con cái","Cha mẹ"]),
                    "insurer":           prod.get('insurer', 'Prudential Vietnam')
                }
                base['clauses'] = [
                    {
                        "clause_id":     f"CL-{cid}-5-1",
                        "clause_number": "5.1",
                        "title":         "Phạm vi bảo hiểm cơ bản",
                        "conditions":    "Hợp đồng còn hiệu lực và phí bảo hiểm đã thanh toán đầy đủ",
                        "benefit":       "Bảo hiểm tử vong và thương tật toàn bộ vĩnh viễn (TPDB)"
                    },
                    {
                        "clause_id":                    f"CL-{cid}-7-3",
                        "clause_number":                "7.3",
                        "title":                        "Quyền lợi y tế VIP khi du lịch nước ngoài",
                        "conditions":                   "Hợp đồng liên tục >= 12 tháng VÀ phân khúc khách hàng Gold/Platinum/Elite",
                        "benefit":                      "Bồi thường chi phí y tế khẩn cấp tối đa 25,000,000 VND (tương đương ~1,000 USD) khi điều trị ở nước ngoài",
                        "customer_qualifies":           qualifies,
                        "continuous_months_required":   12,
                        "customer_continuous_months":   continuous_months,
                        "disqualification_reason":      None if qualifies else (
                            "Chưa đủ 12 tháng liên tục" if continuous_months < 12
                            else "Phân khúc khách hàng không đủ điều kiện (yêu cầu Gold trở lên)"
                        )
                    },
                    {
                        "clause_id":     f"CL-{cid}-9-1",
                        "clause_number": "9.1",
                        "title":         "Điều khoản loại trừ chung",
                        "conditions":    None,
                        "benefit":       None
                    }
                ]
                base['coverages'] = [
                    {
                        "coverage_id":   f"COV-{cid}-LIFE",
                        "coverage_type": "LIFE",
                        "limit_amount":  sum_assured,
                        "conditions":    "Tử vong do bất kỳ nguyên nhân (trừ điều khoản 9.1)"
                    },
                    {
                        "coverage_id":   f"COV-{cid}-MED-TRAVEL",
                        "coverage_type": "MEDICAL_TRAVEL",
                        "limit_amount":  25_000_000,
                        "conditions":    "Điều trị y tế khẩn cấp ngoài lãnh thổ Việt Nam. Không áp dụng bệnh có sẵn."
                    }
                ]

            # ── Term Deposit ──────────────────────────────────────────────────
            elif pk in ('TERM_DEPOSIT_STD', 'TERM_DEPOSIT_PLUS'):
                principal = random.choice([50,100,200,300,500]) * 1_000_000
                if seg in ('Platinum','Elite'):
                    principal *= random.randint(2, 6)
                tenor = random.choice([1, 3, 6, 12, 24])
                rate  = {1:4.0, 3:4.5, 6:5.5, 12:7.0, 24:7.5}[tenor]
                if pk == 'TERM_DEPOSIT_PLUS':
                    rate += 0.3
                maturity = start + timedelta(days=30 * tenor)
                base['end_date']   = maturity.isoformat()
                base['key_amount'] = principal
                base['key_rate']   = rate
                base['extra_fields'] = {
                    "principal":          principal,
                    "interest_rate_pct":  rate,
                    "tenor_months":       tenor,
                    "maturity_date":      maturity.isoformat(),
                    "rollover":           random.choice(["AUTO_PRINCIPAL","AUTO_FULL","NO_ROLLOVER"]),
                    "interest_payment":   "AT_MATURITY" if tenor <= 6 else "MONTHLY"
                }

            # ── Personal Loan ─────────────────────────────────────────────────
            elif pk == 'PERSONAL_LOAN':
                orig   = random.choice([50,100,150,200,300]) * 1_000_000
                tenor  = random.choice([24, 36, 48, 60])
                rate   = round(random.uniform(10.5, 14.5), 2)
                elapsed = max(0, (TODAY - start).days // 30)
                rem    = max(0, tenor - elapsed)
                outstanding = int(orig * rem / tenor)
                monthly     = int(orig / tenor * (1 + rate/100/12 * tenor))
                end    = start + timedelta(days=30 * tenor)
                base['end_date']   = end.isoformat()
                base['key_amount'] = orig
                base['key_rate']   = rate
                base['extra_fields'] = {
                    "original_amount":    orig,
                    "outstanding_balance":outstanding,
                    "monthly_payment":    monthly,
                    "interest_rate_pct":  rate,
                    "tenor_months":       tenor,
                    "remaining_months":   rem,
                    "purpose":            random.choice(["Mua xe","Tiêu dùng","Học tập","Y tế","Du lịch","Sửa nhà"])
                }

            # ── Home Loan ─────────────────────────────────────────────────────
            elif pk == 'HOME_LOAN':
                orig   = random.choice([500,800,1000,1500,2000,3000]) * 1_000_000
                tenor  = random.choice([120, 180, 240, 300])
                rate   = round(random.uniform(8.5, 11.5), 2)
                elapsed = max(0, (TODAY - start).days // 30)
                rem    = max(0, tenor - elapsed)
                outstanding = int(orig * rem / tenor)
                monthly     = int(orig / tenor * (1 + rate/100/12 * tenor))
                end    = start + timedelta(days=30 * tenor)
                base['end_date']   = end.isoformat()
                base['key_amount'] = orig
                base['key_rate']   = rate
                base['extra_fields'] = {
                    "original_amount":    orig,
                    "outstanding_balance":outstanding,
                    "monthly_payment":    monthly,
                    "interest_rate_pct":  rate,
                    "tenor_months":       tenor,
                    "remaining_months":   rem,
                    "property_type":      random.choice(["Căn hộ chung cư","Nhà phố","Đất nền","Biệt thự"]),
                    "fixed_period_months":random.choice([12, 24, 36]),
                    "collateral_value":   int(orig * random.uniform(1.2, 1.8))
                }

            # ── Certificate of Deposit ────────────────────────────────────────
            elif pk == 'CERT_DEPOSIT':
                amount = random.choice([100,200,500,1000]) * 1_000_000
                tenor  = random.choice([6, 12, 24, 36])
                rate   = {6:6.5, 12:7.8, 24:8.0, 36:8.2}[tenor]
                maturity = start + timedelta(days=30 * tenor)
                base['end_date']   = maturity.isoformat()
                base['key_amount'] = amount
                base['key_rate']   = rate
                base['extra_fields'] = {
                    "amount":                        amount,
                    "interest_rate_pct":             rate,
                    "tenor_months":                  tenor,
                    "maturity_date":                 maturity.isoformat(),
                    "early_redemption_penalty_pct":  1.5,
                    "transferable":                  False
                }

            # ── Non-life Insurance ────────────────────────────────────────────
            elif pk in ('TRAVEL_INSURANCE', 'ACCIDENT_INSURANCE'):
                premium    = random.choice([500_000, 1_000_000, 2_000_000, 3_000_000])
                sum_insured = premium * random.randint(50, 200)
                days = 365 if pk == 'ACCIDENT_INSURANCE' else random.choice([7,14,30,365])
                end  = start + timedelta(days=days)
                base['end_date']   = end.isoformat()
                base['key_amount'] = premium
                base['extra_fields'] = {
                    "premium":       premium,
                    "sum_insured":   sum_insured,
                    "coverage_type": "TRAVEL" if pk == 'TRAVEL_INSURANCE' else "PERSONAL_ACCIDENT",
                    "coverage_days": days
                }
                base['coverages'] = [
                    {
                        "coverage_id":   f"COV-{cid}-MAIN",
                        "coverage_type": "TRAVEL_MEDICAL" if pk == 'TRAVEL_INSURANCE' else "PERSONAL_ACCIDENT",
                        "limit_amount":  sum_insured,
                        "conditions":    "Theo điều khoản hợp đồng bảo hiểm"
                    }
                ]

            # ── Business Lending ──────────────────────────────────────────────
            elif pk == 'BUSINESS_LENDING':
                facility = random.choice([500,1000,2000,3000,5000]) * 1_000_000
                drawn    = int(facility * random.uniform(0.30, 0.85))
                rate     = round(random.uniform(9.0, 13.0), 2)
                end      = start + timedelta(days=365 * random.choice([1, 2, 3]))
                base['end_date']   = end.isoformat()
                base['key_amount'] = facility
                base['key_rate']   = rate
                base['extra_fields'] = {
                    "facility_amount":  facility,
                    "drawn_amount":     drawn,
                    "available_amount": facility - drawn,
                    "interest_rate_pct":rate,
                    "facility_type":    random.choice(["REVOLVING","TERM"]),
                    "collateral_type":  random.choice(["Bất động sản","Máy móc thiết bị","Hàng tồn kho"])
                }

            contracts.append(base)

    return contracts


def generate_transactions(customers, portfolio):
    transactions = []
    ctr = 1
    txn_count = {
        'Standard': (40,  65),
        'Gold':     (65,  95),
        'Platinum': (90, 135),
        'Elite':    (120, 180)
    }
    amount_multiplier = {'Standard': 1.0, 'Gold': 1.8, 'Platinum': 4.0, 'Elite': 9.0}

    for cust in customers:
        cid = cust['customer_id']
        seg = cust['segment']
        n_min, n_max = txn_count[seg]
        n = random.randint(n_min, n_max)
        mult = amount_multiplier[seg]

        for _ in range(n):
            txn_date = rand_date(PERIOD_START, TODAY)
            merchant, category, mn, mx = random.choice(MERCHANTS)
            amount = int(random.randint(mn, mx) * random.uniform(0.8, 1.2) * mult)

            transactions.append({
                "transaction_id":   f"TXN-{str(ctr).zfill(6)}",
                "customer_id":      cid,
                "transaction_date": f"{txn_date.isoformat()}T{random.randint(6,22):02d}:{random.randint(0,59):02d}:00",
                "amount":           amount,
                "type":             "DEBIT",
                "merchant_name":    merchant,
                "merchant_category":category,
                "channel":          random.choices(["ONLINE","POS","ATM","TRANSFER"],
                                                    weights=[0.45,0.30,0.15,0.10])[0],
                "account_id":       f"ACC-{cid}-001",
                "description":      f"{merchant} - Giao dịch",
                "status":           random.choices(["COMPLETED","PENDING","FAILED"],
                                                    weights=[0.92,0.05,0.03])[0],
                "currency":         "VND"
            })
            ctr += 1

        # Monthly salary credit (12 months)
        salary = {
            'Standard': random.randint(8_000_000,  20_000_000),
            'Gold':     random.randint(20_000_000, 50_000_000),
            'Platinum': random.randint(50_000_000, 150_000_000),
            'Elite':    random.randint(150_000_000,500_000_000)
        }[seg]

        for m in range(12):
            s_date = TODAY - timedelta(days=30 * m)
            if s_date >= PERIOD_START:
                transactions.append({
                    "transaction_id":   f"TXN-{str(ctr).zfill(6)}",
                    "customer_id":      cid,
                    "transaction_date": f"{s_date.isoformat()}T09:00:00",
                    "amount":           salary + random.randint(-500_000, 500_000),
                    "type":             "CREDIT",
                    "merchant_name":    "Lương tháng",
                    "merchant_category":"SALARY",
                    "channel":          "TRANSFER",
                    "account_id":       f"ACC-{cid}-001",
                    "description":      f"Lương tháng {s_date.strftime('%m/%Y')}",
                    "status":           "COMPLETED",
                    "currency":         "VND"
                })
                ctr += 1

    return transactions


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("Generating AI FrontLine Agent dummy data...\n")

    reps         = generate_reps(10)
    customers    = generate_customers(100)
    portfolio    = assign_portfolio(customers)
    contracts    = build_contracts(customers, portfolio)
    transactions = generate_transactions(customers, portfolio)

    save_json(reps,         "reps.json")
    save_json(customers,    "customers.json")
    save_json(portfolio,    "product_portfolio.json")
    save_json(contracts,    "contracts.json")
    save_json(transactions, "transactions.json")

    # Stats
    banca_count     = sum(1 for c in contracts if c['product_type'] == 'BANCASSURANCE')
    qualifies_count = sum(
        1 for c in contracts
        if c['product_type'] == 'BANCASSURANCE'
        for cl in c['clauses']
        if cl['clause_number'] == '7.3' and cl.get('customer_qualifies')
    )

    print(f"\nSummary:")
    print(f"  Reps:              {len(reps)}")
    print(f"  Customers:         {len(customers)}")
    print(f"  Product holdings:  {sum(len(v) for v in portfolio.values())}")
    print(f"  Contracts:         {len(contracts)}")
    print(f"  Transactions:      {len(transactions)}")
    print(f"  Banca contracts:   {banca_count}")
    print(f"  Qualify VIP (7.3): {qualifies_count} / {banca_count}")
    print(f"\nOutput → {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
