# Templates

**Status:** v2.8 — 2026-11-27; `Q-1` answered: the feature keeps the name **template**. v2.7 — 2026-11-27; `Q-3` answered: a variable that cannot be filled is left as written, and filling a template reports that one or more variables could not be filled, so the screen can act on it (`TMP-20`, new, §2.1). v2.6 — 2026-11-27; Additional details templates can be for all case types or one, like the order text (`TMP-18`, `TMP-19`); they have variables only when they are for one case type (`TMP-11`). v2.5 — 2026-11-27; **one table says what each screen gets** (§1.1, `TMP-17`–`TMP-19`, new): its case type, whether it has variables and whether it has typing shortcuts. **Additional details templates are for one case type.** §2.3 is folded into it: `TMP-08a` and `TMP-16` dropped, their reasons now after the table. `TMP-14` points to §1.1. v2.4 — 2026-11-27; `TMP-11` and the Enhancements bullet on common variables reworded: a template common to all case types. v2.3 — 2026-11-27; **a template for all case types has no variables** (`TMP-11`), with the reason; using fields common to every case type moves to Enhancements. v2.2 — 2026-11-27; §2.3 reframed: each screen gets the part of templates it needs most in this version, with the reason for each screen; the reason that variables need more computation is removed. v2.1 — 2026-11-27; a template's case type, owner and screens are one attribute, **Scope** (`TMP-03`); `TMP-04` and `TMP-05` dropped. v2 — 2026-11-27; **now a PRD**, owning what a template is for every screen that uses one: order generation §5.1, bulk filing §3.5 and e-filing `PRY-1` link here. §1 links the screens' PRDs; `TMP-07`, `TMP-11` and `TMP-14` link the PRDs they rest on. To discuss is now Open questions (§5): the name (`Q-1`), the default template's text (`Q-2`, moved from bulk filing `Q-18`), and a variable with no value or several values in individual filing (`Q-3`). `TMP-13`: on any device, carried over from order generation `SHC-06`. Linked records added. v1.7 — 2026-11-20; To discuss settled except the name: the Additional details field takes templates in individual filing as well as bulk filing (`TMP-14`); every filer is given the same default Additional details template, which then belongs to them (`TMP-13a`, new); variables for data outside e-filing, such as the case number, added to Enhancements; what happens to all-case-types templates is left until a new case type is added. v1.6 — 2026-11-20; new §2.3 **In this version**: variables only in the Additional details field (`TMP-08a`, moved from §3.3) and typing shortcuts only on the order text (`TMP-16`, new), with the reason for the first; the two Enhancements on variables and shortcuts become one on bringing both to every screen. v1.5 — 2026-11-20; Open questions is now **To discuss** (§5), a numbered list with no IDs or Blocking column. v1.4 — 2026-11-20; a concept note, not yet a PRD: no references to other documents. `TMP-11` names the sections common to every case type; §1, `TMP-07` and `Q-4` to `Q-7` reworded without links; Linked records removed. v1.3 — 2026-11-20; `TMP-08` gives examples of the variable format (curly or square brackets). `TMP-08a` moves to §3.3, with its reason directly after it, reworded: a more complex build, more that can break, and more computation each time a template is inserted. v1.2 — 2026-11-20; **typing shortcuts** (`TMP-15`, new, §2.2): a template can be inserted while typing with a specific key followed by its name; a shortcut is not a separate thing. Template text no longer mentions blanks (`TMP-02`). v1.1 — 2026-11-20; `Q-1` answered: in this version, a template used on the order text has no variables (`TMP-08a`, new, §2.1); variables on the order text added to Enhancements. v1 — 2026-11-20; first version. A template is predefined text, with variables, that a user saves and inserts where they type. One model covers the order drafter's shortcuts ([`order-generation.md`](order-generation.md) §5.1) and the filer's Additional details templates ([`bulk-filing.md`](bulk-filing.md) §3.5). Scope has three parts: case type, users and screens (§3). Open questions `Q-1` to `Q-7`.

## 1. Context

People type the same text again and again: an order drafter writing orders, a filer writing
the Additional details of a case. A **template** is a piece of text they save once and
insert wherever it applies. It can contain variables, which are filled from the case.

This document owns what a template is, its variables and its scope. What each screen does
with a template is set by the PRD that owns the screen.

### 1.1 Where templates are used

Each screen gets, in this version, the part of templates it needs most.

| ID | Screen | Used by | Owning PRD | Case type | Variables | Typing shortcut |
| --- | --- | --- | --- | --- | --- | --- |
| `TMP-17` | Order text | Order drafter | [`order-generation.md`](order-generation.md) §5.1 | All, or one | No | Yes |
| `TMP-18` | Additional details, bulk filing | Filer | [`bulk-filing.md`](bulk-filing.md) §3.5 | All, or one | Yes, in a template for one case type (`TMP-11`) | No |
| `TMP-19` | Additional details, individual filing | Filer | [`efiling.md`](efiling.md) §12, `PRY-1` | All, or one | Yes, in a template for one case type (`TMP-11`) | No |

*In Additional details, the filer writes one text for many cases, so a template is only useful if each case's own values are filled in: variables are the point of it there. The filer chooses the template once for the batch, so inserting it by typing adds little.*

*On the order text, the order drafter writes for one case, with that case in front of them. What saves time is calling up text quickly without leaving the keyboard. Variables there would take the build a step further, since the system would have to look up each value in the case as the template is inserted, and they add more that can break, for less gain.*

## 2. A template

| ID | Attribute | Detail |
| --- | --- | --- |
| `TMP-01` | Name | The name the user calls the template up by. |
| `TMP-02` | Text | Formatted text. It can contain variables (§2.1). |
| `TMP-03` | Scope | The case types, users and screens the template applies to (§3). |

### 2.1 Variables

| ID | Requirement |
| --- | --- |
| `TMP-06` | A variable stands for a field of the e-filing flow. Where the template is used, it is replaced by that case's value for the field. |
| `TMP-07` | A variable is identified by two things: the name of the field's section in [`efiling.md`](efiling.md), and the field's own name within that section, for example the Accused Details section and Full Name (`ACC-2`). |
| `TMP-08` | A variable is written in the text in one specific format; all other text is plain text. The format, for example the field's name in curly brackets (`{Full Name}`) or in square brackets (`[Full Name]`), is settled by engineering when it is built. |
| `TMP-20` | **[OWNER]** Where a variable cannot be filled, because the case has no value for it or more than one (two accused, two cheques), it is left in the text as written. Filling a template reports whether one or more of its variables could not be filled, so that the screen using it can act on that. |

### 2.2 Typing shortcuts

| ID | Requirement |
| --- | --- |
| `TMP-15` | **[OWNER]** On the screens that have them (§1.1), while typing, the user can insert a template with a **typing shortcut**: a specific key followed by the template's name fills in the template's text. A typing shortcut is only a way to insert a template, not a separate thing the user saves. |

## 3. Scope

A template's scope has three parts: the case types it can be used in, the users it belongs
to, and the screens it is offered on.

### 3.1 Case type

| ID | Requirement |
| --- | --- |
| `TMP-09` | A template applies either to **all case types** or to **one case type**. |
| `TMP-10` | A template for one case type can use any field of that case type as a variable. |
| `TMP-11` | **[OWNER]** A template that is common to all case types has no variables. |
| `TMP-12` | A template is offered only in a case whose case type is in its scope. |

*With two case types, a filer who wants the same text with variables in both can save one template for each case type. That is simpler than the system tracking which sections are exactly the same across case types, and keeping that up to date as case types are added.*

### 3.2 Users

| ID | Requirement |
| --- | --- |
| `TMP-13` | A template belongs to the user who created it. Only they see, use and maintain it, on any device. |
| `TMP-13a` | **[OWNER]** Every filer is given one default Additional details template. The same template is added for every filer, and each filer's template belongs to them. Its text is still to be written (`Q-2`). |

### 3.3 Screens

| ID | Requirement |
| --- | --- |
| `TMP-14` | In this version, templates are offered on the screens in §1.1. The user does not choose screens for a template. |

## 4. Enhancements

- **Sharing.** In a later version, the owner can share a template with others, for example
  with their office or with everyone in their courtroom.
- **Choosing screens.** In a later version, the user chooses the screens a template is
  offered on. On the court side, templates may come to other screens where text is typed,
  such as the deposition screen. On the filer's side, a template may be limited to the
  Additional details field or to one type of application.
- **Variables and typing shortcuts on every screen.** In a later version, the restrictions
  of §1.1 are removed: templates on the order text can carry variables, and typing
  shortcuts work in the Additional details field.
- **Variables common to every case type.** In a later version, a template that is common
  to all case types can use fields from the sections that are exactly the same in every case type.
- **Variables beyond e-filing.** In a later version, a variable can also stand for data
  that is not an e-filing field, such as the case number.

## 5. Open questions

| ID | Question | Blocking |
| --- | --- | --- |
| `Q-2` | To do: write the default Additional details template every filer is given (`TMP-13a`). | No |

## Linked records

Live views of the master tables, filtered to this document. Each master table is the
single source of truth and the place to edit its rows; anything tagged `templates` there
appears here automatically. A downloaded copy of this document is a snapshot.

### Pending tasks (Court Side)

```superhuman-view
name: Pending tasks (Court Side) — Templates
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-KztrhvteSD
filter: PRDs.Contains("templates")
```

### Pending tasks (Citizen-Side)

```superhuman-view
name: Pending tasks (Citizen-Side) — Templates
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-PQWgeMeH-g/tables/grid-FICRZ0qIR4
filter: PRDs.Contains("templates")
```

### Notifications

```superhuman-view
name: Notifications — Templates
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-xnftvTkudd/tables/grid-3FTjQhdfYv
filter: PRDs.Contains("templates")
```

### Events

```superhuman-view
name: Events — Templates
tableUri: superhuman://docs/KtL_rwN6Qw/pages/section-2x28DoUtbn/tables/grid-GPg4dKS-s9
filter: PRDs.Contains("templates")
```
