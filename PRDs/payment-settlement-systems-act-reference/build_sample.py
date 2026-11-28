"""Builds the PSS Act worked-example complaint PDF (payment-settlement-systems-act.md §9.3).

Every name, number, amount and date below is invented. Run:
    python3 build_sample.py
It writes sample.html next to this file and prints it to
complaint-pdf-worked-example.pdf with headless Chrome.
"""
import html
import pathlib
import subprocess

HERE = pathlib.Path(__file__).parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

FINAL_RELIEF = (
    "It is most respectfully prayed that this Hon'ble Court may be pleased to: (a) Take cognizance of the "
    "offence committed by the Accused under Section 25 of the Payment and Settlement Systems Act, 2007; "
    "(b) Issue process/summons against the Accused; (c) Upon trial, convict and sentence the Accused under "
    "Section 25(1) of the said Act to imprisonment which may extend to two years, or with fine which may "
    "extend to twice the amount of the electronic funds transfer, or with both; (d) Direct the Accused to pay "
    "compensation under Section 395 of the Bharatiya Nagarik Suraksha Sanhita, 2023, equal to the amount of "
    "the transfer with interest at 9% per annum from the date of dishonour; (e) Grant such other relief as "
    "this Hon'ble Court deems fit."
)
INTERIM_RELIEF = (
    "It is, therefore, most respectfully prayed that this Hon'ble Court may be pleased to: Direct the Accused "
    "to pay interim compensation to the Complainant under Section 143A of the Negotiable Instruments Act, "
    "1881, read with Section 25(5) of the Payment and Settlement Systems Act, 2007, during the pendency of the "
    "trial, of a sum not exceeding 20% of the amount of the electronic funds transfer i.e. Rs. 18,600, within "
    "60 days of the order or such further period not exceeding 30 days as this Hon'ble Court may allow for "
    "sufficient cause shown."
)
AFFIDAVIT = [
    "I am the complainant / authorised representative of the complainant in the above case and am fully "
    "acquainted with the facts and circumstances of the case. I am competent and authorised to swear to this "
    "affidavit. The accused initiated the above electronic funds transfer, through a mandate given to their "
    "bank, in discharge of a legally enforceable debt or liability. The transfer was initiated in accordance "
    "with the procedural guidelines of the system provider and was returned unpaid because the amount in the "
    "accused's account was insufficient, or exceeded the amount arranged to be paid. A demand notice was issued "
    "to the accused within thirty days of the complainant receiving information of the dishonour from the bank, "
    "and the accused failed to pay within fifteen days of its receipt. All other requirements under Section 25 "
    "of the Payment and Settlement Systems Act, 2007 have been complied with.",
    "I confirm that the demand notice was served on the last known correct address of the accused(s).",
    "In accordance with Section 225 of the Bharatiya Nagarik Suraksha Sanhita, 2023, I confirm that there is "
    "sufficient ground for proceeding against the accused.",
    "In accordance with Section 223 and other relevant provisions of the Bharatiya Nagarik Suraksha Sanhita, "
    "2023, I confirm that the contents of this complaint are true and correct to the best of my knowledge, "
    "belief and information.",
    "The physical or electronic records of the documents etc. produced by me with this complaint are in my "
    "lawful and proper custody and possession. It is therefore humbly prayed that this Hon'ble Court may be "
    "pleased to take cognizance of the offence committed by the accused, and issue process to the accused.",
]

e = html.escape


def cell(l, v):
    v = e(v)
    if "__PS__" in v:
        a, ps = v.split("__PS__")
        v = f'{a}<div class="l ps">Police Station</div>{ps}'
    return f'<div class="f"><div class="l">{e(l)}</div><div class="v">{v}</div></div>'


def grid(fields):
    """Field flow: three columns, label above value."""
    return '<div class="grid">' + "".join(cell(l, v) for l, v in fields) + "</div>"


def full(label, text):
    return f'<div class="full"><div class="l">{e(label)}</div><div class="v">{e(text)}</div></div>'


def block(title):
    return f'<h4>{e(title)}</h4>'


def columnar(headers, rows, widths):
    head = "".join(f'<th style="width:{w}">{e(h)}</th>' for h, w in zip(headers, widths))
    body = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="col"><tr>{head}</tr>{body}</table>'


MANDATE = [
    ("Type of mandate", "e-NACH"),
    ("UMRN (mandate reference number)", "FDRL7020000012448391"),
    ("Date of mandate", "14 March 2025"),
    ("Loan / agreement number", "MFL/KLM/BL/2025/00871"),
    ("IFSC Code (accused's bank)", "FDRL0001250"),
    ("Bank Name", "Federal Bank"),
    ("Bank Branch", "Kottiyam"),
    ("Bank Account Number", "12500100045871"),
    ("Is the mandate being filed with the complaint?", "Yes"),
]
DEBITS = [
    [
        ("Amount of the transfer", "₹46,500"),
        ("Date the debit was presented", "5 January 2026"),
        ("Date of dishonour", "5 January 2026"),
        ("Date the bank informed the complainant", "7 January 2026"),
        ("Reason for return", "Balance insufficient"),
        ("Transaction / sequence number", "NACH0126010500345"),
    ],
    [
        ("Amount of the transfer", "₹46,500"),
        ("Date the debit was presented", "5 February 2026"),
        ("Date of dishonour", "6 February 2026"),
        ("Date the bank informed the complainant", "7 February 2026"),
        ("Reason for return", "Balance insufficient"),
        ("Transaction / sequence number", "-"),
    ],
]

parts = []
P = parts.append

# Cover
P('<div class="cover"><div>24×7 ON Court, Kollam</div>'
  '<div class="b">Malabar Fincorp Ltd v/s Rajesh Kumar Pillai +1 other</div>'
  '<div class="b">KL-000231-2026</div>'
  '<div class="b">COMPLAINT UNDER SECTION 25 OF THE PAYMENT AND SETTLEMENT SYSTEMS ACT, 2007</div></div>')

# Synopsis
P("<h2>Synopsis</h2>")
P(block("Parties"))
P(grid([
    ("Complainant Name", "Malabar Fincorp Ltd"),
    ("Accused Name", "Rajesh Kumar Pillai\nSindhu Rajesh"),
    ("Complainant's Advocate Name", "Arun Mathew"),
]))
P(block("Mandate details"))
P(grid([MANDATE[i] for i in (0, 1, 2, 3, 5, 6, 7)]))
for n, d in enumerate(DEBITS, 1):
    P(block(f"Dishonour - Failed Debit {n}"))
    P(grid(d[:5]))
P(block("Demand Notice 1"))
P(grid([
    ("Date of dispatch of demand notice", "20 February 2026"),
    ("Mode of service", "Registered Post with AD"),
    ("Tracking number", "RK482201937IN"),
    ("Whether delivered?", "Yes"),
    ("Date of delivery", "24 February 2026"),
    ("Has the accused replied to the demand notice?", "No"),
]))
P(block("Cause of Action"))
P(grid([
    ("Date of cause of action", "11 March 2026"),
    ("Jurisdiction", "Federal Bank, Kollam Main - complainant's bank branch"),
    ("Any other complaint pending between the same parties?", "No"),
]))
P(block("Prayer / Relief sought"))
P(f'<div class="para">{e(FINAL_RELIEF)}</div>')

# 1. Party details
P("<h2>1. Party details</h2><h3>1.1. Complainant</h3>")
P(block("Complainant 1"))
P(grid([
    ("Are you representing yourself as a Party-in-Person?", "No"),
    ("Complainant Type", "Institution"),
    ("Type of Institution", "NBFC"),
    ("Institution Name", "Malabar Fincorp Ltd"),
    ("CIN or PAN", "U65923KL2011PLC029471"),
    ("Phone Number (Institution Contact)", "+914742761100"),
    ("Email ID (Institution Contact)", "legal@malabarfincorp.example"),
    ("Institution Address", "Fincorp House, Chinnakada, Kollam, Kerala 691001"),
]))
P(block("Authorized Representative for Complainant 1"))
P(grid([
    ("Authorised Representative Phone", "+919847301122"),
    ("Authorised Representative Full Name", "Deepa Varghese"),
    ("Authorised Representative Age", "38"),
    ("Authorised Representative Gender", "-"),
    ("Authorised Representative Differently abled?", "-"),
    ("Authorised Representative Email", "deepa.v@malabarfincorp.example"),
    ("Authorised Representative Designation", "Manager - Recoveries"),
    ("Authorised Representative Address", "Fincorp House, Chinnakada, Kollam, Kerala 691001"),
]))
P("<h3>1.2. Advocate (Complainant)</h3>")
P(grid([("Number of advocates", "1")]))
P(block("Advocate for Complainant 1"))
P(columnar(["Full Name", "Bar Registration"], [["Arun Mathew", "K/1588/2013"]], ["55%", "45%"]))
P("<h3>1.3. Accused</h3>")
P(block("Accused 1"))
P(grid([
    ("Accused Type", "Individual"),
    ("Full Name", "Rajesh Kumar Pillai"),
    ("Mobile Number (contact)", "+919746215580"),
    ("Email ID (contact)", "-"),
    ("Address 1", "Kailas, Mukhathala, Kollam, Kerala 691577\n__PS__Kottiyam"),
    ("Resides within jurisdiction", "Yes"),
]))
P(block("Accused 2"))
P(grid([
    ("Accused Type", "Individual"),
    ("Full Name", "Sindhu Rajesh"),
    ("Mobile Number (contact)", "+919746215581"),
    ("Email ID (contact)", "sindhu.r@mail.example"),
    ("Address 1", "Kailas, Mukhathala, Kollam, Kerala 691577\n__PS__Kottiyam"),
    ("Resides within jurisdiction", "Yes"),
]))

# 2. Case details
P("<h2>2. Case details</h2><h3>2.1. Mandate and failed debit details</h3>")
P(block("Mandate"))
P(grid(MANDATE))
for n, d in enumerate(DEBITS, 1):
    P(block(f"Failed Debit {n}"))
    P(grid(d))
P("<h3>2.2. Demand notice details</h3>")
P(block("Demand Notice 1"))
P(grid([("Nature of debt/liability", "Loan / credit facility")]))
P(grid([
    ("Date of dispatch of demand notice", "20 February 2026"),
    ("Mode of service", "Registered Post with AD"),
    ("Tracking number", "RK482201937IN"),
    ("Whether delivered?", "Yes"),
    ("Date of delivery", "24 February 2026"),
    ("Has the accused replied to the demand notice?", "No"),
    ("Has the accused made full or part payment of the amount of the electronic funds transfer?",
     "No Payment Made"),
]))
P("<h3>2.3. Jurisdiction and limitation</h3>")
P(block("Payee (Complainant) Bank Details"))
P(grid([
    ("IFSC Code of the Payee's (Complainant's) Branch", "FDRL0001001"),
    ("Bank Name", "Federal Bank"),
    ("Bank Branch", "Kollam Main"),
    ("Police Station of bank branch", "Kollam East"),
]))
P(full("Is there any other electronic funds transfer dishonour complaint pending between the same parties?", "No"))
P(grid([
    ("Date of cause of action", "11 March 2026"),
    ("Date of complaint filing", "25 March 2026"),
]))
P("<h3>2.4. ADR, prayer and other details</h3>")
P(full("Would you like to settle the case outside the court through alternative methods of dispute resolution?", "Maybe"))
P(full("Additional details (Other Details)", "-"))
P(full("Interim Relief", INTERIM_RELIEF))
P(full("Final Relief", FINAL_RELIEF))

# 3. Evidence (no witnesses, so 3.1 does not print)
P("<h2>3. Evidence</h2><h3>3.2. List of documents</h3>")
docs = [
    ("Debit mandate", "Yes"),
    ("Return memo — Failed Debit 1", "Yes"),
    ("Return memo — Failed Debit 2", "Yes"),
    ("Legal Demand Notice 1", "Yes"),
    ("Proof of dispatch of demand notice 1", "No"),
    ("Proof of delivery of demand notice 1", "No"),
    ("Loan account statement", "Yes"),
    ("Loan agreement or sanction letter", "No"),
    ("ID Card - Complainant 1", "No"),
    ("Authority of the representative", "No"),
    ("Vakalatnama", "No"),
]
P(columnar(["S. No.", "Document Name", "Natively Digital"],
           [[f"{i}.", d, n] for i, (d, n) in enumerate(docs, 1)], ["10%", "70%", "20%"]))

# 4. Affidavit + signatures
P("<h2>4. Affidavit</h2>")
for para in AFFIDAVIT:
    P(f'<div class="para">{e(para)}</div>')
P('<div class="sigs">'
  '<div class="sig"><div class="n">Deepa Varghese</div><div class="r">Authorised Representative for Complainant 1</div></div>'
  '<div class="sig"><div class="n">Arun Mathew</div><div class="r">Advocate for Complainant 1</div></div>'
  '</div>')

# Appended documents
P('<div class="pb"><div class="b">Documents uploaded by the Complainant.</div>'
  f'<div class="note">[the {len(docs)} uploaded files follow here, in the order of section 3.2]</div></div>')

CSS = """
@page { size: A4; margin: 22mm 18mm; }
body { font-family: 'DejaVu Sans', Verdana, sans-serif; font-size: 10pt; color: #111; }
.cover { text-align: center; margin: 10mm 0 14mm; font-size: 11.5pt; line-height: 1.6; }
.cover .b { font-weight: bold; }
h2 { font-size: 14pt; margin: 14pt 0 6pt; }
h3 { font-size: 11pt; margin: 10pt 0 4pt; }
h4 { font-size: 10pt; margin: 9pt 0 3pt 6pt; }
.grid { display: grid; grid-template-columns: 1fr 1fr 1fr; column-gap: 12pt; row-gap: 7pt; margin-bottom: 4pt; }
.l { font-size: 7.5pt; color: #666; } .ps { margin-top: 3pt; }
.v { white-space: pre-line; }
.full { margin: 6pt 0 6pt 6pt; }
.full .v, .para { line-height: 1.45; }
.para { margin: 0 0 7pt 6pt; }
table.col { width: 100%; border-collapse: collapse; margin: 3pt 0 6pt; }
table.col th { text-align: left; font-size: 7.5pt; color: #666; border-bottom: 0.5pt solid #bbb; padding: 2pt 0; }
table.col td { padding: 3pt 0; }
.sigs { display: grid; grid-template-columns: 1fr 1fr; column-gap: 24pt; margin-top: 24pt; }
.sig { border-top: 0.6pt solid #111; padding-top: 2pt; }
.sig .n { font-weight: bold; } .sig .r { font-size: 8pt; color: #666; }
.pb { page-break-before: always; } .pb .b { font-weight: bold; } .note { font-size: 9pt; }
"""

doc = f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
(HERE / "sample.html").write_text(doc, encoding="utf-8")
subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={HERE / 'complaint-pdf-worked-example.pdf'}", (HERE / "sample.html").as_uri()],
               check=True, capture_output=True)
print("wrote", HERE / "complaint-pdf-worked-example.pdf")
