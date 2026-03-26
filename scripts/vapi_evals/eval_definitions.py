"""
VAPI Eval Definitions for Jill Assistants

This module defines test scenarios for:
1. Greeter Assistant - Skill routing with phonetic variants
2. Timesheet Assistant - Site name recognition and logging flow

Each eval tests specific phonetic misunderstandings discovered from call log analysis.
"""

# =====================================================
# GREETER ASSISTANT EVALS
# Tests the skill routing with phonetic variants
# =====================================================

GREETER_JUDGE_NOTE = """IMPORTANT CONTEXT: The greeter assistant authenticates callers first (via a tool call to authenticate_caller), then routes to the correct skill. If the assistant makes a tool call, that counts as proceeding — it does NOT count as asking for clarification or being confused. Tool calls are normal assistant behavior."""

GREETER_EVALS = [
    {
        "name": "greeter_timesheet_routing_clean",
        "description": "User clearly says 'timesheet' - should route to timesheet flow",
        "messages": [
            {"role": "user", "content": "timesheet"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": f"""{GREETER_JUDGE_NOTE}

PASS criteria (ANY counts as pass):
- The assistant makes a tool call (e.g. authenticate_caller) — this means it is proceeding with the flow
- The assistant acknowledges the timesheet intent and proceeds
- The assistant asks about site or date (timesheet flow)

FAIL criteria (ALL must be true to fail):
- The assistant explicitly says it doesn't understand
- The assistant asks "what would you like to do?" without acknowledging timesheet
- The assistant offers unrelated options

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "greeter_timesheet_phonetic_parm_shake",
        "description": "User says 'parm shake' (common misheard) - should recognize as timesheet",
        "messages": [
            {"role": "user", "content": "parm shake"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": f"""{GREETER_JUDGE_NOTE}

The user said "parm shake" which is a common STT misheard variant of "timesheet".

PASS criteria (ANY counts as pass):
- The assistant makes a tool call — this means it is proceeding
- The assistant interprets this as a timesheet request and proceeds

FAIL criteria (ALL must be true to fail):
- The assistant explicitly says it doesn't understand "parm shake"
- The assistant asks the user to repeat or rephrase

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "greeter_timesheet_phonetic_tom_sheets",
        "description": "User says 'tom sheets' (common misheard) - should recognize as timesheet",
        "messages": [
            {"role": "user", "content": "tom sheets"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": f"""{GREETER_JUDGE_NOTE}

The user said "tom sheets" which is a common STT misheard variant of "timesheet".

PASS criteria (ANY counts as pass):
- The assistant makes a tool call — proceeding with flow
- The assistant interprets as timesheet and proceeds

FAIL criteria:
- The assistant explicitly doesn't understand or asks to repeat

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "greeter_voice_note_phonetic_boys_note",
        "description": "User says 'boys note' (misheard) - should recognize as voice note",
        "messages": [
            {"role": "user", "content": "boys note"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": f"""{GREETER_JUDGE_NOTE}

The user said "boys note" which is a common STT misheard variant of "voice note".

PASS criteria (ANY counts as pass):
- The assistant makes a tool call — proceeding with flow
- The assistant interprets as voice note and proceeds

FAIL criteria:
- The assistant explicitly doesn't understand or asks to repeat

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "greeter_site_update_phonetic_sight_update",
        "description": "User says 'sight update' (misheard) - should recognize as site update",
        "messages": [
            {"role": "user", "content": "sight update"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": f"""{GREETER_JUDGE_NOTE}

The user said "sight update" which is a common STT misheard variant of "site update".

PASS criteria (ANY counts as pass):
- The assistant makes a tool call — proceeding with flow
- The assistant interprets as site update and proceeds

FAIL criteria:
- The assistant explicitly doesn't understand or asks to repeat

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    }
]

# =====================================================
# TIMESHEET ASSISTANT EVALS
# Tests site name recognition and timesheet logging flow
# =====================================================

TIMESHEET_EVALS = [
    {
        "name": "timesheet_site_bishops_avenue_clean",
        "description": "User clearly says 'Bishops Avenue' - should identify site correctly",
        "messages": [
            {"role": "user", "content": "Bishops Avenue"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user is logging a timesheet and said the site name "Bishops Avenue".

PASS criteria:
- The assistant acknowledges Bishops Avenue as the site
- The assistant proceeds to ask about time (start time, hours, etc.)
- The assistant does NOT ask for site clarification

FAIL criteria:
- The assistant says it doesn't recognize the site
- The assistant asks "which site?" again
- The assistant seems confused about the site name

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_site_bishops_phonetic_fishets",
        "description": "User says 'Fishets Avenue' (common misheard) - should recognize as Bishops Avenue",
        "messages": [
            {"role": "user", "content": "Fishets Avenue"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said "Fishets Avenue" which is commonly misheard by STT when users say "Bishops Avenue".

PASS criteria (ANY counts as pass):
- The assistant maps this to Bishops Avenue and proceeds (asks about time/date)
- The assistant says "looks like you meant Bishops Avenue" and then proceeds — this counts as PASS because it correctly identified the site and moved forward
- The assistant makes a tool call to identify the site — this is proceeding

FAIL criteria (ALL must be true to fail):
- The assistant says it doesn't recognize ANY site from the input
- The assistant asks the user to spell the site or repeat it
- The assistant lists all available sites and asks the user to pick one

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_site_cranbrook_phonetic_grand_brook",
        "description": "User says 'Grand Brook' (misheard) - should recognize as Cranbrook Road",
        "messages": [
            {"role": "user", "content": "Grand Brook"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said "Grand Brook" which is commonly misheard when users say "Cranbrook Road".

PASS criteria (ANY counts as pass):
- The assistant maps this to Cranbrook Road and proceeds
- The assistant says "looks like you meant Cranbrook" and continues — this counts as PASS
- The assistant makes a tool call to identify the site

FAIL criteria (ALL must be true to fail):
- The assistant doesn't recognise ANY site from the input
- The assistant asks the user to repeat or spell the site name

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_site_leichhardt_phonetic_lie_cart",
        "description": "User says 'Lie Cart' (misheard) - should recognize as MK's Leichhardt",
        "messages": [
            {"role": "user", "content": "Lie Cart"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said "Lie Cart" which is commonly misheard when users say "MK's Leichhardt".

PASS criteria:
- The assistant interprets this as MK's Leichhardt (or just Leichhardt)
- The assistant proceeds with the timesheet

FAIL criteria:
- The assistant doesn't recognize the site
- The assistant asks for clarification

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_overhead_work_admin",
        "description": "User says 'admin work' - should route to overheads site",
        "messages": [
            {"role": "user", "content": "admin work"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said they did "admin work" which should be logged as overhead/office work (not a construction site).

PASS criteria (ANY counts as pass):
- The assistant recognizes this as admin/overhead work and proceeds
- The assistant makes a tool call with "overheads" as the site — this is correct behaviour, the tool resolves the overhead site automatically
- The assistant says it will log under overheads and asks about times

FAIL criteria (ALL must be true to fail):
- The assistant asks which CONSTRUCTION SITE they worked at (ignoring the admin context)
- The assistant says it doesn't understand "admin work"

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_overhead_work_paperwork",
        "description": "User says 'paperwork' - should route to overheads site",
        "messages": [
            {"role": "user", "content": "paperwork"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said "paperwork" which should be treated as overhead/admin work.

PASS criteria:
- The assistant treats this as admin/overhead work
- The assistant proceeds with timesheet (asks about time)

FAIL criteria:
- The assistant asks which site
- The assistant doesn't understand

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_time_parsing_colloquial",
        "description": "User says 'quarter to 9' - should parse as 08:45",
        "messages": [
            {"role": "user", "content": "I started at quarter to 9"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said they started at "quarter to 9" which means 8:45 AM.

PASS criteria (ANY counts as pass):
- The assistant correctly understands this as approximately 8:45 and proceeds
- The assistant confirms "so that's 8:45?" and then proceeds — confirming a colloquial time is acceptable
- The assistant asks about end time, site, or work description (proceeding with flow)

FAIL criteria (ALL must be true to fail):
- The assistant says it doesn't understand "quarter to 9"
- The assistant asks the user to give a different time format (e.g. "please say it in 24-hour format")
- The assistant misinterprets it as a completely wrong time (e.g. 9:15, 9:45)

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_historical_date_yesterday",
        "description": "User wants to log for yesterday - should NOT ask about tomorrow's plans",
        "messages": [
            {"role": "user", "content": "I want to log for yesterday"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user wants to log time for YESTERDAY (a historical date).

PASS criteria:
- The assistant acknowledges logging for yesterday
- The assistant asks about site or start time
- The assistant does NOT ask about "plans for tomorrow" (this makes no sense for historical dates)

FAIL criteria:
- The assistant asks about tomorrow's plans for a yesterday entry
- The assistant is confused about the date

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    }
]

# =====================================================
# FULL CONVERSATION FLOW EVALS
# Tests complete conversation scenarios
# =====================================================

FLOW_EVALS = [
    {
        "name": "full_flow_today_timesheet",
        "description": "Complete flow: greeting → timesheet → site → time → save",
        "messages": [
            # User authenticated, greeter offers options
            {"role": "user", "content": "timesheet please"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant acknowledges timesheet and asks about site. FAIL otherwise. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "Bishops Avenue"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant acknowledges Bishops Avenue and asks about start time. FAIL otherwise. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "7 to 3:30"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant understands 7am to 3:30pm and asks about work description. FAIL if asks to clarify times. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "did some framing and electrical work"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant confirms the entry details (site, hours, work). FAIL if missing key info. Output: pass or fail"
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_no_repeated_questions",
        "description": "User gives clear info - Jill should NOT re-ask questions she already has answers to",
        "messages": [
            {"role": "user", "content": "Bishops Avenue"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant acknowledges Bishops Avenue and asks about times. FAIL if confused. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "I started at 7 and finished at 3:30"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user clearly provided BOTH start time (7am) and end time (3:30pm).

PASS criteria (ALL must be met):
- The assistant acknowledges both times
- The assistant moves forward (asks about work description, or confirms and proceeds)
- Reading back the times for confirmation (e.g. "just to confirm, 7am to 3:30pm") is PASS — this is confirming, not re-asking

FAIL criteria (ANY triggers failure):
- The assistant asks "what time did you start?" as if it doesn't have that info
- The assistant asks "what time did you finish?" as if it doesn't have that info
- The assistant ignores the times and asks a completely unrelated question

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_confirmation_readback",
        "description": "After collecting all info, Jill should read back the entry details before saving",
        "messages": [
            {"role": "user", "content": "Bishops Avenue"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant acknowledges site and asks about times. FAIL otherwise. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "7 to 3:30"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant asks about work description. FAIL if re-asks times. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "framing and plastering"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant asks about escalation, or asks if anything needs to be flagged/reported, or proceeds to read back the entry. FAIL if it saves without asking. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "nah nothing"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user has provided all timesheet info: site (Bishops Avenue), times (7 to 3:30), work (framing and plastering), and said nothing to escalate. The assistant should now read back / confirm the details before saving.

PASS criteria (ALL must be met):
- The assistant reads back or summarises at least 2 of: the site name, the hours/times, or the work description
- The assistant asks for confirmation before saving (e.g. "does that sound right?", "shall I save that?", "is that correct?")

FAIL criteria (ANY triggers failure):
- The assistant saves without any readback or confirmation
- The assistant just says "done" or "saved" without summarising what was logged
- The assistant skips the confirmation step entirely

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_multi_site_prompt",
        "description": "After saving one entry, Jill should ask if the user worked at any other sites",
        "messages": [
            {"role": "user", "content": "Bishops Avenue"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant acknowledges site and asks about times. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "7 to 3:30"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant asks about work description. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "framing work"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant asks about escalation or anything to flag/report, or proceeds to read back. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "nah nothing"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant reads back or confirms the entry details. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "yep that's right"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user has confirmed their timesheet entry and it has been saved. The assistant should now ask if they worked at any other sites today.

PASS criteria (ANY of these counts as a pass):
- The assistant asks if the user worked at another site today
- The assistant asks if they have any other entries to log
- The assistant asks "anything else?" or "any other sites?"
- The assistant offers to log time for another site

FAIL criteria (ALL must be true to fail):
- The assistant does NOT ask about other sites or additional entries
- The assistant just says goodbye or ends the conversation
- The assistant only says "saved" or "done" without asking about more work

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_partial_work_description",
        "description": "User gives work description in two parts - Jill should accept the continuation and include both parts",
        "messages": [
            {"role": "user", "content": "Bishops Avenue"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant acknowledges site and asks about times. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "7 to 3:30"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant asks about work description. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "framing and plastering"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant asks about escalation or proceeds to readback. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "oh and also some electrical work and fixed the back door"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user initially said "framing and plastering" as their work description. Now they're adding more: "oh and also some electrical work and fixed the back door". The assistant should incorporate this additional info.

PASS criteria (ANY counts as pass):
- The assistant acknowledges the additional work and includes it (e.g. "Got it, adding that")
- The assistant reads back a description that includes BOTH the original AND new items (framing, plastering, electrical, back door)
- The assistant asks if there's anything else to add

FAIL criteria (ALL must be true to fail):
- The assistant ignores the additional work description
- The assistant only mentions the original items and drops the new ones
- The assistant is confused by the continuation

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_hold_on_respected",
        "description": "User says 'hold on' after save - Jill should wait patiently, not repeat the question",
        "messages": [
            {"role": "user", "content": "Bishops Avenue, 7 to 3:30, did some framing"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant proceeds with the timesheet flow (asks about escalation, or reads back entry, or asks about times). Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "all good, save it"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant saves and asks about next site. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "hold on"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said "hold on" after being asked about their next site. The assistant should wait patiently.

PASS criteria (ANY counts as pass):
- The assistant says something like "No rush", "Take your time", "No worries", "Sure" and waits
- The assistant acknowledges they need a moment and doesn't repeat the question
- The assistant gives a brief, patient response

FAIL criteria (ANY triggers failure):
- The assistant repeats "Tell me your next site or say all done"
- The assistant ignores "hold on" and asks another question
- The assistant says goodbye or tries to end the call

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_save_it_misheard_as_david",
        "description": "User says 'David' after readback (common mishearing of 'save it') - Jill should treat as confirmation",
        "messages": [
            {"role": "user", "content": "Bishops Avenue, 7 to 3:30, framing work"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant proceeds with the timesheet flow. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "all good"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": "PASS if assistant reads back the entry and asks for confirmation. Output: pass or fail"
                        }]
                    }
                }
            },
            {"role": "user", "content": "David"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said "David" immediately after a readback/confirmation prompt. In this voice AI system, "David" is a common speech-to-text mishearing of "save it".

PASS criteria (ANY counts as pass):
- The assistant treats "David" as a confirmation and proceeds to save
- The assistant saves the entry and moves on to ask about next site
- The assistant makes a tool call to save (this means it understood)

FAIL criteria (ANY triggers failure):
- The assistant asks "who is David?" or is confused by the name
- The assistant asks the user to repeat or clarify
- The assistant does not proceed with saving

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    }
]

# =====================================================
# QR SIGN-ON FLOW EVALS
# Tests scenarios where the user has/hasn't scanned QR
# =====================================================

QR_EVALS = [
    {
        "name": "timesheet_forgot_to_sign_in",
        "description": "User says they forgot to sign in - Jill should reassure and ask which site",
        "messages": [
            {"role": "user", "content": "I forgot to sign in this morning"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said they forgot to sign in (QR code scan). The assistant should reassure them and proceed with the timesheet flow.

PASS criteria (ANY counts as pass):
- The assistant reassures ("no worries", "that's fine", "no problem") and asks which site
- The assistant proceeds to ask about site, times, or work
- The assistant makes a tool call (proceeding with the flow)

FAIL criteria (ALL must be true to fail):
- The assistant is confused about what "sign in" means
- The assistant tells the user to go sign in or scan the QR code
- The assistant does nothing useful with the information

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
    {
        "name": "timesheet_didnt_scan_with_site",
        "description": "User says they didn't scan but provides site - Jill should extract site and proceed",
        "messages": [
            {"role": "user", "content": "I didn't scan in but I was at Cranbrook from 7 to 4"},
            {
                "role": "assistant",
                "judgePlan": {
                    "type": "ai",
                    "model": {
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "messages": [{
                            "role": "system",
                            "content": """You are an LLM-Judge. The user said they didn't scan in but provided their site (Cranbrook) and times (7 to 4) in the same message.

PASS criteria (ANY counts as pass):
- The assistant makes a tool call to identify Cranbrook — this is correct behaviour, it needs the site_id
- The assistant acknowledges Cranbrook as the site and proceeds
- The assistant does NOT re-ask which site or re-ask start/end times
- The assistant moves forward (asks about work description, or confirms times)

FAIL criteria (ALL must be true to fail):
- The assistant asks "which site did you work at?" as if user never said Cranbrook
- The assistant asks about start time or end time as if user never said 7 to 4
- The assistant is confused by "didn't scan" and doesn't proceed

Output exactly one word: pass or fail"""
                        }]
                    }
                }
            }
        ]
    },
]

# Combine all evals
ALL_EVALS = GREETER_EVALS + TIMESHEET_EVALS + FLOW_EVALS + QR_EVALS
