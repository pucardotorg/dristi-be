# Applications — court-side integration plan

How the court-side application screens in `dristi-fe-develop` move from their
in-browser sandbox to the backend described in
[`spec/0033-applications.md`](../spec/0033-applications.md) (PRD
`application-lifecycle.md` v41). This plan covers the **court side only**. The
filer side (raise, sign, pay, objections) is mentioned only where the court
screens need data from it.

---

## 1. Where things stand

### 1.1 Backend

| Piece | State on `main` | Needed for |
| --- | --- | --- |
| `apps.applications` (0033) | **Not built.** Spec only, on this branch | everything below |
| `apps.orders` (0025) | **Not built** (spec merged as a proposal) | every court act: onboard, defer, dismiss, decide, move date |
| `apps.workflows` (0011) `TaskService` | **Not built** | `review_application`, `decide_application` tasks. 0033 #1.2 derives court lists from statuses until it lands |
| `apps.organizations` court roles (0029) | Spec merged, code on `origin/feat/0029-court-roles` | `GET /court-roles/me/` (courtroom id), `orders.*` actions, `is_court_reader` |
| `apps.hearings` (0023) | Built | `next_hearing`, `business_date`, the signals that drive expiry, `PUT /orders/{id}/next-hearing/` holds |
| `apps.esign` (0015) | Built | signing orders (through 0025) |
| `apps.files` (0014) | Built, in-process only, no REST | document download (gap G1) |

### 1.2 Frontend (court side)

Every court application screen runs on browser data. Nothing calls the
backend yet.

| Concern | Where it lives now |
| --- | --- |
| Application records | `lib/applications/store.ts`: `localStorage` key `dristi.applications.v1`, sample seed `lib/applications/seed.ts` |
| Lifecycle rules | `lib/applications/lifecycle.ts` (written against PRD **v26**: temporary id, onboarding as a system act, etc.) |
| Court queue | `lib/employee/application-queue.ts`: `queueOf`, `applicationsIn`, `statusLine`, `objectionLine` |
| Court tasks | `lib/employee/application-tasks.ts`: `courtTaskOf`, `nextHearingOf` (fixture `NEXT_HEARING_IN_DAYS`), `courtDocumentOf` (rebuilt from the filer's form) |
| The order's Application item | `lib/employee/application-outcome.ts` (questions), `application-outcome-steps.ts` (what a triggered order does) |
| Applying triggered orders | `components/employee/application-order-triggers.tsx`, run **in the browser** behind a Web Lock |
| Order drafts | `lib/employee/order-drafts.ts` and `pending-orders.ts`, both in the browser |
| Hearing order's pending applications | `lib/employee/listing-applications.ts`, demo data |
| Older type-cut queues | `lib/employee/rescheduling-request.ts`, `delay-condonation.ts`, `other-applications.ts`, demo data, no actions, **not on the rail** any more |

The frontend's own rules (its `AGENTS.md`) say screens read through
`lib/<feature>/data/` repositories chosen by `NEXT_PUBLIC_DATA_SOURCE`, with
`http.ts` owned by engineering. Applications has no data layer yet, so the
first step is to add one (section 6).

---

## 2. Court screens reviewed, and the endpoint each one uses

| # | Screen / component (FE) | Route | Backend (0033 unless stated) | Diagram |
| --- | --- | --- | --- | --- |
| S1 | Review Applications list, `applications-screen.tsx` | `/employee/applications?view=` | `GET /applications/court-queue/?court=&view=&search=&page=` | [court-queue](sequence-diagrams/0033-application/court-queue.svg) |
| S2 | View pills and counts, `ViewPills` | same | `GET /applications/court-queue/counts/?court=` | court-queue |
| S3 | Rail entry *Review Applications*, `lib/employee/navigation.ts` | — | counts `views.onboard + views.decide` (0033 #14.5: only these two get a badge) | court-queue |
| S4 | Redirects `/onboard-applications`, `/decide-applications`, `/applications/{id}` | — | none, keep the redirects | — |
| S5 | Application pop-up, `application-dialog.tsx` (header, facts, paper switch) | `?open={id}` | `GET /applications/{id}/` (detail + court view, #14.3, #14.4) | [open-application](sequence-diagrams/0033-application/open-application.svg) |
| S6 | Paper: application, `ApplicationFacsimile` | — | `detail.document` (structured render, #6.5a) | open-application |
| S7 | Paper: objection, `ObjectionPaper` / `NoObjection` | — | `detail.objection`, `detail.objection_status` | open-application |
| S8 | Paper: previous orders, `OrderPaper` | — | `detail.orders[]` + `GET /orders/{id}/` (0025 #10.2) for the text | open-application |
| S9 | Decision panel, `application-decision-panel.tsx` | — | `detail.order_actions`, `can_draft_order`, `pending_order`, `suggested_date`, `case.next_hearing`, `task` | open-application |
| S10 | Quick order, `application-quick-order.tsx` | — | 0025: `POST /orders/` (preset `APPLICATION`), `PATCH items`, `PATCH text`, `POST data/complete`, `POST send-for-signing`, `POST sign` and `sign/confirm` | [review-by-order](sequence-diagrams/0033-application/review-by-order.svg), [decide-by-order](sequence-diagrams/0033-application/decide-by-order.svg) |
| S11 | Order screen on an application, `application-order-screen.tsx` | `/employee/applications/{id}/order` | 0025 order endpoints, opened on an existing order id | review-by-order |
| S12 | Application item pop-up in the order editor, `application-outcome-dialog.tsx` | — | 0025 `PATCH /orders/{id}/items/{item_id}/` with `APPLICATION_ACTION` values (0033 #8.2) | review-by-order |
| S13 | Trigger side effects, `application-order-triggers.tsx` | — | **removed**: the server's `APPLICATION_ACTION` handler does this (0033 #8.4) | review-by-order |
| S14 | Pending orders, `pending-order-screen.tsx` | `/employee/pending-orders` | 0025 `GET /orders/pending/` (an application order is an ordinary order) | — |
| S15 | Hearing order, Applications section, `order-door-screen.tsx` + `listing-application-dialog.tsx` | hearing order | `GET /cases/{case_id}/applications/?pending=true` + 0025 `POST /orders/{id}/items/` | [hearing-order-pending-applications](sequence-diagrams/0033-application/hearing-order-pending-applications.svg) |
| S16 | Court case view, Applications tab, `case-applications.tsx` with `reader="court"` | `/employee/cases/{case_id}` | `GET /cases/{case_id}/applications/?type=&status=&search=&page=` | open-application (last note) |
| S17 | Breadcrumb resolver, `employee-top-bar.tsx` | — | the number from the detail already loaded (no extra call) | — |
| S18 | Rescheduling request / Delay condonation / Others | `/employee/rescheduling-request` etc. | `GET /applications/court-queue/?court=&queue=rescheduling\|delay_condonation\|other` **or** retire (decision D4) | — |
| — | Approve copy application | `/employee/approve-copy-application` | **out of scope**: Certified Copy is not a 0033 type | — |

---

## 3. Data mapping

### 3.1 Identifiers and enums

| FE | Backend | Notes |
| --- | --- | --- |
| `ApplicationStatus` `"pending-review"` etc. | `status` `PENDING_REVIEW` etc. | one-to-one for all ten. Use `status_label` from the API for display |
| `ApplicationTypeId` (`lib/cases/applications.ts`) | `type.code` | `bail`→`BAIL`, `edit-litigant-details`→`EDIT_LITIGANT_DETAILS`, `settlement`→`CASE_SETTLEMENT`, `transfer`→`CASE_TRANSFER`, `withdrawal`→`CASE_WITHDRAWAL`, `condonation-of-delay`→`DELAY_CONDONATION`, `application-others`→`GENERIC`, `advancement-reschedule`→`ADVANCE_HEARING`, `postpone`→`POSTPONE_HEARING`, `poa-change`→`POA_CHANGE`, `production-of-documents`→`PRODUCTION_OF_DOCUMENTS`, `addition-of-witness`→`ADDITION_OF_WITNESS`, `warrant-by-hand`→`WARRANT_BY_HAND`, `absent-application`→`ABSENT_APPLICATION`, `reopen-evidence`→`REOPEN_EVIDENCE`, `objection`→`OBJECTION`. `certified-copy` and `warrant-recall` have no backend type. Court screens show `type.label` and branch on a code only for Advance / Postpone |
| `Side` `"complainant"` / `"accused"` | `side` `COMPLAINANT` / `ACCUSED` | |
| queue `"onboard" "decide" "signing" "later" "closed" "archive"` | `view` `onboard decide signing upcoming closed archive` (+ `all`) | **`later` = `upcoming`**. FE hides the Upcoming pill and shows those rows under All. Keep that, and read `band` from each row |
| `CourtSeat` (`magistrate`, `bench-clerk`, `typist`) | none. Use `can_draft_order` and the order's `allowed_actions` | 0029 `RLE-08`: never branch on a role or title |

### 3.2 `LifecycleApplication` → API

| FE field | API field (queue row Q, detail D) | Change in behaviour |
| --- | --- | --- |
| `id` | `application_id` (Q), `id` (D) | UUID |
| `caseId`, `caseOf(app)` fixture | `case {id, case_number, title, stage, advocates}` (Q), `case {…, courtroom, next_hearing}` (D) | no more `CASES` fixture lookup |
| `typeLabel` | `type.label` | |
| `temporaryId` / `applicationNumber` | `application_number` + `earlier_application_number` | **Model change.** v41 gives one number **from submission**, replaced at onboarding only in some states (Kerala yes, Gujarat no). Drop the *Temporary* label. Show `application_number`, with `earlier_application_number` beside it when set |
| `raisedBy ?? createdByName` | `filed_by` (Q), `raised_by.name` (D) | |
| `onBehalfOf` | `litigant.name` (D) | |
| `submittedOn` | `submitted_at` (Q, D), `filed_on` (D) | |
| `onboardedOn` | `onboarded_at` (D) | |
| `review.dueOn` / `review.defaultDueOn` | `review_due_date`, `task {kind: REVIEW, due_date, overdue, due_today, deferred}` | *Back after deferral* comes from `task.deferred` or `review_deferred`, no longer worked out on the client |
| `decide.dueOn` / `decide.mode` | `decision_date`, `task {kind: DECIDE, …}` | `mode: "now"` has no backend field. Onboard-and-decide-today ends Accepted/Rejected in one order. *List for a date* is just a decision-date move (#8.3) |
| `objectionsInvited`, `objectionDueBy`, `objectionId` | `objections_invited`, `respond_by`, `objection_status` (`NOT_CALLED_FOR`, `DUE`, `NONE_RECEIVED`, `FILED`), `objection` (D) | `objectionLine()` becomes a lookup on `objection_status` and `respond_by` |
| `pendingOrder` (legacy) and `orders[nextApplicationOrderKey]` | `pending_order {id, status, answers}` | one live order per application, keyed by the server's order id. Drop `application:<id>#n` keys |
| `orders[]` (`PassedOrder`) | `orders[] {id, number, title, signed_at, summary, deciding}` | text comes from `GET /orders/{id}/` (gap G2) |
| `linkedOrder` | `deciding_order {id, number, title, signed_at}` | |
| `decisionLabel` ("Partly allowed") | `outcome` + CIS outcome on the deciding order | see 4.1 |
| `workflowResult` | `workflow_summary`, `workflow_status` | |
| `courtDocumentOf(app)` | `document` (D) | stop decoding the filer's form on the court side |
| `nextHearingOf(app)` | `case.next_hearing`, `suggested_date` | drop `NEXT_HEARING_IN_DAYS` |
| `today()` (browser clock) | `today` on the court-queue response (courtroom business date, 0023 #4) | due/overdue badges and the title use the server's day |
| `history[]` | `history[]` | |

---

## 4. Behaviour the frontend has to change

These are the places where the FE rules (PRD v26 plus owner notes up to
2026-10-22) differ from spec 0033 / PRD v41. Each needs a FE change, or a
product decision where marked **D**.

### 4.1 The Application item's questions

| FE `application-outcome.ts` | 0033 #8.2 (`APPLICATION_ACTION` values) | Action |
| --- | --- | --- |
| `onboard` yes/no, default yes | `onboard` bool, default true, fixed true once onboarded | same |
| `decided` "", no default | `decides` bool, **default false** (`ALC-25`) | start the item at No |
| `decision`: Allowed, Partly allowed, Disallowed, Disallowed with cost, Disposed, mapped to a status by `CLOSES` | `outcome` `ACCEPTED`/`REJECTED`, or `DISMISSED` only when not onboarding. Plus `cis_outcome` from `applications.<STATE>.cis_outcomes`, **asked only where the state sets it** (P&H, not Kerala) | replace the five words with Accept/Reject (Dismiss before onboarding). Show the state's CIS list as a separate question. Remove `CLOSES`: a CIS word never maps to a status (`ALC-36`) |
| `workflowTriggered` yes/no | **none**: acceptance always runs the type's workflow (`ALC-16`) | remove the question and `applicationWorkflow()` |
| `responseNeeded`, asked whenever decided = no | `respond`, asked only when onboarding/onboarded, not deciding, and `bring_back_on` is **after today** (`ALC-11`) | hide when deferring review, and for a date of today |
| `respondBy` | `respond_by`, default the day before `bring_back_on`, not after it | |
| `bringForwardOn` | `bring_back_on`, default `suggested_date`, **today allowed** (`ALC-08`, `ALC-15`) | FE refuses `<= today` in several places (`onboard`, `listForLater`, `moveDecisionDate`, `setReviewDate`). Allow today |

Validation messages come back as order problems (`409 E11012`, item problems
`DATE_IN_PAST`, `RESPOND_BY_INVALID`, `OUTCOME_NOT_ALLOWED`,
`CIS_OUTCOME_INVALID`, `HEARING_MOVE_REQUIRED`). Show them on the item. Keep
the client checks only as hints.

### 4.2 Court acts are server-side order effects

* Delete the client-side application of triggered orders:
  `application-order-triggers.tsx`, `application-outcome-steps.ts`,
  `application-order-outcome.ts`, and the `draftOrder` / `signOrder` /
  `discardOrder` / `onboard` / `listForLater` / `moveDecisionDate` /
  `setReviewDate` steps in `lifecycle.ts`. The server's handler does all of
  it, once, under a lock (0033 #8.4).
* Withdrawn order items `accept-application`, `reject-application`,
  `dismiss-application` (and *Acceptance of bail*) become one contextual item,
  `APPLICATION_ACTION` (catalogue #27). `decisionItem()` in
  `application-order-draft.ts` and `KIND_OF_ITEM` go.
* The application changes **after** the order triggers, and that happens in a
  Dramatiq worker (`run_order_workflows`, 0025 #9.1). After `sign/confirm` or
  `data/complete`, poll `GET /applications/{id}/` until `pending_order` is
  null (short backoff, a few tries), then refetch counts and the view. If a run
  fails with `APPLICATION_NOT_IN_STATUS`, the order stands and the application
  is unchanged. Show the reloaded state; there is no error to report.
* An order that does not carry the item leaves the application and its task
  alone (`ALC-18`). *Pass a different order instead* stays as it is.

### 4.3 Who may do what

* `canTakeSystemAction`, `canDraftOrder` and `canSignOrder` in `lifecycle.ts`
  come out. Show the panel's options when `can_draft_order` is true, and the
  order's buttons from its `allowed_actions` (0025 #10.2).
* The rule "the bench clerk takes system actions for now" (owner, 2026-10-13)
  now belongs to court-role configuration: the bench clerk title holds
  *Order drafter* (0029). Nothing about it stays in FE code.
* Any staff member on the courtroom list may read. A staff member of another
  courtroom gets `404 E00105`.

### 4.4 Queue rules

| FE today | Backend | Action |
| --- | --- | --- |
| `queueOf` ignores `expired` | `closed` / `archive` include `EXPIRED` | add an Expired badge |
| `signing` only for legacy `pendingOrder`. A new-style order under way shows *Order · Drafting* but **stays** in onboard/decide | any live order with the item puts the row in `signing` **only** | **D1**: accept the backend rule (spec #14.5: "so the bench does not start a second order"), or ask for `signing` to cover only orders sent for signing |
| `ARCHIVE_AFTER_DAYS = 30` hard-coded | `applications.closed_view_days` config | read from the API, not the client |
| `nextWorkingDay` skips Sat and Sun | Sunday + `HOLIDAY` entries, configurable (`ALC-03`, #6.9) | the client never computes due dates; it shows `review_due_date` |
| search on type, cause title, case number, both numbers | same fields, server-side `search=` | debounce, and reset to page 1 |
| no paging | paginated | add paging (the screen uses `QueueAnnouncer` already) |

### 4.5 Advance / Postpone accepted

The FE carries the new date as `draft.next = "list"` with `nextDate` in the
browser draft. Backend: the accepting order has to move the hearing itself
(`HEARING_MOVE_REQUIRED`, #8.2). That means
`PUT /orders/{id}/next-hearing/ {state: LISTED, date, purpose}`, which places a
0023 hold and adds a *Rescheduling of hearing date* item (0025 #6.4). The
quick order's date field (`needsHearingDate`) calls that endpoint, and shows
the 0023 warnings (full day, adjournment limit) it returns.

### 4.6 The quick order against real orders

The quick order now does *data complete → send → sign* in one click. On the
backend it is a sequence of calls, and signing leaves the page:

1. `POST /orders/` with `preset {kind: APPLICATION, application_id}`, or
   reopen `pending_order.id`. Never create a second live order.
2. `PATCH /orders/{id}/items/{item_id}/` with the panel's answers
   (`If-Match: d-n`).
3. `PATCH /orders/{id}/text/` with the words (`If-Match: t-n`).
4. Settle the next hearing. Outside a hearing it starts as the case's listed
   hearing. With no listed hearing, the order needs a date or
   `NOT_LISTED_AGAIN` before sending, otherwise `409 E11006`.
5. `POST /orders/{id}/data/complete/`, then `POST /orders/{id}/send-for-signing/`.
6. Signer only: `POST /orders/{id}/sign/` returns `esign_url` and
   `form_fields`. The browser posts to CDAC and comes back, then
   `POST /orders/{id}/sign/confirm/`. The return URL has to bring the user back
   to `/employee/applications?view=&open={id}`.

*Open in order screen* goes to `/employee/applications/{id}/order` on the
same server order id (no browser draft key).

---

## 5. Backend spec gaps found in this review

Raise these on the 0033 / 0025 PRs before implementation starts.

| # | Gap | Proposal |
| --- | --- | --- |
| G1 | **No way to download a submitted application's files.** `preview?format=pdf` is limited to the drafting circle before signing. The court pop-up's *Download* and *Full view* need the signed application and every supporting/field document, and `apps.files` has no REST API | `GET /applications/{id}/documents/{doc_id}/` streaming the file (same path as the spec's `DELETE`, and the `dristi-requests/{id}/documents/{doc_id}/` pattern), visible to anyone who can read the application. List the signed application as the first document with its own id (#14.3 already lists it first) |
| G2 | `orders[]` has no order text. `OrderPaper` shows the words | read `GET /orders/{id}/` (`rendered_html`) when the switch selects an order, so nothing is duplicated. Make sure court readers without order roles may read it ("court staff of the courtroom", 0025 #11.1, already allows this) |
| G3 | 0025 #5.2 still lists presets `ACCEPT`, `REJECT`, `DISMISS`, `ACCEPT_BAIL`, catalogue rows #5/#6/#13/#26, and the `APPLICATION_NOT_ONBOARDED` / `APPLICATION_ONBOARDED` availability reasons | amend 0025 to `preset {kind: APPLICATION, application_id}` and one `APPLICATION_ACTION` item, as 0033 #8.1 asks. Also decide what replaces `"onboarding": true` for preselecting the `APPLICATION_ONBOARDING` order type (`OTY-03`), e.g. preselect when the application is `PENDING_REVIEW` |
| G4 | The court queue is keyed by `court={courtroom_id}`, but the FE session (`lib/employee/session.ts`) only has a display name | needs 0029 `GET /court-roles/me/` merged, and the FE stores the chosen courtroom id at login |
| G5 | The trigger runs asynchronously, so the client cannot tell when the application has moved | polling `pending_order` works (section 4.2). Optionally the order detail could expose its workflow runs' state so the client polls one resource |
| G6 | Detail does not say whether accepting will need a hearing move | the client checks `type.code ∈ {ADVANCE_HEARING, POSTPONE_HEARING}`. Optionally add `type.moves_hearing` |
| G7 | `GET /applications/?court=` (#14.4) and `court-queue` overlap | the FE uses `court-queue` only. Drop the former or keep it for exports |
| G8 | The FE has no "deferred N times" on the row; spec gives `review_deferred` + count on the detail only, `task.deferred` on the row | fine as is. Noted so the row badge reads `task.deferred` |
| G9 | Without 0011 and 0025, 0033 #1.2 offers an admin action *Record order on application* | until 0025 lands the FE panel in `api` mode shows options disabled ("Orders are not connected yet"), using `NotIntegratedError` from the orders repository. It never falls back to client-side changes |

---

## 6. Frontend implementation plan

Follow the FE repo's data rules: screens call a store/hook; the store calls a
repository; `http.ts` maps backend shapes to app types.

### 6.1 New data layer: `lib/applications/data/`

```text
lib/applications/
├── types.ts            # CourtApplicationRow, CourtApplication (detail), CourtQueueCounts, enums
├── data/
│   ├── repository.ts   # contract (grows only)
│   ├── sandbox.ts      # wraps today's store.ts + lifecycle.ts, so dev:sandbox keeps working
│   ├── http.ts         # engineering: lib/api calls + mapping
│   └── index.ts        # repositoryFor("applications", {sandbox, http})
```

Contract, court side:

```ts
interface ApplicationsRepository {
  courtQueue(q: { court: string; view?: CourtView; queue?: TypeQueue; search?: string;
                  type?: string; side?: Side; stage?: string; ordering?: string; page?: number })
    : Promise<Page<CourtApplicationRow> & { today: string; facets: Facets }>;
  courtQueueCounts(court: string): Promise<CourtQueueCounts>;
  getApplication(id: string): Promise<CourtApplication>;          // detail + court view
  caseApplications(caseId: string, q: CaseListQuery): Promise<Page<CaseApplicationRow>>;
  pendingOnCase(caseId: string): Promise<PendingApplication[]>;   // ?pending=true
  documentUrl(id: string, docId: string): Promise<string>;        // G1
}
```

Court acts go through the **orders** repository (`lib/orders/data/`, a
separate 0025 integration), with one helper for this flow:
`openApplicationOrder(caseId, applicationId)` → `POST /orders/` with the
preset, or the existing `pending_order.id`.

### 6.2 Screen changes, in order

| Step | Change | Files |
| --- | --- | --- |
| F1 | Add the data layer and types. The sandbox implementation adapts today's `LifecycleApplication` to the new types, so the screens switch over first and the sandbox keeps working | `lib/applications/data/*`, `types.ts` |
| F2 | Queue on the repository: server paging, search, `view`, `band`, `today`, counts. Rename `later` → `upcoming` at the mapping boundary only | `applications-screen.tsx`, `application-queue.ts` (`statusLine` reads `task` / `status_line`), `views.ts` |
| F3 | Rail badge from `courtQueueCounts` (onboard + decide) | `navigation.ts`, `employee-top-bar.tsx` |
| F4 | Pop-up on `getApplication`: facts from `task`, `objection_status`, `case.next_hearing`, numbers; papers from `document`, `objection`, `orders[]`; download via G1 | `application-dialog.tsx`, `application-tasks.ts` (drop `caseOf`, `nextHearingOf`, `courtDocumentOf`) |
| F5 | Panel offers `order_actions` when `can_draft_order`; `pending_order` shows *Order awaiting signature / Open order*. Allow today as a date | `application-decision-panel.tsx` |
| F6 | Application item = 0033 #8.2 (section 4.1) | `application-outcome.ts`, `application-outcome-dialog.tsx`, `order-editor.tsx` |
| F7 | Quick order and order screen on server orders (section 4.6); delete client triggers (section 4.2) | `application-quick-order.tsx`, `application-order-screen.tsx`, `application-order-draft.ts`, remove `application-order-triggers.tsx`, `application-outcome-steps.ts`, `application-order-outcome.ts` |
| F8 | Hearing order's pending applications from `pendingOnCase`, decided through `APPLICATION_ACTION` | `order-screen.tsx`, `order-door-screen.tsx`, `listing-application-dialog.tsx`, retire `listing-applications.ts` |
| F9 | Court case view Applications tab on `caseApplications` (court reader sees every submitted application, both sides, from submission: `ALC-17`. The FE comment "the other side's applications appear only once the court has onboarded them" is out of date) | `case-applications.tsx`, `application-access.ts` |
| F10 | Type-cut queues: either `courtQueue({queue})` or redirect to `/employee/applications` with a type filter (**D4**) | `rescheduling-request*`, `delay-condonation*`, `other-applications*` |
| F11 | Remove the PRD-v26 parts of `lifecycle.ts` used only by the court side (temporary id, `visibleToSeat` court rules, seats) once the filer side has also moved | `lifecycle.ts`, `store.ts`, `seed.ts` |

F1–F5 and F9 need only the **read** endpoints of `apps.applications`. F6–F8
need 0025.

---

## 7. Backend implementation order (court side)

| Step | Work | Unblocks |
| --- | --- | --- |
| B1 | Allocate domain `13`. Models, enums, `errors.py`, type registry with seeded `ApplicationType` rows, transition log, numbering (submission number) | — |
| B2 | Filing services up to `submit()` (so there is data). Until the filer side is integrated, a **dev-only** command creates submitted applications on a registered case (**D5**: reference data goes in `data/seed/`, but demo applications are not reference data, so this needs a home, e.g. factories behind `DEBUG`) | FE work against real data |
| B3 | `access.py` (`is_court_reader` through `ports.py` until 0029 lands), selectors, and the read endpoints: `court-queue`, `court-queue/counts`, `GET /applications/{id}/` with the court view, `GET /cases/{case_id}/applications/` (+ `?pending=true`), document download (G1). Court lists come from statuses (#1.2 stand-in for 0011). `pending_order` is null until 0025 exists | F1–F5, F9, F10 |
| B4 | `actions.apply` + the admin action *Record order on application* (#1.2), so QA can move applications before 0025 lands | QA of the read screens across every status |
| B5 | With 0025: register `APPLICATION_ACTION` (`unavailable_reason`, `validate_target`, `defaults`, `validate`, `summary`, `execute`), `live_items_targeting` → `pending_order`, the preset `{kind: APPLICATION}` | F5–F8 |
| B6 | Expiry receivers + 00:05 IST sweep; `run_type_workflow` | Expired rows, `workflow_summary` |
| B7 | With 0011: real `review_application` / `decide_application` tasks; `task` and the counts read tasks instead of statuses. The API shape stays the same | — |

Each endpoint documents its codes with `error_responses(...)`, and its tests
assert `code` / `field` (repo `AGENTS.md`).

---

## 8. Error handling on the court screens

| Code | Where | FE behaviour |
| --- | --- | --- |
| `404 E00105` | detail of another courtroom's or an unsubmitted application | "This application is not available", close the pop-up, refetch the list |
| `409 E11012` + item problems | `data/complete` | show each problem on the Application item; keep the quick order open |
| `409 E11006` | `send-for-signing` without a settled next hearing | ask for a date or *Not listed again* |
| `409 E11009` | adding a second `APPLICATION_ACTION` for one application to an order | "This order already answers that application" |
| `409 E11008` `APPLICATION_NOT_OPEN` | adding the item to a decided, draft or expired application | refetch the detail; the panel shows the closed record |
| `412 E11002` | stale `If-Match` on text or items | reload the order, keep the user's typed text in the editor, ask them to retry |
| `0023 E100xx` + `warnings` | `PUT next-hearing` | show as the hearings screens do |
| run `APPLICATION_NOT_IN_STATUS` (not an HTTP error) | after polling | show the reloaded state; another order got there first |

---

## 9. Acceptance scenarios (court side, `NEXT_PUBLIC_DATA_SOURCE=api`)

Taken from 0033 #17.10, as seen from the court screens:

1. **E-01**: a Postpone filed by a clerk and paid shows in *To onboard*, due
   the next working day. The order onboards it for a date with a response
   asked → the row moves to *Upcoming* under All, then *To decide* on the day,
   with `objection_status` going `DUE` → `FILED`. The order accepts it and
   moves the hearing → Closed, *Accepted*, `workflow_summary` "Hearing
   rescheduled to …".
2. **E-02**: one order onboards and accepts a Bail the same day →
   *To onboard* → Closed, with two entries in `orders[]` history (onboard,
   accept) from one order.
3. **E-03**: deferred once, then dismissed → *To onboard* → *Upcoming*
   ("Review deferred to …") → *To onboard* ("Back after deferral") → Closed,
   *Dismissed*, number never replaced.
4. **E-04**: Advance onboarded for a date, then its hearing moved by the court
   → Closed, *Expired*.
5. While an order on an application is drafted or awaiting signature, the row
   sits in `signing` only, and the pop-up offers *Open order*, not a second
   one (T-132).
6. The rail badge equals `onboard + decide` from counts (T-134).
7. A staff member of another courtroom opening `?open={id}` gets the
   not-available state (`404 E00105`).

---

## 10. Decisions needed

| # | Question | Owner |
| --- | --- | --- |
| D1 | Should an application with a merely **drafted** order leave *To onboard* / *To decide* for `signing` (backend rule), or stay until the order is sent for signing (FE today)? | product / FE owner |
| D2 | Kerala records no CIS outcome, so its bench only says Accept / Reject. Confirm the FE drops Allowed / Partly allowed / Disallowed / Disallowed with cost / Disposed outside states that list them (`Q-15`) | product |
| D3 | *Dismiss* after onboarding is not allowed in v41 (`ALC-36`), but the FE offers *Disposed* on an onboarded application. Confirm it is removed | product |
| D4 | Keep the type-cut queues (Rescheduling request, Delay condonation, Others) on `?queue=`, or retire them? They are off the rail already | FE owner |
| D5 | Where does dev/demo data for applications live, given `data/seed/` is for reference data only? | backend |
| D6 | Polling after trigger (section 4.2), or should 0025 expose run state on the order? | backend |

---

## 11. Sequence diagrams

Rendered with `mermaid-cli`, the same renderer the other diagrams in
`docs/sequence-diagrams/` use. The sources are next to the SVGs:

```bash
cd docs/sequence-diagrams/0033-application
for f in src/*.mmd; do
  n=$(basename "$f" .mmd)
  docker run --rm -u "$(id -u):$(id -g)" -v "$PWD":/data minlag/mermaid-cli \
    -i "/data/src/$n.mmd" -o "/data/$n.svg" -b white
done
```

| Diagram | Covers |
| --- | --- |
| [court-queue.svg](sequence-diagrams/0033-application/court-queue.svg) | S1–S4: courtroom id, counts, list, pills, archive, search, paging |
| [open-application.svg](sequence-diagrams/0033-application/open-application.svg) | S5–S9, S16: the pop-up, its papers, downloads, which panel shows |
| [review-by-order.svg](sequence-diagrams/0033-application/review-by-order.svg) | S10–S13: onboard / defer / dismiss through an `APPLICATION_ACTION` order, signing, the async trigger, polling |
| [decide-by-order.svg](sequence-diagrams/0033-application/decide-by-order.svg) | accept / reject / move date, the hearing move for Advance / Postpone, type workflows, expiry |
| [hearing-order-pending-applications.svg](sequence-diagrams/0033-application/hearing-order-pending-applications.svg) | S15: deciding applications inside a hearing's order |
