import streamlit as st
import pandas as pd
from io import BytesIO
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Font

st.set_page_config(page_title="GST Working Papers", layout="wide")

st.title("GST Working Papers Generator (AU BAS)")
st.markdown(
    "Upload your **Commonwealth** and **Wise** CSV files. "
    "Review GST decisions and export BAS-ready working papers."
)

# ------------------------
# Upload section
# ------------------------
c1, c2 = st.columns(2)

with c1:
    cba_file = st.file_uploader("Upload Commonwealth CSV", type="csv")
with c2:
    wise_file = st.file_uploader("Upload Wise CSV", type="csv")

if not cba_file or not wise_file:
    st.stop()

# ------------------------
# Load & normalise data
# ------------------------

# Commonwealth
cba = pd.read_csv(cba_file, header=None)
cba.columns = ["Date", "Amount", "Description", "Balance"]
cba["Date"] = pd.to_datetime(cba["Date"], dayfirst=True, errors="coerce")
cba["Account"] = "Commonwealth"
cba["Direction"] = cba["Amount"].apply(lambda x: "IN" if x > 0 else "OUT")
cba["Amount"] = pd.to_numeric(cba["Amount"], errors="coerce").fillna(0)

# Wise
wise = pd.read_csv(wise_file)
wise["Date"] = pd.to_datetime(wise["Finished on"], errors="coerce")
wise["Account"] = "Wise"
wise["Description"] = wise["Source name"]
wise["Direction"] = wise["Direction"]
wise["Amount"] = pd.to_numeric(
    wise["Target amount (after fees)"], errors="coerce"
).fillna(0)

ledger = pd.concat(
    [
        cba[["Date", "Account", "Description", "Direction", "Amount"]],
        wise[["Date", "Account", "Description", "Direction", "Amount"]],
    ],
    ignore_index=True,
)

# ------------------------
# Quarter detection
# ------------------------
ledger["Quarter"] = ledger["Date"].dt.month.map(
    lambda m: "Q1" if m <= 3 else "Q2" if m <= 6 else "Q3" if m <= 9 else "Q4"
)
bas_quarter = ledger["Quarter"].mode().iloc[0]
sheet_name = f"{bas_quarter} – BAS GST"

# ------------------------
# Classification
# ------------------------
def classify(row):
    d = str(row["Description"]).lower()
    if row["Direction"] == "IN":
        return "Income", "NO", "Income received"
    if "transfer" in d:
        return "Transfer", "NO", "Internal transfer"
    if any(x in d for x in ["fee", "fx", "asic", "ato", "bpay", "tax"]):
        return "Fee", "NO", "GST-free fee or government charge"
    return "Expense", "YES", "Australian business expense – GST assumed"


ledger[["Transaction Type", "GST Claimable", "System Reason"]] = ledger.apply(
    lambda r: pd.Series(classify(r)), axis=1
)

ledger["Gross Amount"] = ledger["Amount"].abs().round(2)
ledger["GST Amount"] = 0.0
ledger["Net (ex GST)"] = ledger["Gross Amount"]
ledger["Comment"] = ""

# ------------------------
# Editable ledger (WEB)
# ------------------------
edited_df = st.data_editor(
    ledger.drop(columns=["Quarter"]),
    use_container_width=True,
    num_rows="fixed",
    column_config={
        "GST Claimable": st.column_config.SelectboxColumn(
            "GST Claimable", options=["YES", "NO"]
        ),
        "Comment": st.column_config.TextColumn("Comment"),
    },
)

# ------------------------
# WEB GST SUMMARY (correct – unchanged)
# ------------------------
income = edited_df.loc[edited_df["Transaction Type"] == "Income", "Gross Amount"].sum()
gst_sales = income / 11
gst_exp_gross = edited_df.loc[edited_df["GST Claimable"] == "YES", "Gross Amount"].sum()
gst_purchases = gst_exp_gross / 11
net_gst = gst_sales - gst_purchases

st.subheader("GST Summary")
cols = st.columns(5)
labels = [
    ("G1 – Total sales", income),
    ("1A – GST on sales", gst_sales),
    ("GST-claimable expenses", gst_exp_gross),
    ("1B – GST on purchases", gst_purchases),
    ("Net GST payable", net_gst),
]

for c, (l, v) in zip(cols, labels):
    c.markdown(
        f"""
        <div style="background:#1f2937;padding:20px;border-radius:10px;text-align:center;color:white">
            <div style="font-size:13px;opacity:.8">{l}</div>
            <div style="font-size:28px;font-weight:700">${v:,.2f}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ------------------------
# Excel export (FIXED)
# ------------------------
def export_excel(df):
    output = BytesIO()
    currency_fmt = "$#,##0.00"

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        ws = writer.sheets[sheet_name]

        last_row = len(df) + 1

        # Column letters (NO columns dropped)
        col_map = {c: get_column_letter(i + 1) for i, c in enumerate(df.columns)}

        # Dropdown
        dv = DataValidation(type="list", formula1='"YES,NO"', allow_blank=False)
        ws.add_data_validation(dv)
        dv.add(f"{col_map['GST Claimable']}2:{col_map['GST Claimable']}{last_row}")

        # Row formulas + currency formatting
        for r in range(2, last_row + 1):
            ws[f"{col_map['GST Amount']}{r}"] = (
                f'=IF({col_map["GST Claimable"]}{r}="YES",'
                f'{col_map["Gross Amount"]}{r}/11,0)'
            )
            ws[f"{col_map['Net (ex GST)']}{r}"] = (
                f'={col_map["Gross Amount"]}{r}-{col_map["GST Amount"]}{r}'
            )

            for c in ["Amount", "Gross Amount", "GST Amount", "Net (ex GST)"]:
                ws[f"{col_map[c]}{r}"].number_format = currency_fmt

        # Summary
        s = last_row + 3
        ws[f"A{s}"] = "GST SUMMARY (AUTO-CALCULATED)"
        ws[f"A{s}"].font = Font(bold=True)

        ws[f"A{s+2}"] = "G1 – Total sales (incl GST)"
        ws[f"B{s+2}"] = f'=SUMIF({col_map["Transaction Type"]}2:{col_map["Transaction Type"]}{last_row},"Income",{col_map["Gross Amount"]}2:{col_map["Gross Amount"]}{last_row})'

        ws[f"A{s+3}"] = "1A – GST on sales"
        ws[f"B{s+3}"] = f"=B{s+2}/11"

        ws[f"A{s+4}"] = "GST-claimable expenses (gross)"
        ws[f"B{s+4}"] = f'=SUMIF({col_map["GST Claimable"]}2:{col_map["GST Claimable"]}{last_row},"YES",{col_map["Gross Amount"]}2:{col_map["Gross Amount"]}{last_row})'

        ws[f"A{s+5}"] = "1B – GST on purchases"
        ws[f"B{s+5}"] = f'=SUMIF({col_map["GST Claimable"]}2:{col_map["GST Claimable"]}{last_row},"YES",{col_map["GST Amount"]}2:{col_map["GST Amount"]}{last_row})'

        ws[f"A{s+6}"] = "Net GST payable"
        ws[f"B{s+6}"] = f"=B{s+3}-B{s+5}"

        for r in range(s + 2, s + 7):
            ws[f"B{r}"].number_format = currency_fmt

        # FINAL autosize — AFTER all formatting, NO forced widths
        for col in ws.columns:
            max_len = max(len(str(cell.value)) if cell.value else 0 for cell in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = max_len + 2

    return output.getvalue()

# ------------------------
# Export
# ------------------------
st.download_button(
    "⬇️ Export Excel (BAS GST)",
    export_excel(edited_df),
    file_name=f"{bas_quarter}_BAS_GST.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
