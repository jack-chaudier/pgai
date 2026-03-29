# PGAI Voice Agent -- Bug Report

**Date:** 2026-03-29
**Method:** 16 automated test calls via Nova Sonic, analyzed by Gemini 3.1 Flash Lite
**System under test:** Pivot Point Orthopedics AI receptionist (PGAI demo)

---

## Summary

Across 16 test scenarios, the agent failed to complete its primary task (booking, cancellation, refill, etc.) in nearly every call. Three systemic issues dominate: the visit-reason validation bug blocks all bookings, the transfer endpoint is a dead-end test line, and the agent repeatedly asks patients for information they already provided. Below are 11 distinct bugs, deduplicated and ordered by severity.

---

## Critical

### 1. Visit reason validation rejects all booking attempts

**Severity:** Critical
**Affected calls:** call-20260329-114915, call-20260329-120058, call-20260329-120812, call-20260329-121553, edge-vague-20260329-132543, edge-visit-reason-simple-20260329-133413, edge-weekend-20260329-131416, followup-surgery-20260329-124743, reschedule-20260329-125154
**Details:** The booking API rejects the visit reason on every single appointment attempt across all scenarios. The agent collects all required information, the patient confirms, and the booking call fails with a vague "system issue with the visit reason." This happens regardless of whether the reason is specific ("knee pain from running injury") or generic ("general checkup"). The agent retries once or twice, fails again, and escalates. This is the single most impactful bug -- the agent cannot perform its primary function.

> "it looks like there was an issue booking the appointment due to a problem with the visit reason."
> -- call-20260329-114915

> "i'm having trouble booking your appointment because the system isn't accepting general checkup as a reason."
> -- edge-visit-reason-simple-20260329-133413

### 2. Transfer routes to dead-end test line that hangs up on patients

**Severity:** Critical
**Affected calls:** call-20260329-114915, call-20260329-120058, call-20260329-121553, edge-vague-20260329-132543, edge-visit-reason-simple-20260329-133413, followup-surgery-20260329-124743, medication-refill-20260329-125751, reschedule-20260329-125154
**Details:** When the agent cannot complete a task, it promises to connect the patient to a live representative. The transfer target is a recorded message that says "hello, you've reached the pretty good ai test line. goodbye." and disconnects. The patient is left with no appointment, no callback, and no recourse. This turns every booking failure into a total dead end.

> "connecting you to a representative. please wait. hello, you've reached the pretty good ai test line. goodbye."
> -- followup-surgery-20260329-124743

### 3. Refill request creation fails with no fallback

**Severity:** Critical
**Affected call:** medication-refill-20260329-125751
**Details:** The agent collects medication name, dosage, frequency, pharmacy, and remaining supply, then fails to submit the refill request due to a "technical issue." It retries once, fails again, and transfers to the dead-end test line. A patient running out of prescribed medication is left without resolution.

> "there was a technical issue creating your refill request. let me try one more time to make sure your request is sent to the clinic."
> -- medication-refill-20260329-125751

---

## High

### 4. Agent bypasses identity verification "for demo purposes"

**Severity:** High
**Affected calls:** call-20260329-114915, call-20260329-120812, call-20260329-121553, scheduling-knee-20260329-124127, followup-surgery-20260329-124743, medication-refill-20260329-125751, reschedule-20260329-125154, edge-visit-reason-simple-20260329-133413
**Details:** When the patient's date of birth does not match records, the agent says the birthday is wrong and then accepts it anyway "for demo purposes." This exposes internal system state to the caller, breaks immersion, and in a production setting would constitute a security and HIPAA compliance failure. The agent should either reject the mismatch and offer alternatives (e.g., verify by phone number) or silently proceed without revealing that records do not match.

> "the birthday doesn't match our records, but for demo purposes, i'll accept it."
> -- call-20260329-114915

### 5. Agent cannot find patient records, blocks all downstream tasks

**Severity:** High
**Affected calls:** cancel-20260329-125437, edge-frustrated-20260329-133649, edge-urgent-20260329-131804, edge-wrong-specialty-20260329-132130, office-hours-20260329-130225, scheduling-shoulder-20260329-123604, scheduling-shoulder-20260329-124429, insurance-20260329-130656
**Details:** For the "Lisa Park" and "Michael Torres" test personas, the agent consistently fails to locate their records after collecting name, DOB, and phone number. Once the lookup fails, the agent cannot book, cancel, or perform any record-dependent action. The agent then attempts a live transfer (which hits the dead-end test line) or tells the patient a callback will happen. In the cancellation scenario, the patient is told the agent cannot proceed at all.

> "i can't complete the cancellation right now because i'm unable to find your record in the system."
> -- cancel-20260329-125437

### 6. Agent offers live transfer then immediately retracts it

**Severity:** High
**Affected calls:** edge-urgent-20260329-131804, edge-wrong-specialty-20260329-132130, office-hours-20260329-130225, edge-frustrated-20260329-133649, edge-multiple-20260329-133036, insurance-20260329-130656
**Details:** The agent says it will connect the patient to the support team, then immediately says "live transfer isn't available right now since this is a demo clinic." This whiplash -- offering help and then revoking it in the same breath -- is confusing and erodes trust. The agent should check whether transfer is available before offering it.

> "i can connect you to our patient support team... live transfer isn't available right now since this is a demo clinic."
> -- office-hours-20260329-130225

---

## Medium

### 7. Agent repeatedly asks for information already provided

**Severity:** Medium
**Affected calls:** cancel-20260329-125437, edge-frustrated-20260329-133649, edge-urgent-20260329-131804, edge-wrong-specialty-20260329-132130, edge-multiple-20260329-133036, office-hours-20260329-130225, scheduling-shoulder-20260329-123604, insurance-20260329-130656, medication-refill-20260329-125751
**Details:** Patients frequently give their name, DOB, and reason for calling in their opening statement. The agent ignores this and asks for each piece individually, sometimes multiple times. In several calls, patients express visible frustration. This appears to be a rigid data-collection flow that does not incorporate information already extracted from earlier utterances.

> "It's Michael Torres, June 22 1978. I told you that already."
> -- cancel-20260329-125437

> "I already gave you my name -- it's Lisa Park. L-I-S-A P-A-R-K. Can we skip the repeats and just schedule the appointment?"
> -- edge-frustrated-20260329-133649

### 8. Agent misidentifies caller or assumes wrong name

**Severity:** Medium
**Affected calls:** edge-urgent-20260329-131804, edge-wrong-specialty-20260329-132130, location-20260329-130857, scheduling-shoulder-20260329-123604
**Details:** The agent greets every caller as "Sarah" regardless of who is actually calling. When the caller is Michael Torres or Lisa Park, the agent still opens with "am i speaking with sarah?" This suggests the greeting is hardcoded or the agent defaults to a single patient profile.

> "am i speaking with sarah?"
> "Yeah, this is Michael Torres. I twisted my ankle pretty badly about an hour ago..."
> -- edge-urgent-20260329-131804

### 9. Incomplete or truncated speech output

**Severity:** Medium
**Affected calls:** edge-wrong-specialty-20260329-132130, edge-multiple-20260329-133036, call-20260329-120812, edge-weekend-20260329-131416, reschedule-20260329-125154
**Details:** The agent occasionally produces partial utterances that trail off or get cut mid-word, forcing the patient to ask for clarification. Examples include "life tra" (attempted "live transfer"), "could you" (incomplete sentence), "i'm having trouble." (no further explanation), and "there are no new..." (cut off). This may be a TTS streaming issue or the agent generating incomplete responses.

> "life tra"
> "Sorry, I didn't catch that -- could you repeat it?"
> -- edge-wrong-specialty-20260329-132130

> "could you"
> "Sorry, could you what?"
> -- edge-multiple-20260329-133036

### 10. Agent lacks basic clinic knowledge (hours, policies, parking)

**Severity:** Medium
**Affected calls:** cancel-20260329-125437, location-20260329-130857, office-hours-20260329-130225, insurance-20260329-130656
**Details:** The agent cannot answer routine questions a receptionist should know: cancellation policy, floor number, accessible parking details, self-pay pricing. It defaults to "I don't have that information" and promises a callback. A medical office receptionist -- human or AI -- should have this information in its knowledge base.

> "i don't have access to the specific cancellation policy details for pivot point orthopedics."
> -- cancel-20260329-125437

> "i don't have information about the floor number or specific accessible parking spots."
> -- location-20260329-130857

---

## Low

### 11. Offered appointment type mismatches patient status

**Severity:** Low
**Affected call:** call-20260329-121553
**Details:** A returning patient calling for a follow-up is offered "new patient consultation" slots. The agent does not differentiate between new and returning patients when selecting appointment types, which could result in incorrect visit duration, billing codes, or provider assignment.

> "dr. bricker has openings for a new patient consultation on monday, march 30th at 9.45 a.m. and 10.30 a.m."
> -- call-20260329-121553

---

## Notes

- **Excluded: "Jessica from patient support" hallucination.** In scheduling-shoulder-20260329-123604, Nova Sonic (the simulated patient) began role-playing as a support agent named Jessica. This is a test harness artifact, not a PGAI agent bug.

- **Root cause overlap.** Bugs 1, 2, and 6 are likely caused by the same underlying issue: the demo environment lacks a functional booking backend and transfer endpoint. Fixing the API integration for visit-reason validation and pointing the transfer SIP URI to a real destination (or a proper hold queue) would resolve the majority of critical failures.

- **Bugs 4 and 7 are prompt/logic issues.** The "for demo purposes" leak (Bug 4) and the redundant data collection (Bug 7) are solvable through prompt engineering -- removing the demo-mode bypass language and adding instructions to extract patient details from the conversation history before asking again.
