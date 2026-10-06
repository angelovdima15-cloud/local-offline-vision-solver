READ = """Read ALL original pages jointly as ONE task. Do not solve yet.
Preserve exponents, fractions, signs, units, diagrams, map labels, options and question numbers.
Reconstruct logical page order; original page numbers are the labelled upload indices.
Transcribe the complete source including articles and data needed for later questions.
Give each question/subquestion a unique stable id. Include diagram facts in the transcription.
Identify primary instructional language en/ru/kk, subject and task type.
Check blur, perspective, page truncation, missing continuation pages and unclear symbols.
Do not infer an absent map value or complete an illegible sentence by guessing.
Record every material ambiguity in uncertainties, including alternatives and fractional original
crop_box [left, top, right, bottom] or null. sufficient_information is false if required
information is absent. Contrast variants and detail crops are alternatives to originals,
not extra pages. Reading quality flags are hints, not proof that a page is unreadable.
"""

SOLVE = """Solve the entire task using ALL originals, the source transcription and classification.
Treat article continuations, question pages and options as a single context.
Use the task language for every prose answer (including Kazakh); preserve requested English
writing when the exercise explicitly asks for it. Answer every question and subquestion.
Mathematics: complete derivation, intermediate calculations, final result.
Physics: knowns, unknowns, formulas, substitutions, calculations, SI units and result.
Computer science: identify theory/algorithm/code/logic task; provide complete requested code.
English/IELTS: identify writing/reading/grammar; respect writing length and give the FULL essay.
Kazakh/geography: preserve Kazakh and use only labels/locations actually present in the photo.
Multiple choice: selected option AND explanation, retaining question ids.
Return full solution as ordered text/math/code blocks. Math blocks contain bare LaTeX without
delimiters. Keep ONE short equation or one derivation step per block for a small watch screen;
split wide equations into equivalent consecutive steps. Put prose/units explanations in text.
Use standard fractions, powers, roots, integrals, sums and Greek commands; avoid align environments,
custom macros and external TeX files. Code blocks must preserve indentation and all requested code.
final_answer contains the important results FIRST. For essays/long written responses leave
final_answer empty and put the full response into solution; do not invent an essay 'final result'.
Do not drop details to meet a latency or card count target.
For practical numerical calculations supply numeric_checks (left/right numeric expressions with
+ - * / **, sqrt/sin/cos/tan/abs, pi; no variables). Include substitution checks for equations
and final physical calculations. absolute_tolerance should reflect justified rounding only.
confidence is your subjective estimate, not a calibrated probability. Never execute code.
"""

INDEPENDENT = """Independently re-read the ORIGINAL task images and solve the task from scratch.
You have not been given the first solver's answer. Recheck transcription against all images;
use the original image if they conflict. Check signs, exponents, quantities, units and options.
Check every subquestion and document continuation. Use an alternative derivation where practical.
""" + SOLVE

AUDIT = """Audit two independently produced solutions against ALL ORIGINAL task images.
The first answer is a candidate, NOT presumed correct. Compare the independent solution and
local numeric equality checks. Recheck reading, arithmetic, logic, units, options, language,
completeness of every question and consistency with diagrams/articles/maps.
Mark units_checked and answer_options_checked true after checking or determining not applicable.
If source transcription missed/misread data or any meaningful ambiguity persists, verdict=reread.
If necessary source data genuinely does not exist in these photos, verdict=unreadable.
If a solution needs correction, verdict=revise with specific issues and instructions.
Accept only if complete and correct, all audit flags true, and no unresolved issues.
Do not accept a candidate solely because the independent answer has the same final number.
"""

