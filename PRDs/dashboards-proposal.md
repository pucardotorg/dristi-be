# Dashboards — proposal to spin off

We need dashboards for court operations and case movement. This is distinct from product analytics (adoption, click paths, UX issues) — that stays with the core team.

The current dashboards are not user-friendly and don't let us monitor things effectively. There is low-hanging fruit here.

## Who needs what

**High Court (governance)**
A monitoring view into the court. Key metrics: disposal rates, pendency, time between hearings, aging of cases. Should make it easy to spot whether things are running well, whether anything is getting worse or better, and flag anomalies.

**Court (magistrates, courtroom officers, staff)**
The same numbers the High Court sees — because if the High Court is going to evaluate a magistrate's performance against these metrics, the magistrate and their staff should be able to see them too and course-correct. Can also be more operational: upcoming deadlines, overdue matters, workload distribution.

**Public**
A subset of the High Court view — whatever the High Court is comfortable making public. Serves researchers, litigants, civil society, anyone working with court data.

## Why spin this off

Most of our work requires close collaboration, frequent meetings, and deep orientation into the tech stack and our proposals. Dashboards are different. Someone who already works in the dispute resolution / justice innovation space, understands how courts operate, and knows what metrics matter can take this on as a problem statement. They just need a rough idea of what data a digital court system produces.

We should aim for something simple and deployable — not a custom query builder or an overambitious analytics platform.

## What we provide

- A description of what data the system records and can make available (case events, hearing records, orders, filing data, timelines)
- The separation between what is internal / what can be public
- Feedback on drafts

## What we need from them

- Dashboard design and build for the three audiences above
- Opinionated choices about which metrics matter and how to present them — they should bring that judgment, not wait for us to spec every chart
- Feedback on what additional data the system needs to capture for their dashboards to work

## Who will do this

Someone (individual or small team) who:

- Has worked in the dispute resolution or justice innovation space and understands how Indian courts operate — case flow, hearing cycles, pendency, disposal
- Knows which metrics matter for court performance and why, without needing us to define them
- Can design and build dashboards, not just spec them — they can bring on additional design or data capabilities if needed
- Can work from a problem statement and a data description rather than a detailed brief

They do not need to know our tech stack, our codebase, or our product design. That's the point — this is the one piece of work where that orientation isn't necessary.

## Also useful to us

The same court-operations data can help the PUCAR team internally — identifying where to intervene, which courts need support, where process bottlenecks are. This doesn't need to be a separate dashboard; it can be the governance view with internal annotations or filters.
