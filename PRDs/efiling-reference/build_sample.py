"""Builds the e-filing (Section 138) worked-example complaint PDF (efiling.md §16.9).

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
e = html.escape

FINAL_RELIEF = (
    "It is most respectfully prayed that this Hon'ble Court may be pleased to: (a) Take cognizance of the offence "
    "committed by the Accused under Section 138 of the Negotiable Instruments Act, 1881; (b) Issue process/summons "
    "against the Accused and direct him/her to appear before this Hon'ble Court; (c) Upon trial, convict and sentence "
    "the Accused under Section 138 of the Negotiable Instruments Act, 1881, to imprisonment for a term which may extend "
    "to two years, or with fine which may extend to twice the amount of the cheque, or with both; (d) Direct the Accused "
    "to pay compensation to the Complainant under Section 395 of the Bharatiya Nagarik Suraksha Sanhita, 2023, "
    "equivalent to the cheque amount along with interest 6% per annum from the date of dishonour; (e) Grant such other "
    "and further relief(s) as this Hon'ble Court may deem fit and proper in the facts and circumstances of the case."
)
INTERIM_RELIEF = (
    "It is, therefore, most respectfully prayed that this Hon'ble Court may be pleased to: Direct the Accused to pay "
    "interim compensation to the Complainant under Section 143A of the Negotiable Instruments Act, 1881, during the "
    "pendency of the trial, of a sum not exceeding 20% of the cheque amount i.e. Rs. 1,05,000, within 60 days of the "
    "order or such further period not exceeding 30 days as this Hon'ble Court may allow for sufficient cause shown."
)
AFFIDAVIT = [
    "I am the complainant / authorised representative of the complainant in the above case and am fully acquainted "
    "with the facts and circumstances of the case. I am competent and authorised to swear to this affidavit. The accused "
    "issued the above cheque in discharge of a legally enforceable debt or liability. It has been dishonoured due to "
    "insufficiency of funds. A demand notice has been issued to the accused, but she/he has failed to make the payment "
    "due under the cheque. All other requirements under Section 138 of the Negotiable Instruments Act, 1881 have been "
    "complied with.",
    "I confirm that the demand notice was served on the last known correct address of the accused(s).",
    "In accordance with Section 225 of the Bharatiya Nagarik Suraksha Sanhita, 2023, I confirm that there is "
    "sufficient ground for proceeding against the accused.",
    "In accordance with Section 223 and other relevant provisions of the Bharatiya Nagarik Suraksha Sanhita, 2023, I "
    "confirm that the contents of this complaint are true and correct to the best of my knowledge, belief and "
    "information.",
    "The physical or electronic records of the documents etc. produced by me with this complaint are in my lawful and "
    "proper custody and possession. It is therefore humbly prayed that this Hon'ble Court may be pleased to take "
    "cognizance of the offence committed by the accused, and issue process to the accused.",
]


def addr(text, ps):
    return f"{text}\n__PS__{ps}"


def cell(l, v):
    v = e(v)
    if "__PS__" in v:
        a, ps = v.split("__PS__")
        v = f'{a}<div class="l ps">Police Station</div>{ps}'
    return f'<div class="f"><div class="l">{e(l)}</div><div class="v">{v}</div></div>'


def grid(fields):
    return '<div class="grid">' + "".join(cell(l, v) for l, v in fields) + "</div>"


def full(label, text):
    return f'<div class="full"><div class="l">{e(label)}</div><div class="v">{e(text)}</div></div>'


def block(t):
    return f"<h4>{e(t)}</h4>"


def columnar(headers, rows, widths):
    head = "".join(f'<th style="width:{w}">{e(h)}</th>' for h, w in zip(headers, widths))
    body = "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="col"><tr>{head}</tr>{body}</table>'


CHEQUES = [
    dict(date="12 December 2025", amount="₹3,50,000", number="214507"),
    dict(date="12 December 2025", amount="₹1,75,000", number="214508"),
]
BANK = [("IFSC Code", "HDFC0000521"), ("Bank Name", "HDFC Bank"), ("Bank Branch", "Kollam Main Branch"),
        ("Bank Account Number", "50100234567890")]
RETURN = [("Date of presentation/deposit", "2 January 2026"), ("Date of return", "5 January 2026"),
          ("Return reason", "Insufficient Funds")]

parts = []
P = parts.append

P('<div class="cover"><div>24×7 ON Court, Kollam</div>'
  '<div class="b">Anilkumar Sasidharan +1 other v/s Devadas Nair +3 others</div>'
  '<div class="b">KL-004182-2026</div>'
  '<div class="b">COMPLAINT UNDER SECTION 138 OF THE NEGOTIABLE INSTRUMENTS ACT, 1881</div></div>')

# Synopsis
P("<h2>Synopsis</h2>")
P(block("Parties"))
P(grid([
    ("Complainant Name", "Anilkumar Sasidharan\nThevally Traders Pvt Ltd"),
    ("Accused Name", "Devadas Nair\nKarunagappally Marine Exports\nSuresh Babu M\nNisha Thomas"),
    ("Complainant's Advocate Name", "Meera Nandakumar\nAnoop Chandran\nFathima Beevi A"),
]))
for n, c in enumerate(CHEQUES, 1):
    P(block(f"Cheque details - Cheque {n}"))
    P(grid([("Date on cheque", c["date"]), ("Amount", c["amount"]), ("Cheque number", c["number"]),
            ("Bank Name", "HDFC Bank"), ("Bank Branch", "Kollam Main Branch"),
            ("Bank Account Number", "50100234567890")]))
for n in (1, 2):
    P(block(f"Dishonour - Cheque {n}"))
    P(grid([("Date of presentation", "2 January 2026"), ("Date on return memo", "5 January 2026"),
            ("Return reason", "Insufficient Funds"), ("Bank Branch (Complainant)", "South Indian Bank, Kollam")]))
P(block("Demand Notice 1"))
P(grid([("Date of dispatch of demand notice", "20 January 2026"), ("Mode of service", "Registered Post with AD"),
        ("Tracking number", "-"), ("Whether delivered?", "No"), ("Date of return", "28 January 2026"),
        ("Reason for non-delivery", "Addressee moved from the address")]))
P(block("Cause of Action"))
P(grid([("Date of cause of action", "12 February 2026"),
        ("Jurisdiction invoked under Section 142(2)", "South Indian Bank, Kollam - complainant's bank branch"),
        ("Any other complaint pending between the same parties?", "Yes")]))
P(columnar(["Court Name", "Case Number"], [["JMFC-II, Kollam", "CMP/482/2025"]], ["50%", "50%"]))
P(block("Prayer / Relief sought"))
P(f'<div class="para">{e(FINAL_RELIEF)}</div>')

# 1. Party details
P("<h2>1. Party details</h2><h3>1.1. Complainant</h3>")
P(block("Complainant 1"))
P(grid([
    ("Are you representing yourself as a Party-in-Person?", "No"), ("Complainant Type", "Individual"),
    ("Phone Number", "+919847012233"), ("Full Name", "Anilkumar Sasidharan"), ("Age", "54"), ("Gender", "Male"),
    ("Differently abled?", "-"), ("Email ID", "anil.sasidharan@mail.example"),
    ("Permanent Address", "Sreyas, TC 14/221, Kadappakada, Kollam, Kerala 691008"),
    ("Is current address same as permanent?", "Yes"),
    ("Has this litigant transferred Power of Attorney to somebody else?", "Yes"),
]))
P(block("POA for Complainant 1"))
P(grid([
    ("PoA Phone Number", "+919995540118"), ("PoA Holder Full Name", "Lakshmi Menon"), ("PoA Holder Age", "41"),
    ("PoA Holder Email", "-"), ("PoA Permanent Address", "Flat 3B, Ashirvad Apartments, Chinnakada, Kollam, Kerala 691001"),
    ("PoA current same as permanent?", "No"),
    ("PoA Current Address", "22/1140, Vaidyasala Road, Thevally, Kollam, Kerala 691009"),
]))
P(block("Complainant 2"))
P(grid([
    ("Are you representing yourself as a Party-in-Person?", "No"), ("Complainant Type", "Institution"),
    ("Type of Institution", "Private limited company"), ("Institution Name", "Thevally Traders Pvt Ltd"),
    ("CIN or PAN", "U51909KL2014PTC036225"), ("Phone Number (Institution Contact)", "+914742765430"),
    ("Email ID (Institution Contact)", "-"), ("Institution Address", "2nd Floor, Beach Road, Thevally, Kollam, Kerala 691009"),
]))
P(block("Authorized Representative for Complainant 2"))
P(grid([
    ("Authorised Representative Phone", "+919446781200"), ("Authorised Representative Full Name", "Rajeev Pillai"),
    ("Authorised Representative Age", "46"), ("Authorised Representative Gender", "-"),
    ("Authorised Representative Differently abled?", "-"),
    ("Authorised Representative Email", "rajeev@thevallytraders.example"),
    ("Authorised Representative Designation", "Manager - Credit"),
    ("Authorised Representative Address", "2nd Floor, Beach Road, Thevally, Kollam, Kerala 691009"),
]))
P("<h3>1.2. Advocate (Complainant)</h3>")
P(grid([("Number of advocates", "3")]))
P(block("Advocate for Complainant 1, Complainant 2"))
P(columnar(["Full Name", "Bar Registration"],
           [["Meera Nandakumar", "K/1204/2011"], ["Anoop Chandran", "K/0876/2015"], ["Fathima Beevi A", "K/2210/2019"]],
           ["55%", "45%"]))
P("<h3>1.3. Accused</h3>")
P(block("Accused 1"))
P(grid([
    ("Accused Type", "Individual"), ("Full Name", "Devadas Nair"), ("Mobile Number (contact)", "+919388776511"),
    ("Email ID (contact)", "-"),
    ("Address 1", addr("Devi Nivas, Mundakkal East, Kollam, Kerala 691001", "Kollam East")),
    ("Address 2", addr("14/882, NH Bypass, Kavanad, Kollam, Kerala 691003", "-")),
    ("Resides within jurisdiction", "Yes"),
]))
P(block("Accused 2"))
P(grid([
    ("Accused Type", "Institution"), ("Type of Institution", "Partnership firm"),
    ("Institution Name", "Karunagappally Marine Exports"), ("Mobile Number (contact)", "+914762620144"),
    ("Email ID (contact)", "accounts@kmexports.example"),
    ("Address 1", addr("Harbour Road, Karunagappally, Kollam, Kerala 690518", "Karunagappally")),
]))
P(block("Persons Vicariously liable for the Institution"))
P(block("Person 1"))
P(grid([
    ("Representative Full Name", "Suresh Babu M"), ("Representative Designation", "Managing Partner"),
    ("Representative Mobile", "+919847556201"), ("Representative Email", "suresh@kmexports.example"),
    ("Representative Address", addr("Beach Road, Karunagappally, Kollam, Kerala 690518", "Karunagappally")),
]))
P(block("Person 2"))
P(grid([
    ("Representative Full Name", "Nisha Thomas"), ("Representative Designation", "Partner"),
    ("Representative Mobile", "+919446330817"), ("Representative Email", "-"),
    ("Representative Address", addr("Thomas Villa, Ochira, Kollam, Kerala 690548", "-")),
]))
P(grid([("Resides within jurisdiction", "Yes")]))

# 2. Case details
P("<h2>2. Case details</h2><h3>2.1. Cheque and return memo details</h3>")
for n, c in enumerate(CHEQUES, 1):
    P(block(f"Cheque {n} - {c['number']}"))
    f = [("Date on cheque", c["date"]), ("Amount", c["amount"]), ("Cheque Number", c["number"])]
    if n > 1:
        f.append(("Bank details same as previous cheque?", "Yes"))
    P(grid(f + BANK + RETURN))
P("<h3>2.2. Demand notice details</h3>")
P(block("Demand Notice 1"))
P(grid([("Nature of debt/liability", "Supply of goods - marine produce consignment")]))
P(grid([
    ("Date of dispatch of demand notice", "20 January 2026"), ("Mode of service", "Registered Post with AD"),
    ("Tracking number", "-"), ("Whether delivered?", "No"), ("Date of Return", "28 January 2026"),
    ("Reason for non-delivery", "Addressee moved from the address"),
    ("Has the accused replied to the demand notice?", "No"),
    ("Has the Drawer made full or part payment due under the cheque?", "Part Payment"),
    ("How much payment has already been made?", "₹50,000"),
]))
P("<h3>2.3. Jurisdiction and limitation</h3>")
P(full("Did the Payee (Complainant) deposit the cheque in their bank account?", "Yes"))
P(block("Payee (Complainant) Bank Details"))
P(grid([("IFSC Code (complainant's branch)", "SIBL0000432"), ("Bank Name", "South Indian Bank"),
        ("Bank Branch", "Kollam"), ("Police Station of bank branch", "Kollam East")]))
P(full("Is there any other cheque dishonour complaint pending between the same parties?", "Yes"))
P(columnar(["Court", "Case Number"], [["JMFC-II, Kollam", "CMP/482/2025"]], ["50%", "50%"]))
P(grid([("Date of cause of action", "12 February 2026"), ("Date of complaint filing", "25 March 2026"),
        ("Duration of delay", "13 days")]))
P(full("Reason for praying condonation of delay",
       "The complainant was admitted at Bishop Benziger Hospital, Kollam from 20 February 2026 to 14 March 2026 "
       "and could not instruct counsel during that period. Discharge summary is produced as proof of reasons for delay."))
P("<h3>2.4. ADR, prayer and other details</h3>")
P(full("Would you like to settle the case outside the court through alternative methods of dispute resolution?", "Yes"))
P(full("Additional details (Other Details)",
       "The complainant has supplied marine produce to the accused firm since 2019 on running account. Both cheques "
       "were issued towards the November 2025 consignment and were dishonoured on the same memo date."))
P(full("Interim Relief", INTERIM_RELIEF))
P(full("Final Relief", FINAL_RELIEF))

# 3. Evidence
P("<h2>3. Evidence</h2><h3>3.1. List of witnesses</h3>")
P(block("Witness 1"))
P(grid([
    ("Full Name", "-"), ("Age", "-"), ("What will the witness prove", "Presentation of both cheques and issue of the return memos"),
    ("Designation", "Branch Manager, South Indian Bank, Kollam"), ("Mobile Number", "+914742742100"), ("Email ID", "-"),
    ("Address 1", addr("South Indian Bank, Main Road, Kollam, Kerala 691001", "-")),
]))
P("<h3>3.2. List of documents</h3>")
docs = [
    ("Cheque 1", "Yes"), ("Cheque 2", "Yes"), ("Cheque return memo 1", "No"), ("Cheque return memo 2", "No"),
    ("Legal Demand Notice 1", "Yes"), ("Proof of dispatch of demand notice 1", "No"),
    ("Proof of delivery of demand notice 1", "No"), ("Proof of debt / liability", "Yes"),
    ("Proof of reasons for delay", "No"), ("ID Card — Complainant 1", "No"), ("ID Card — Complainant 2", "No"),
    ("ID Card — PoA holder", "No"), ("Power of Attorney Authorisation", "No"),
    ("Vakalatnama — Complainant 1", "No"), ("Vakalatnama — Complainant 2", "No"),
    ("Running account statement 2019-2025", "Yes"),
]
P(columnar(["S. No.", "Document Name", "Natively Digital"],
           [[f"{i}.", d, n] for i, (d, n) in enumerate(docs, 1)], ["10%", "70%", "20%"]))

P("<h2>4. Affidavit</h2>")
for para in AFFIDAVIT:
    P(f'<div class="para">{e(para)}</div>')
sigs = [("Lakshmi Menon", "PoA holder for Complainant 1"), ("Meera Nandakumar", "Advocate for Complainant 1"),
        ("Rajeev Pillai", "Authorised Representative for Complainant 2"), ("Meera Nandakumar", "Advocate for Complainant 2")]
P('<div class="sigs">' + "".join(
    f'<div class="sig"><div class="n">{e(n)}</div><div class="r">{e(r)}</div></div>' for n, r in sigs) + "</div>")
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
.sigs { display: grid; grid-template-columns: 1fr 1fr; column-gap: 24pt; row-gap: 20pt; margin-top: 24pt; }
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
