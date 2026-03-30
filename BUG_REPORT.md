# PGAI Voice Agent -- Bug Report

**Date:** 2026-03-29
**Method:** 17 test calls (16-scenario batch + targeted retries) via Nova Sonic voice bot, analyzed by Gemini 3.1 Flash Lite
**System under test:** Pivot Point Orthopedics AI receptionist (PGAI)

---

## Summary

Across 17 test calls covering scheduling, rescheduling, cancellation, refills, information queries, and edge cases, we found 16 distinct agent behavior bugs. The 3 most actionable findings are the missing triage logic for urgent symptoms (#2, #5), the booking error handling (#1), and the inconsistent knowledge access (#7). Bugs are split into two sections: agent reasoning bugs that would occur in production, and behaviors influenced by the demo test environment.

---

## Agent Reasoning Bugs

These bugs reflect issues in how the agent reasons, responds, and handles conversation flow -- independent of the demo environment.

### Critical

#### 1. Agent handles booking failures with vague errors and no workaround

**Severity:** Critical
**Affected calls:** All scheduling attempts (9+ calls)
**Details:** When the booking API rejects the visit reason, the agent gives the patient a vague "system issue with the visit reason" message, retries with the exact same input, fails again, and escalates. It never attempts to rephrase the visit reason, offer the patient a different format, or suggest an alternative path (e.g., "let me take your details and have someone call you back with a confirmed time"). The error handling is identical across every call regardless of whether the reason was "knee pain from running" or "general checkup."

> "i'm having trouble booking your appointment due to a system issue with the visit reason. let me try again."
> -- edge-visit-reason-simple-20260329-133413

> "i'm having trouble booking your appointment because the system isn't accepting general checkup as a reason."
> -- edge-visit-reason-simple-20260329-133413

#### 2. No urgent care escalation for acute injuries

**Severity:** Critical
**Affected call:** edge-urgent-20260329-131804
**Details:** A patient called saying they twisted their ankle an hour ago, it's swelling fast, and they're in a lot of pain. The agent's first response was "i can help you schedule an appointment" followed by the standard name/DOB collection flow. It did not proactively suggest urgent care or the emergency room until the patient explicitly asked "should I go to the ER?" A patient describing acute swelling and severe pain should receive immediate triage guidance before being routed into a scheduling workflow.

> "i can help you schedule an appointment. to proceed, may i have your first name?"
> -- edge-urgent-20260329-131804 (patient had just described acute ankle injury with swelling)

### High

#### 3. Agent asks "what other phone number do we have on file" to new patients

**Severity:** High
**Affected calls:** scheduling-shoulder-20260329-124429, cancel-20260329-125437, office-hours-20260329-130225, insurance-20260329-130656, edge-wrong-specialty-20260329-132130
**Details:** The agent asks "what other phone number do we have on file for you?" to patients it has never seen before and whose records it cannot find. This question presupposes the patient is an existing patient with multiple phone numbers on file. For new callers, it's confusing and logically inconsistent.

> "what other phone number do we have on file for you?"
> -- insurance-20260329-130656 (new patient Lisa Park, no records in system)

#### 4. Agent offers to document a callback request, then immediately says it cannot document

**Severity:** High
**Affected call:** edge-urgent-20260329-131804
**Details:** The agent says "would you like me to document your request for the clinic to call you back as soon as possible?" The patient says yes. The agent then says "since i can't document your request while live support is open, and transfer isn't available in this demo, i recommend you seek urgent care." The agent offered an action then immediately claimed it couldn't perform it -- a self-contradiction in the same conversational turn, made worse by the fact that the patient has an acute injury.

> "would you like me to document your request for the clinic to call you back as soon as possible?"
> Patient: "Yeah, go ahead and document that. I need to be seen today because it's really bad."
> "since i can't document your request while live support is open, and transfer isn't available in this demo, i recommend you seek urgent care or the emergency room if your pain or swelling gets worse."
> -- edge-urgent-20260329-131804

#### 5. Agent ignores worsening symptoms during a routine refill request

**Severity:** High
**Affected call:** medication-refill-20260329-125751
**Details:** The patient says "the pain has been getting worse, that's why I'm using more of it." The agent asked about worsening symptoms but did nothing with the answer -- it immediately pivoted to processing the refill. It did not flag that worsening pain despite ongoing medication may warrant a clinical review or new appointment. A medical office receptionist should note "your pain is worsening -- the doctor may want to see you before we refill."

> Agent: "can you confirm if you've had any worsening symptoms since starting or while taking your ibuprofen?"
> Patient: "the pain has been getting worse, that's why I'm using more of it"
> Agent: "there was an issue sending your refill request. let me try again..."
> -- medication-refill-20260329-125751

### Medium

#### 6. Agent doesn't know its own cancellation policy

**Severity:** Medium
**Affected call:** cancel-20260329-125437
**Details:** When directly asked about the cancellation policy, the agent says "i don't have access to the specific cancellation policy details for pivot point orthopedics." A medical office receptionist -- human or AI -- should know the clinic's own policies. In the reschedule call, the agent correctly stated there's no cancellation fee, showing inconsistent knowledge across calls.

> "i don't have access to the specific cancellation policy details for pivot point orthopedics."
> -- cancel-20260329-125437

Compare with: "pivot point orthopedics does not charge a fee for rescheduling or canceling appointments."
> -- reschedule-20260329-125154

#### 7. Agent says it can't answer cost questions, then answers them

**Severity:** Medium
**Affected call:** edge-multiple-20260329-133036
**Details:** The agent first says "i am unable to answer questions related to referrals, appointment requirements, or costs" and forces the patient through the verification loop. Later in the same call, after the demo transfer fails, it provides a detailed answer about how one consultation can cover multiple concerns and how insurance billing works. The initial refusal was unnecessary and frustrated the patient.

> "i am unable to answer questions related to referrals, appointment requirements, or costs."
> (later in the same call)
> "for most orthopedic clinics, one consultation can often cover multiple concerns like knee and shoulder pain, but it depends on the provider's policy and your insurer."
> -- edge-multiple-20260329-133036

#### 8. Misheard phone number read back

**Severity:** Medium
**Affected call:** insurance-20260329-130656
**Details:** The patient provided phone number 313-555-0419. The agent read back "three one three five one three seven three one six" -- which is the Twilio caller ID number, not the patient's stated number. The agent confused the telephony metadata with the patient's verbal input.

> Patient: "It's just the one, 3135550419."
> Agent: "you're calling from three one three five one three seven three one six. is that the best number for follow up?"
> Patient: "No, that's not my number."
> -- insurance-20260329-130656

#### 9. Agent confirms a promise it has no mechanism to keep

**Severity:** Medium
**Affected call:** edge-weekend-20260329-131416
**Details:** Patient asks to be called if a weekend slot opens. The agent says "i'll... note your request to be contacted if a weekend slot opens." Then immediately fails to even complete the basic booking ("i'm having trouble booking your appointment due to a system issue"). The agent confirmed it would monitor for weekend cancellations and call the patient -- a promise it cannot keep, especially when it can't even process a standard booking.

> "i'll book you for monday at 9.45 a.m. with dr. bricker and note your request to be contacted if a weekend slot opens."
> (moments later)
> "i'm having trouble booking your appointment due to a system issue with the visit reason."
> -- edge-weekend-20260329-131416

#### 10. Agent collects full identity verification before redirecting a wrong-specialty caller

**Severity:** Medium
**Affected call:** edge-wrong-specialty-20260329-132130
**Details:** Lisa Park calls with a skin rash. Instead of recognizing "skin rash" as outside orthopedic scope immediately, the agent puts her through a full identity verification (name, DOB, spelling, phone number, record lookup) before finally saying "for a skin rash, it's best to contact a primary care doctor or a dermatologist." The specialty redirect should happen at first mention of the non-orthopedic complaint, not after a failed identity lookup.

> Patient: "I've got this skin rash on my arm that's been getting worse"
> Agent: "i'll help you get scheduled. may i get your date of birth to look up your record?"
> (full name, DOB, spelling, phone number collection follows)
> Agent: "for a skin rash, it's best to contact a primary care doctor or a dermatologist."
> -- edge-wrong-specialty-20260329-132130

### Low

#### 11. Agent offers "new patient consultation" slots to returning patients

**Severity:** Low
**Affected calls:** followup-surgery-20260329-124743, scheduling calls
**Details:** When a patient states they are returning (had surgery six weeks ago, need a follow-up), the agent sometimes offers "new patient consultation" as one of the appointment type options. While it did correctly identify the follow-up type in some cases, the inconsistency suggests the appointment type classification doesn't always factor in stated patient history. A patient who just said "I had surgery six weeks ago" should not be prompted with "new patient consultation" as an option.

#### 12. 9 AM described as "early morning" when patient needs pre-8 AM

**Severity:** Low
**Affected call:** edge-weekend-20260329-131416
**Details:** The patient explicitly asked for appointments before 8 AM because they work a 9-to-5 job. The agent said it would check "earliest available" slots but returned 9:45 AM as the earliest option, with no acknowledgment that this doesn't meet the patient's stated constraint. The framing of 9:45 AM as "early morning" is misleading for a patient who said they need to be seen before work.

> Patient: "Maybe an early slot before 8am on a weekday?"
> Agent: "the earliest new patient consultation i found is monday at 9.45 a.m."
> -- edge-weekend-20260329-131416

---

## Demo-Influenced Behaviors

These bugs are real conversational failures, but they are triggered or amplified by the demo test environment (single caller ID, demo mode flags, missing live transfer). They are documented for completeness but are less likely to appear in production.

#### 13. Agent breaks character by revealing demo mode during identity verification

**Severity:** Critical
**Affected calls:** scheduling-knee-20260329-124127, followup-surgery-20260329-124743, medication-refill-20260329-125751, reschedule-20260329-125154, edge-visit-reason-simple-20260329-133413, edge-weekend-20260329-131416
**Details:** When a patient's date of birth doesn't match records, the agent explicitly tells the caller it's accepting the mismatch "for demo purposes." A production-quality agent should never expose internal system state to a caller. It should either reject the mismatch and offer alternative verification, or silently proceed. Saying "for demo purposes" would confuse a real patient and constitutes a HIPAA-adjacent identity verification failure.

> "the birthday doesn't match our records, but for demo purposes, i'll accept it."

#### 14. Agent greets every caller as "Sarah" and recovers poorly when corrected

**Severity:** High
**Affected calls:** scheduling-shoulder-20260329-124429, cancel-20260329-125437, location-20260329-130857, edge-urgent-20260329-131804, edge-wrong-specialty-20260329-132130, edge-multiple-20260329-133036
**Details:** The agent greets every caller with "am i speaking with sarah?" -- likely based on a caller-ID lookup associating our test number with a single patient record. The real bug is what happens next: when the caller corrects the agent ("No, this is Michael Torres"), the agent doesn't smoothly pivot. Instead, it launches into a rigid re-verification loop (name, DOB, spelling, phone number) that ignores information the caller already provided. The greeting mismatch is a minor annoyance, but the poor recovery turns it into a frustrating multi-minute detour.

> "am i speaking with sarah?"
> "Yeah, this is Michael Torres. I twisted my ankle pretty badly..."
> (agent then asks for name, DOB, spelling, phone number -- ignoring what was just said)
> -- edge-urgent-20260329-131804

#### 15. Redundant verification loop for non-Sarah callers

**Severity:** High
**Affected calls:** cancel-20260329-125437, edge-frustrated-20260329-133649, edge-urgent-20260329-131804, edge-wrong-specialty-20260329-132130, office-hours-20260329-130225, insurance-20260329-130656, scheduling-shoulder-20260329-124429
**Details:** For callers who aren't "Sarah Johnson," the agent enters a rigid data-collection loop: asks for name, DOB, confirms DOB, asks to spell name, asks for phone number -- then sometimes restarts the entire sequence. Patients who gave all their information upfront are forced to repeat it. In several calls, patients expressed visible frustration. The agent does not incorporate information already provided in the conversation.

> "It's Michael Torres, June 22 1978. I told you that already."
> -- cancel-20260329-125437

> "I already gave you my name -- it's Lisa Park. L-I-S-A P-A-R-K. Can we skip the repeats and just schedule the appointment?"
> -- edge-frustrated-20260329-133649

#### 16. Agent offers live transfer then immediately retracts it

**Severity:** Medium
**Affected calls:** edge-urgent-20260329-131804, edge-wrong-specialty-20260329-132130, office-hours-20260329-130225, edge-frustrated-20260329-133649, edge-multiple-20260329-133036
**Details:** The agent says it will connect the patient to the support team, then immediately says transfer isn't available. The agent should check whether transfer is available before offering it. Offering and retracting in the same breath erodes trust.

> "i can connect you to our patient support team... live transfer isn't available right now since this is a demo clinic."
> -- office-hours-20260329-130225

---

## Notes

- 17 transcripts total: 15 from the batch run (edge-frustrated failed mid-batch due to a connection drop) plus a successful retry of edge-frustrated and one earlier exploratory call (scheduling-knee) that was shorter than ideal but still captured a real bug.
- The "Jessica from patient support" hallucination observed in one early test call was a Nova Sonic (test harness) artifact, not a PGAI agent bug. It is excluded from this report.
- Infrastructure limitations (dead-end test line transfer, missing patient records for non-Sarah personas) are noted as context but not classified as agent bugs. The agent behavior bugs above are about what the agent *said or reasoned* in conversation.
- The visit reason booking failure may be a backend API issue rather than an agent logic bug. However, the agent's *handling* of the failure (vague error messages, identical retry with no change, no workaround offered) is the agent bug being reported.
