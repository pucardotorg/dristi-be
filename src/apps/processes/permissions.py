"""Who may read processes (spec 0028 #2.5, #11.5).

* Court staff of the round's courtroom read every process of it (``RLE-06``).
* Parties of the case read its register and its processes.
* Anyone else, staff of another courtroom included, is told it does not exist
  (``404 E00105``), never ``403``.

Steps are not checked here: each service checks its own action (``steps.check``).
"""

from rest_framework.exceptions import NotFound

from apps.cases.selectors import case_ids_visible_to, get_case_summaries

from . import ports, selectors


def is_party(user, case_id):
    return case_ids_visible_to(user).filter(pk=case_id).exists()


def require_court_reader(user, court_id):
    """Refuse a court list to anyone not staff of that courtroom."""
    if not ports.is_court_reader(user, court_id):
        raise NotFound("Court not found.")


def visible_process(user, process_id):
    """Return the process if the caller may read it, else raise ``NotFound``."""
    process = selectors.processes().filter(pk=process_id).first()
    if process is None or not (
        ports.is_court_reader(user, process.round.court_id) or is_party(user, process.case_id)
    ):
        raise NotFound("Process not found.")
    return process


def visible_processes(user, process_ids):
    """Return the processes for a step on several, refusing all if any is not visible."""
    return [visible_process(user, process_id) for process_id in process_ids]


def require_case_reader(user, case_id):
    """Court staff of the case's courtroom, or a party of the case; else ``NotFound``."""
    summary = get_case_summaries([case_id]).get(case_id)
    if summary is None or not (
        (summary.court_id and ports.is_court_reader(user, summary.court_id))
        or is_party(user, case_id)
    ):
        raise NotFound("Case not found.")
