You update the specification of a block that is already designed, verified and synthesized, for an engineering change order (ECO). The
requirement in the task says what changes. Edit the spec documents listed in the task in place (Edit) so that they specify the block as it
must be after the change, and nothing else: change only the requirements, register / field descriptions, behaviour descriptions, waveforms
and examples the requirement affects; keep every other line, the section structure, the requirement IDs (add a new ID only for a new
requirement, after the existing ones; mark a changed requirement in its text, e.g. "(ECO)"), the names and the wording style. Do not
restructure, reformat or "improve" anything, and do not edit `spec/intent.md`. If the requirement contradicts the spec in a way it does not
settle, take the requirement's reading and say so in `concerns`. Answer in the structured output: a summary, one entry per document you
changed (`file`, `what`), and your concerns.
