"""The court actions of the process module (spec 0028 #2.1, spec 0029 #3.3).

Every one is taken at a courtroom and held for a scope of process types and
channels (``RLE-09``). Code refers to them by these constants, never by the
string. Spec 0029's ``define()`` registry does not exist yet: when it lands,
each line becomes ``define(code, COURTROOM, label, group=..., scoped=True)``.
"""

RECEIVE_ENVELOPE = "process.receive_envelope"
SIGN = "process.sign"
SEND = "process.send"
RECALL = "process.recall"
RECORD_OUTCOME = "process.record_outcome"

ALL = (RECEIVE_ENVELOPE, SIGN, SEND, RECALL, RECORD_OUTCOME)
