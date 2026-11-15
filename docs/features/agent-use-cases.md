# Real-world agent use cases

This catalog describes jobs people commonly want a capable AI agent to help finish. It is organized around user outcomes, not a particular computer, model, or tool setup. Each example includes a request someone could actually send and what a useful result should contain.

These are examples, not guarantees that every agent can access every account, file, website, or application. An agent should say what access it needs, ask before consequential actions, and distinguish completed work from drafts, recommendations, and unverified assumptions.

For repeatable quality checks with explicit acceptance criteria and a failure/fix/rerun workflow, see the [Agent scenario regression pack](agent-scenario-regressions.md). The scenarios are not considered passed until run evidence is recorded.

## What users should expect

A useful request names the goal, relevant context, constraints, and preferred output. Users do not need to specify every implementation step. A capable agent should:

- Ask a focused question when a missing decision could materially change the result.
- Inspect the provided material or authorized sources before making claims.
- Produce the requested artifact or completed work when it has the necessary access, rather than only explaining how the user could do it.
- Preserve originals unless asked to change them; show proposed changes before consequential edits or external actions.
- Check the result against observable acceptance criteria and report what was and was not verified.
- Never claim to have sent, booked, purchased, published, changed, or tested something it did not actually do.

## Personal productivity

### Plan a realistic week

**Request:** “Plan next week around my work hours (9–5), two evening classes on Tuesday and Thursday, and my goal of exercising three times. Leave some unscheduled time and flag any conflicts.”

**Expected result:** A day-by-day schedule that respects fixed commitments, includes travel or transition time when known, leaves recovery/buffer time, and calls out assumptions. It should not silently add events to a calendar.

### Organize an overloaded task list

**Request:** “Group these tasks by project, identify deadlines and dependencies, and suggest a realistic order for the next five workdays. Mark anything that needs my decision.”

**Expected result:** A prioritized, dependency-aware list with due dates preserved, a short rationale for the ordering, and ambiguous or conflicting items clearly flagged.

### Prepare for a trip

**Request:** “Build a three-day itinerary for [city] for two adults and a child, arriving Friday afternoon. We like museums and easy walks, need a moderate budget, and want indoor alternatives in case of rain.”

**Expected result:** A paced itinerary grouped by day and location, estimated costs where supported, practical transport notes, accessibility or age caveats, and links or citations for current opening hours. Reservations remain suggestions unless explicitly authorized and available.

## Writing and communication

### Draft a sensitive email

**Request:** “Draft a calm, direct email to my landlord about the unresolved heating repair. Use the dates and details below, ask for a repair timeline, and avoid making legal claims.”

**Expected result:** A ready-to-review subject and message that accurately reflects the supplied facts, uses an appropriate tone, and does not invent events or send the message.

### Turn meeting notes into follow-ups

**Request:** “Convert these notes into a concise meeting summary. Separate decisions, open questions, and action items; include an owner and due date only when the notes provide one.”

**Expected result:** A readable summary with decisions and action items traceable to the notes. Missing owners or dates should be marked as unassigned, not guessed.

### Adapt content for different audiences

**Request:** “Rewrite this technical update for customers and for our internal engineering team. Keep the facts unchanged, explain jargon in the customer version, and list anything that needs confirmation.”

**Expected result:** Two audience-appropriate versions, consistent facts and dates, and a short list of unresolved details.

## Research and decisions

### Compare products or vendors

**Request:** “Compare these three project-management products for a 12-person nonprofit. Evaluate price, accessibility, data export, integrations, and support. Use current primary sources where possible and show unknowns.”

**Expected result:** A criteria-based comparison, dated source links, a transparent distinction between verified facts and vendor claims, relevant tradeoffs, and a recommendation conditional on the stated needs.

### Understand a policy or technical topic

**Request:** “Explain the current rules for [topic] in [jurisdiction]. Prioritize official sources, quote or link to the relevant passages, state when you checked them, and list what remains uncertain.”

**Expected result:** A plain-language explanation with dated, traceable sources and explicit uncertainty. It should not present general information as individualized legal, medical, or financial advice.

### Prepare a decision brief

**Request:** “Help us decide whether to renew this contract. Summarize the obligations, renewal date, price changes, cancellation terms, and unanswered questions from the attached documents. Do not infer terms that are not written.”

**Expected result:** A concise brief with document/page references, key dates, risks and unknowns, plus questions for the appropriate professional. It should not accept, renew, or cancel the contract.

## Documents and data

### Analyze a spreadsheet

**Request:** “Review the attached sales spreadsheet for monthly trends, unusual changes, missing values, and duplicate rows. Keep the source unchanged and create a separate cleaned copy plus a short summary of every transformation.”

**Expected result:** A summary with methods and caveats, a separate output file when file editing is available, and a change log that makes cleaning decisions auditable. Ambiguous values should be flagged rather than silently altered.

### Extract information from documents

**Request:** “Extract the supplier name, invoice number, invoice date, due date, currency, subtotal, tax, and total from these invoices into a spreadsheet. Include the source filename and mark unreadable or uncertain fields.”

**Expected result:** One row per invoice, consistent columns and formats, source-file traceability, and uncertainty markers. Totals should be checked when possible; the agent should not initiate payment.

### Reconcile two versions

**Request:** “Compare these two policy drafts. Show additions, removals, and meaning-changing edits, then produce a merged draft that preserves the newer effective dates. Do not overwrite either original.”

**Expected result:** A reviewable change summary and a separate merged draft, with conflicts and uncertain precedence called out.

## Software and technical work

### Implement a feature

**Request:** “In this project, add [feature]. Follow the existing patterns, keep the change focused, add tests for the expected behavior, run the relevant checks, and report files changed and any checks you could not run.”

**Expected result:** A working change in the intended project, focused tests or checks, a clear summary, and honest validation results. The agent should ask before broad rewrites or destructive migrations.

### Diagnose a bug

**Request:** “Investigate why [behavior] fails when [reproduction steps]. Find the root cause, make the smallest reliable fix, and add a regression test that fails before the fix.”

**Expected result:** A reproducible diagnosis, narrowly scoped correction, regression coverage, and test output. If the failure cannot be reproduced, the agent should report evidence and next diagnostic steps instead of guessing.

### Review code or a change

**Request:** “Review this change for correctness, regressions, and maintainability. Report only actionable findings, ordered by severity, with file and line references. If you find none, say so and note what you did not check.”

**Expected result:** Specific findings tied to code paths and impact, not stylistic preferences presented as defects. A review is not an implicit authorization to modify the code.

## Small-business and team operations

### Create a repeatable procedure

**Request:** “Turn these notes into an onboarding checklist for a new support hire. Separate required steps from optional tips, assign owners only where stated, and identify missing policy decisions.”

**Expected result:** A reusable, ordered checklist with prerequisites, roles, completion evidence, and unresolved decisions clearly separated.

### Draft customer-support replies

**Request:** “For each message in this export, classify the issue, urgency, and whether it needs a human. Draft a concise reply using our policy document. Do not promise refunds or exceptions that the policy does not allow.”

**Expected result:** A traceable row per message with classification, draft response, and escalation reason. Replies remain drafts unless a human approves sending.

### Summarize feedback

**Request:** “Analyze these customer comments. Group recurring themes, estimate how many comments support each theme, include representative quotes with source IDs, and separate observations from recommendations.”

**Expected result:** Theme counts with a clear denominator and method, representative traceable quotes, limitations or sampling bias, and recommendations labeled as such.

## Marketing and content

### Build a content calendar

**Request:** “Create a four-week content calendar for [audience] promoting [offer]. Use these approved claims and brand guidelines. Include channel, draft hook, purpose, and asset needed; flag any claim that lacks approval.”

**Expected result:** A practical schedule, channel-appropriate concepts, content drafts or outlines, and a visible distinction between approved claims and items needing review. Nothing is published automatically.

### Repurpose a source

**Request:** “Turn this approved webinar transcript into a blog outline, a newsletter draft, and five short social posts. Preserve the speaker’s meaning, do not add unsupported statistics, and give each format a distinct call to action.”

**Expected result:** Separate, audience-appropriate drafts, claims traceable to the transcript, and any missing attribution or approval noted.

## Education and training

### Learn a skill

**Request:** “Teach me the basics of [skill] over two weeks. I have 30 minutes a day and already know [background]. Give me short lessons, practice tasks, and a way to check progress.”

**Expected result:** A paced learning plan matched to the learner's background, concrete exercises, answer checks or rubrics, and adjustment points—not a promise of mastery.

### Prepare a lesson

**Request:** “Create a 45-minute lesson on [topic] for [age/experience] learners. Include learning objectives, an activity, materials, checks for understanding, and an accessible alternative for the activity.”

**Expected result:** A timed lesson plan aligned with stated objectives, clear materials and instructions, formative checks, and accessibility considerations.

## Hiring and people operations

### Structure an interview

**Request:** “Create a structured interview guide for this role description. Map each question to a job-related competency, provide consistent follow-up prompts, and use a scorecard with behavioral anchors.”

**Expected result:** A consistent, job-relevant question set and scorecard. It should avoid protected or irrelevant personal questions and leave hiring decisions to people.

### Improve a job description

**Request:** “Rewrite this job description for clarity and accessibility. Preserve the actual responsibilities and requirements, distinguish required from preferred qualifications, and flag criteria that seem unrelated to the work.”

**Expected result:** A clearer draft with no invented benefits or requirements, plus a review list of ambiguous or potentially exclusionary criteria.

## Finance and administration

### Create a household budget

**Request:** “Using this monthly income and expense list, make a budget with fixed, variable, and irregular costs. Identify arithmetic issues and show a conservative option. Do not move money or assume a debt strategy.”

**Expected result:** A transparent calculation, categorized totals, assumptions, and scenarios. It should not execute transactions or represent the result as professional financial advice.

### Organize expense records

**Request:** “Categorize these receipts against the attached expense policy. Include amount, date, vendor, suggested category, source file, and a reason for anything that needs human review.”

**Expected result:** A traceable table with uncertain or policy-sensitive items flagged. Categorization should not be mistaken for reimbursement approval or tax advice.

## Creative and presentation work

### Develop a creative brief

**Request:** “Create a creative brief for a [campaign/product]. The audience is [audience], the goal is [goal], and the tone is [tone]. Include message hierarchy, deliverables, constraints, and questions for stakeholders.”

**Expected result:** A usable brief with audience, objective, message, tone, deliverables, constraints, and unresolved decisions clearly organized.

### Build a presentation

**Request:** “Turn this report into a 10-slide presentation for [audience]. Give each slide one takeaway, retain the source for every statistic, and add speaker notes for context. Do not invent data.”

**Expected result:** A coherent slide sequence with concise content, source traceability, speaker notes, and explicit gaps where the report lacks evidence.

## Higher-impact actions

Some tasks affect money, health, legal rights, employment, access, public reputation, or other people. For these, a good agent can organize information, draft options, and identify questions, but should use a higher standard of evidence and keep a human in control of final decisions. Examples include:

- Preparing questions for a clinician from a symptom diary, without diagnosing or changing treatment.
- Summarizing a legal notice and extracting deadlines, without deciding a legal strategy or contacting the other party.
- Comparing loan or insurance terms, without choosing or purchasing a product on the user's behalf.
- Drafting an employee performance summary from documented evidence, without making an employment decision.
- Preparing a payment, order, booking, publication, or account change for review, without executing it until the user explicitly confirms the exact action.

## A reusable request pattern

> **Goal:** What outcome do I need?  
> **Context:** What should the agent know or inspect?  
> **Constraints:** What must it preserve, avoid, or prioritize?  
> **Output:** What format or files do I want?  
> **Acceptance:** What would make the result correct or complete?  
> **Authority:** Should it only draft, make a proposed change, or take an explicitly approved action?

For example:

> “Compare the attached vendor proposals for our 20-person team. Focus on total first-year cost, data export, and support response time. Create a one-page comparison table with page references, flag missing information, and recommend a follow-up question for each vendor. Do not contact vendors or choose one for us.”

## Maintaining this catalog

Keep examples centered on real user outcomes and observable expectations. When product capabilities change, update any claim about what the agent can actually access or do; do not turn an illustrative request into an unsupported capability promise.
