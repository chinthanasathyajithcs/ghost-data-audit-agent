# Intent labels

`intent_labels.csv` holds our hand label for **every distinct request text** in the samples, the
evaluation set and the custom cases: 402 texts (after collapsing whitespace). It is used only by
`python code/evaluation/main.py --suite intent` to score the Stage 2 classifier; the agent never
reads it (enforced by `code/tests/test_no_leak.py`).

## How the labels were made

All 518 evaluation requests are built from 67 distinct sentences (Stage 2 doc §4.1). We read every
sentence and labelled each text with the rule in `code/deletion_audit/prompts/intent.md`:
`authorizes_deletion` is true only for requests to delete the account or its personal data, and an
explicit refusal always wins.

| Group | Texts | Label |
|---|---|---|
| English deletion requests (12 openings × scope × closing sentences) | 383 | `DELETION` |
| Portuguese, Spanish, French, Japanese, Korean deletion requests (eval set) and the Korean custom_05 | 6 | `DELETION` |
| Non-deletion requests | 13 | below |

## The 13 non-deletion texts

| Source | Text (opening) | Label | Why it is not deletion |
|---|---|---|---|
| eval case_533 | "The mobile number on my profile is out of date…" | `CORRECTION` | Asks to replace the number and keep the account active |
| eval case_534 | "Please stop the promotional emails…" | `MARKETING_OPT_OUT` | Says "I am not asking for deletion" |
| eval case_535 | "I'd like to download my account information in a portable format…" | `EXPORT` | Asks to keep the account as it is |
| eval case_536 | "I can't access my profile and need help resetting the login…" | `ACCOUNT_SUPPORT` | Says "Do not close the account" |
| eval case_537 | "My surname is misspelled on the account…" | `CORRECTION` | Asks to correct it "without removing any of my records" |
| eval case_538 | "Please remove me from marketing lists only…" | `MARKETING_OPT_OUT` | "Only" narrows it to marketing; still wants service messages |
| eval case_539 | "Can you tell me what personal information you hold about me?…" | `ACCESS` | "This is an information request, not a request to erase it" |
| eval case_540 | "I need a copy of last year's invoices for my records…" | `OTHER` | Documents; asks to leave the profile in place |
| eval case_541 | "Please change the email address used for this account…" | `CORRECTION` | Wants to keep using the service |
| eval case_542 | "Could you send me a copy of the information held on my account?…" | `ACCESS` | "Please don't delete or change anything" |
| custom_01 | "Could you send me a copy of all the personal data you hold about me?…" | `ACCESS` | Keeps the account open |
| custom_02 | "プロモーションメールの配信を停止してください…" (stop promotional emails) | `MARKETING_OPT_OUT` | Will keep using the account |
| custom_03 | "Gostaria de corrigir o endereço de e-mail…" (correct my email) | `CORRECTION` | Wants to keep using the service |

The suite reports two numbers: **authorises deletion** (the decision that changes the output) and
**intent label** (the finer label, useful for explaining mistakes but not used by the agent).
