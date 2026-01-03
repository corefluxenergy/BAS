import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="GST Working Papers", layout="wide")

st.title("GST Working Papers Generator (AU BAS)")
st.markdown(
    "Upload your **Commonwealth** and **Wise** CSV files. "
    "Review GST decisions, add comments, and export working papers."
)

st.markdown(
    """
    <style>
    div.stDownloadButton > button {
        width: 100%;
        height: 3em;
        font-size: 18px;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Upload files
col1, col2 = st.columns(2)
with col1:
    cba_file = st.file_uploader("Upload Commonwealth CSV", type="csv")
with col2:
    wise_file = st.file_uploader("Upload Wise CSV", type="csv")

if not cba_file or not wise_file:
    st.info("Please upload both CSV files to continue.")
    st.stop()

# Commonwealth
cba = pd.read_csv(cba_file, header=None)
cba.columns = ["Date", "Amount", "Description", "Balance"]
cba["Account"] = "Commonwealth"
cba["Direction"] = cba["Amount"].apply(lambda x: "IN" if x > 0 else "OUT")
cba["Amount"] = pd.to_numeric(cba["Amount"], errors="coerce").fillna(0)

# Wise
wise = pd.read_csv(wise_file)
wise["Account"] = "Wise"
wise["Date"] = wise["Finished on"]
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

def classify(row):
    desc = str(row["Description"]).lower()
    if row["Direction"] == "IN":
        return "Income", False, "Income received"
    if "transfer" in desc:
        return "Transfer", False, "Internal transfer"
    if any(k in desc for k in ["fee", "fx", "asic", "ato", "bpay", "tax"]):
        return "Fee", False, "GST-free fee or government charge"
    return "Expense", True, "Australian business expense – GST assumed"

ledger[["Transaction Type", "GST Claimable", "System Reason"]] = ledger.apply(
    lambda r: pd.Series(classify(r)), axis=1
)

ledger["Gross Amount"] = ledger["Amount"].abs().round(2)
ledger["GST Amount"] = ledger.apply(
    lambda r: round(r["Gross Amount"] / 11, 2) if r["GST Claimable"] else 0, axis=1
)
ledger["Net (ex GST)"] = ledger["Gross Amount"] - ledger["GST Amount"]
ledger["Comment"] = ""

st.subheader("Ledger")
edited_df = st.data_editor(
    ledger,
    use_container_width=True,
    column_config={
        "GST Claimable": st.column_config.CheckboxColumn(),
        "Comment": st.column_config.TextColumn(),
    },
)

edited_df["GST Amount"] = edited_df.apply(
    lambda r: round(r["Gross Amount"] / 11, 2) if r["GST Claimable"] else 0, axis=1
)
edited_df["Net (ex GST)"] = edited_df["Gross Amount"] - edited_df["GST Amount"]

with st.sidebar:
    st.header("Ledger Overview")
    st.write("Commonwealth:", (edited_df["Account"] == "Commonwealth").sum())
    st.write("Wise:", (edited_df["Account"] == "Wise").sum())
    st.write("Total rows:", len(edited_df))

    st.divider()
    st.header("GST Summary (BAS)")
    g1 = edited_df.loc[edited_df["Transaction Type"] == "Income", "Gross Amount"].sum()
    one_a = round(g1 / 11, 2)
    gst_exp = edited_df.loc[edited_df["GST Claimable"], "Gross Amount"].sum()
    one_b = edited_df.loc[edited_df["GST Claimable"], "GST Amount"].sum()
    net_gst = one_a - one_b

    st.metric("G1 – Total sales (incl GST)", f"${g1:,.2f}")
    st.metric("1A – GST on sales", f"${one_a:,.2f}")
    st.metric("GST-claimable expenses (gross)", f"${gst_exp:,.2f}")
    st.metric("1B – GST on purchases", f"${one_b:,.2f}")
    st.metric("Net GST payable", f"${net_gst:,.2f}")

def export_excel(df):
    output = BytesIO()

    # Recalculate summary from df (same as UI)
    g1 = df.loc[df["Transaction Type"] == "Income", "Gross Amount"].sum()
    one_a = round(g1 / 11, 2)
    gst_exp_gross = df.loc[df["GST Claimable"], "Gross Amount"].sum()
    one_b = df.loc[df["GST Claimable"], "GST Amount"].sum()
    net_gst = one_a - one_b

    gst_summary = pd.DataFrame(
        {
            "BAS Label": [
                "G1 – Total sales (incl GST)",
                "1A – GST on sales",
                "GST-claimable expenses (gross)",
                "1B – GST on purchases",
                "Net GST payable",
            ],
            "Amount (AUD)": [
                g1,
                one_a,
                gst_exp_gross,
                one_b,
                net_gst,
            ],
        }
    )

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="GST Working Papers")
        gst_summary.to_excel(writer, index=False, sheet_name="GST Summary")

    return output.getvalue()

st.divider()
st.subheader("Export")

st.download_button(
    label="⬇️ Export Excel (GST Working Papers)",
    data=export_excel(edited_df),
    file_name="GST_Working_Papers.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
