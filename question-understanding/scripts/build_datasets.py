"""Write the evidence stores in datasets/. Values come from the reports read by hand; S1 and S2 from their generators."""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "datasets"
OUT.mkdir(exist_ok=True)


class Doc:
    def __init__(self, code, file_name, pages):
        self.code, self.file_name, self.pages, self.items = code, file_name, pages, []
        self.count = 0

    def add(self, series, period, value, unit, page, source="table_cell", method=None, status=None, text=None, revises=None, code=None):
        self.count += 1
        if method is None:
            method = "none" if value is None and not text else "direct_label"
        if status is None:
            status = "missing" if value is None and not text else "valid"
        meta = {"revises": f"EVD_{revises}"} if revises else {}
        self.items.append({
            "evidence_code": f"EVD_{code or self.count:0>4}" if not code else f"EVD_{code}",
            "source_type": source, "extraction_method": method,
            "location": {"page": page, "bbox": [50.0, 100.0 + 12 * (self.count % 40), 300.0, 112.0 + 12 * (self.count % 40)], "meta": meta},
            "series_name": series, "time_period": period, "unit": unit,
            "raw_value": value, "current_value": value, "text_content": text,
            "data_status": status, "verification_status": "unverified"})

    def note(self, name, text, page):
        self.add(name, "", None, "text", page, source="text_paragraph", method="direct_label", text=text)

    def write(self, name):
        data = {"document_code": self.code, "file_name": self.file_name, "page_count": self.pages, "evidences": self.items}
        (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def s1():
    d = Doc("S1_HUONG_LUA", "S1-huong-lua.pdf", 3)
    Q1, Q2 = "Quý 1/2026", "Quý 2/2026"
    table = {"Miền Bắc": (18240, 21350, 5290, 6405), "Miền Trung": (8120, 9860, None, 2760), "Miền Nam": (15930, 17420, 4620, 5050),
             "Xuất khẩu": (0, 1250, 0, 310), "Tổng": (42290, 49880, None, 14525)}
    for region, (a, b, c, e) in table.items():
        d.add(f"Doanh thu thuần - {region}", Q1, a, "triệu đồng", 1)
        d.add(f"Doanh thu thuần - {region}", Q2, b, "triệu đồng", 1)
        d.add(f"Lợi nhuận gộp - {region}", Q1, c, "triệu đồng", 1)
        d.add(f"Lợi nhuận gộp - {region}", Q2, e, "triệu đồng", 1)
    d.note("Định nghĩa Doanh thu thuần", "Doanh thu thuần là doanh thu bán hàng chưa gồm thuế GTGT, sau khi trừ chiết khấu thương mại và hàng bán bị trả lại.", 1)
    d.note("Định nghĩa Lợi nhuận gộp", "Lợi nhuận gộp bằng doanh thu thuần trừ giá vốn hàng bán.", 1)
    d.note("Định nghĩa Biên lợi nhuận gộp", "Biên lợi nhuận gộp bằng lợi nhuận gộp chia cho doanh thu thuần.", 1)
    d.note("Định nghĩa Khách hàng hoạt động", "Khách hàng hoạt động là khách hàng có ít nhất một đơn hàng thành công trong tháng.", 1)
    d.note("Định nghĩa Tỷ lệ khách hàng quay lại", "Tỷ lệ khách hàng quay lại là tỷ lệ phần trăm khách hàng hoạt động của tháng đã từng mua hàng trước tháng đó.", 1)
    d.add("Thuế suất GTGT", "", 8, "%", 1, source="text_paragraph")
    d.add("Tỷ trọng kênh trực tuyến - Miền Nam", Q2, 31, "%", 1, source="text_paragraph")
    d.add("Chi phí vận chuyển trên doanh thu thuần", Q2, 6.5, "%", 1, source="text_paragraph")
    d.add("Mục tiêu doanh thu thuần", "Năm 2026", 220, "tỷ đồng", 1, source="text_paragraph")
    d.add("Khách hàng hoạt động", "Tháng 6/2026", 128.4, "nghìn khách hàng", 2, source="text_paragraph")
    orders = {"Miền Bắc": [38, 35, 41, 44, 49, 47], "Miền Trung": [17, 15, 19, 21, 24, 30], "Miền Nam": [33, 30, 36, 35, 37, 38]}
    for region, values in orders.items():
        for month, value in enumerate(values, 1):
            d.add(f"Số đơn hàng - {region}", f"Tháng {month}/2026", value, "nghìn đơn", 2, source="chart_bar")
    d.add("Số đơn hàng - Miền Trung", "Tháng 6/2026", 33, "nghìn đơn", 2, source="text_paragraph")
    for region, (a, b) in {"Miền Bắc": (64, 68), "Miền Trung": (27, 31), "Miền Nam": (52, 55)}.items():
        d.add(f"Số cửa hàng - {region}", "Cuối quý 1/2026", a, "cửa hàng", 2)
        d.add(f"Số cửa hàng - {region}", "Cuối quý 2/2026", b, "cửa hàng", 2)
    rate = {"2025": [36, 34, 37, 38, 39, 40], "2026": [39, 38, 42, 44, 46, 48]}
    for year, values in rate.items():
        for month, value in enumerate(values, 1):
            d.add("Tỷ lệ khách hàng quay lại", f"Tháng {month}/{year}", value, "%", 3, source="chart_line", method="axis_estimation")
    d.write("S1")


def s2():
    d = Doc("S2_LOGISTICS", "S2-logistics-bac-nam-scan.pdf", 4)
    table = {"Đường bộ": (152340, 160215, 171560, 484115, 431900), "Đường biển": (101870, 108430, 119725, 330025, 301480),
             "Đường sắt": (4905, 4813, 5632, 15350, 13240), "Tổng": (259115, 273458, 296917, 829490, 746620)}
    for mode, row in table.items():
        for period, value in zip(("Quý 1/2026", "Quý 2/2026", "Quý 3/2026", "9 tháng 2026", "9 tháng 2025"), row):
            code = {("Đường sắt", "Quý 2/2026"): "RAIL_Q2_PRELIM", ("Đường sắt", "9 tháng 2026"): "RAIL_9M_PRELIM", ("Tổng", "9 tháng 2026"): "TOTAL_9M_PRELIM", ("Tổng", "Quý 2/2026"): "TOTAL_Q2_PRELIM"}.get((mode, period))
            d.add(f"Doanh thu thuần - {mode}", period, value, "triệu đồng", 1, code=code)
    d.add("Doanh thu thuần - Đường sắt", "Quý 2/2026", 4318, "triệu đồng", 2, source="text_paragraph", revises="RAIL_Q2_PRELIM", code="RAIL_Q2")
    d.add("Doanh thu thuần - Đường sắt", "9 tháng 2026", 14855, "triệu đồng", 2, source="text_paragraph", revises="RAIL_9M_PRELIM", method="direct_label", code="RAIL_9M")
    d.add("Doanh thu thuần - Tổng", "Quý 2/2026", 272963, "triệu đồng", 2, source="text_paragraph", revises="TOTAL_Q2_PRELIM", code="TOTAL_Q2")
    d.add("Doanh thu thuần - Tổng", "9 tháng 2026", 828995, "triệu đồng", 2, source="text_paragraph", revises="TOTAL_9M_PRELIM", code="TOTAL_9M")
    d.note("Định nghĩa Doanh thu thuần", "Doanh thu thuần chưa gồm thuế GTGT.", 1)
    d.note("Định nghĩa Tỷ lệ giao hàng đúng hạn", "Tỷ lệ giao hàng đúng hạn là số lô hàng giao không muộn hơn thời điểm cam kết trong hợp đồng, chia cho tổng số lô hàng đã giao trong tháng.", 1)
    d.add("Thuế suất GTGT", "", 10, "%", 1, source="text_paragraph")
    d.add("Kế hoạch doanh thu thuần", "Năm 2026", 1.25, "nghìn tỷ đồng", 1, source="text_paragraph")
    quarters = ["Quý 1/2025", "Quý 2/2025", "Quý 3/2025", "Quý 4/2025", "Quý 1/2026", "Quý 2/2026", "Quý 3/2026"]
    for quarter, rev, gpm in zip(quarters, [236.1, 248.0, 262.5, 281.4, 259.1, 273.0, 296.9], [17.2, 16.4, 18.1, 19.6, 15.3, 16.9, 18.8]):
        d.add("Doanh thu thuần theo quý", quarter, rev, "tỷ đồng", 1, source="chart_bar", method="axis_estimation")
        d.add("Biên lợi nhuận gộp", quarter, gpm, "%", 1, source="chart_line", method="axis_estimation")
    ontime = {"Đường sắt": [95.1, 94.0, 90.2, 88.5, 90.0, 89.2, 87.6, 90.4, 91.0], "Đường bộ": [91.2, 89.5, 92.0, 93.1, 94.0, 92.6, 90.8, 91.5, 93.4],
              "Đường biển": [84.0, 86.5, 88.2, 87.0, 89.6, 91.8, 93.0, 92.1, 94.2]}
    for mode, values in ontime.items():
        for month, value in enumerate(values, 1):
            d.add(f"Tỷ lệ giao hàng đúng hạn - {mode}", f"Tháng {month}/2026", value, "%", 3, source="chart_line", method="axis_estimation")
    routes = {"Hà Nội – TP. Hồ Chí Minh": (312.4, 290.1, 3), "Hải Phòng – Hà Nội": (185.6, 170.2, 3), "TP. Hồ Chí Minh – Cần Thơ": (142.8, 150.5, 3),
              "Đà Nẵng – TP. Hồ Chí Minh": (98.3, 88.0, 3), "Hải Phòng – Quảng Ninh": (76.5, 71.9, 3), "Hà Nội – Lào Cai": (54.2, 49.8, 4),
              "Cái Mép – TP. Hồ Chí Minh": (412.6, 365.0, 4), "TP. Hồ Chí Minh – Phnom Penh": (2.2, None, 4), "Tổng": (1284.6, 1185.5, 4)}
    for route, (a, b, page) in routes.items():
        d.add(f"Sản lượng - {route}", "9 tháng 2026", a, "nghìn tấn", page)
        d.add(f"Sản lượng - {route}", "9 tháng 2025", b, "nghìn tấn", page)
    for client, value in {"A": 109.4, "B": 72.6, "C": 51.2, "D": 38.5, "E": 30.1, "Cộng 5 khách hàng": 301.8}.items():
        name = f"Khách hàng {client}" if len(client) == 1 else client
        d.add(f"Doanh thu đã gồm GTGT - {name}", "9 tháng 2026", value, "tỷ đồng", 4)
    d.add("Tỷ trọng doanh thu thuần - Khách hàng A", "9 tháng 2026", 12, "%", 4, source="text_paragraph")
    d.write("S2")


def r1():
    d = Doc("R1_DSC_HPG", "R1-dsc-hpg-q2-2026.pdf", 5)
    d.add("Doanh thu thuần", "Quý 2/2025", 35911, "tỷ đồng", 1)
    d.add("Doanh thu thuần", "Quý 2/2026", 55159, "tỷ đồng", 1)
    d.add("Doanh thu thuần", "Quý 2/2026", 55557, "tỷ đồng", 2, source="text_paragraph")
    d.add("Doanh thu thuần dự phóng", "Năm 2026", 199829, "tỷ đồng", 1)
    d.add("Doanh thu thuần lũy kế", "6 tháng 2026", 108060, "tỷ đồng", 1, source="text_paragraph")
    d.add("Doanh thu thuần lũy kế", "6 tháng 2026", 108870, "tỷ đồng", 2, source="text_paragraph")
    d.add("Lợi nhuận sau thuế", "Quý 2/2026", 6425, "tỷ đồng", 1, source="text_paragraph")
    d.add("Lợi nhuận sau thuế", "Quý 2/2026", 6424, "tỷ đồng", 2, source="text_paragraph")
    d.add("Tăng trưởng lợi nhuận sau thuế so với cùng kỳ", "Quý 2/2026", 51, "%", 1, source="text_paragraph")
    d.add("Lợi nhuận sau thuế lũy kế", "6 tháng 2026", 15480, "tỷ đồng", 1, source="text_paragraph")
    d.add("Lợi nhuận sau thuế lũy kế", "6 tháng 2026", 15365, "tỷ đồng", 1, source="text_paragraph")
    d.add("Lợi nhuận sau thuế cổ đông công ty mẹ", "Quý 2/2025", 4257, "tỷ đồng", 1)
    d.add("Lợi nhuận sau thuế cổ đông công ty mẹ", "Quý 2/2026", 6371, "tỷ đồng", 1)
    d.add("Lợi nhuận sau thuế cổ đông công ty mẹ dự phóng", "Năm 2026", 23329, "tỷ đồng", 1)
    quarters = ["Quý 3/2024", "Quý 4/2024", "Quý 1/2025", "Quý 2/2025", "Quý 3/2025", "Quý 4/2025", "Quý 1/2026", "Quý 2/2026"]
    series = {"Biên lợi nhuận gộp": ([13.9, 12.7, 14.4, 18.4, 16.7, 13.9, 15.8, 19.0], "%", "chart_line"), "Biên lợi nhuận trước thuế": ([10, 9.5, 10.2, 13.8, 12.7, 10, 20.3, 13], "%", "chart_line"),
              "Số ngày tồn kho": ([112, 123, 130, 134, 128, 138, 114, 120], "ngày", "chart_line"), "Tăng trưởng lợi nhuận trước thuế so với cùng kỳ": ([56.9, -2.9, 17.7, 33.2, 35.6, 40, 180.3, 44.5], "%", "chart_line")}
    for name, (values, unit, source) in series.items():
        for quarter, value in zip(quarters, values):
            d.add(name, quarter, value, unit, 2, source=source)
    d.add("Sản lượng tiêu thụ - Ống thép", "Quý 2/2026", 212000, "tấn", 2, source="text_paragraph")
    d.add("Sản lượng tiêu thụ - Tôn mạ", "Quý 2/2026", 83000, "tấn", 2, source="text_paragraph")
    d.add("Sản lượng tiêu thụ - Thép xây dựng", "Quý 2/2026", 1.308, "triệu tấn", 2, source="text_paragraph")
    d.add("Sản lượng - HRC", "Quý 2/2026", 1.9, "triệu tấn", 1, source="text_paragraph")
    d.add("Tăng trưởng sản lượng HRC so với cùng kỳ", "Quý 2/2026", 64, "%", 1, source="text_paragraph")
    d.add("Doanh thu mảng nông nghiệp", "Quý 2/2026", 1523, "tỷ đồng", 2, source="text_paragraph")
    d.add("Hàng tồn kho", "Quý 2/2026", 55608, "tỷ đồng", 2, source="text_paragraph")
    d.add("Giá dự phóng theo P/B", "", 26200, "đồng/cổ phiếu", 3)
    d.add("Giá dự phóng theo DCF", "", 27600, "đồng/cổ phiếu", 3)
    d.add("Giá mục tiêu", "Năm 2026", 26900, "đồng/cổ phiếu", 3)
    d.add("Giá hiện tại", "", 22100, "đồng/cổ phiếu", 1)
    d.add("EPS 4 quý gần nhất", "", 2750, "đồng/cổ phiếu", 1)
    d.note("Định nghĩa LNST sau CĐTS", "LNST sau CĐTS là lợi nhuận sau thuế thuộc về cổ đông công ty mẹ.", 1)
    d.write("R1")


def r2():
    d = Doc("R2_KBSV_MWG", "R2-kbsv-mwg-p1-5.pdf", 5)
    rows = {"Doanh thu thuần": (34147, 39853, 99927, 113607), "Doanh thu - TGDĐ+Topzone": (8132, 9535, 21649, 26130), "Doanh thu - ĐMX": (14319, 17547, 45095, 50442),
            "Doanh thu - BHX": (10840, 11780, 30329, 34423), "Doanh thu - Khác": (922, 990, 2854, 2613), "Lợi nhuận gộp": (6892, 7478, 20787, 22247),
            "Lợi nhuận sau thuế": (806, 1784, 2830, 4989), "LNST công ty mẹ": (800, 1784, 2819, 4965)}
    periods = ("Quý 3/2024", "Quý 3/2025", "9 tháng 2024", "9 tháng 2025")
    for name, values in rows.items():
        for period, value in zip(periods, values):
            d.add(name, period, value, "tỷ đồng", 3)
    for period, value in zip(periods, (20.2, 18.8, 20.8, 19.6)):
        d.add("Biên lợi nhuận gộp", period, value, "%", 3)
    for period, value in zip(periods, (2.4, 4.5, 2.8, 4.4)):
        d.add("Biên LNST", period, value, "%", 3)
    d.add("Giá mục tiêu", "", 106100, "đồng/cổ phiếu", 1)
    d.add("Giá hiện tại", "", 79900, "đồng/cổ phiếu", 1)
    for chain, a, b in [("TGDĐ", 1021, 1013), ("ĐMX", 2026, 2018), ("BHX", 1770, 2290), ("An Khang", 326, 347), ("Erablue", 87, 144)]:
        d.add(f"Số cửa hàng - {chain}", "Năm 2024", a, "cửa hàng", 4, source="chart_bar")
        d.add(f"Số cửa hàng - {chain}", "Quý 3/2025", b, "cửa hàng", 4, source="chart_bar")
    for name, value in {"Dự phóng LNST công ty mẹ - KBSV": 8173, "Dự phóng LNST công ty mẹ - Đồng thuận": 7052}.items():
        d.add(name, "Năm 2026", value, "tỷ đồng", 2)
    d.add("Dự phóng doanh thu", "Năm 2025", 155535, "tỷ đồng", 2)
    for name, value in {"Giá mục tiêu kịch bản tích cực": 119100, "Giá mục tiêu kịch bản cơ sở": 106100, "Giá mục tiêu kịch bản tiêu cực": 93600}.items():
        d.add(name, "", value, "đồng/cổ phiếu", 2)
    d.add("Số cửa hàng BHX mở mới theo mục tiêu", "Năm 2026", 700, "cửa hàng", 5, source="text_paragraph")
    d.add("Số cửa hàng BHX mở mới theo mục tiêu", "Năm 2026", 1000, "cửa hàng", 2)
    d.add("Doanh thu 1 cửa hàng 1 tháng - ĐMX", "Quý 3/2025", 2.9, "tỷ đồng", 4, source="chart_line", method="axis_estimation")
    for chain, value in {"TGDĐ+ĐMX": 20.6, "FPT Shop": 11.2, "DGW ICT&CE": 9.9}.items():
        d.add(f"Tăng trưởng doanh thu ICT&CE - {chain}", "Quý 3/2025", value, "%", 5, source="chart_line")
    d.write("R2")


def vng():
    d = Doc("VNG_SNAPSHOT_Q1_26", "Snapshot Q1-26 VI.pdf", 7)
    for period, value in zip(("Quý 1/2025", "Quý 2/2025", "Quý 3/2025", "Quý 4/2025", "Quý 1/2026"), (185, 251, 263, 139, 470)):
        d.add("Lợi nhuận thuần từ HĐKD sau điều chỉnh", period, value, "tỷ đồng", 2, source="chart_bar")
    d.write("VNG")


def design_example():
    d = Doc("DOC_STAT_2025_01", "baocao_kinhdoanh_3quy.pdf", 4)
    d.note("Định nghĩa doanh thu", "Doanh thu thuần chưa bao gồm thuế GTGT.", 1)
    d.add("Doanh thu - Miền Bắc", "Quý 1", 38, "triệu đồng", 3, source="chart_bar", code="CHART_MB_Q1")
    d.add("Doanh thu - Miền Bắc", "Quý 3", 87, "triệu đồng", 3, source="chart_bar", code="CHART_MB_Q3")
    d.add("Doanh thu - Miền Nam", "Quý 1", 50, "triệu đồng", 3, source="chart_bar", code="CHART_MN_Q1")
    d.add("Doanh thu - Miền Nam", "Quý 3", 90, "triệu đồng", 3, source="chart_bar", code="CHART_MN_Q3")
    d.write("design_example")


def edge():
    """A store built to break things: bad statuses, mixed units, unknown units, negative and zero values."""
    d = Doc("EDGE", "edge.pdf", 2)
    d.add("Lợi nhuận - A", "Quý 1/2026", -100, "triệu đồng", 1)
    d.add("Lợi nhuận - A", "Quý 2/2026", 50, "triệu đồng", 1)
    d.add("Doanh thu - A", "Quý 1/2026", 0, "triệu đồng", 1)
    d.add("Doanh thu - A", "Quý 2/2026", 10, "triệu đồng", 1)
    d.add("Doanh thu - B", "Quý 1/2026", 2, "tỷ đồng", 1)
    d.add("Doanh thu - B", "Quý 2/2026", 3000, "triệu đồng", 1)
    d.add("Doanh thu - C", "Quý 1/2026", None, "triệu đồng", 1)
    d.add("Doanh thu - C", "Quý 2/2026", 5, "triệu đồng", 1)
    d.add("Doanh thu - D", "Quý 1/2026", None, "triệu đồng", 1, status="error", method="none")
    d.add("Doanh thu - D", "Quý 2/2026", 5, "triệu đồng", 1)
    d.add("Sản lượng - A", "Quý 2/2026", 7, "nghìn tấn", 1)
    d.add("Không rõ đơn vị - A", "Quý 1/2026", 10, None, 2)
    d.add("Không rõ đơn vị - A", "Quý 2/2026", 20, None, 2)
    d.write("edge")


for build in (s1, s2, r1, r2, vng, design_example, edge):
    build()
print("datasets written:", sorted(p.name for p in OUT.glob("*.json")))
