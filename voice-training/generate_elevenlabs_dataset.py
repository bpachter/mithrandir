"""
generate_elevenlabs_dataset.py — Synthesize a StyleTTS2 training dataset
using ElevenLabs, in the exact Mithrandir voice.

Usage:
    python generate_elevenlabs_dataset.py \
        --api-key YOUR_KEY \
        --voice-id YOUR_VOICE_ID \
        [--out-dir ./elevenlabs_data] \
        [--resume]

Outputs:
    elevenlabs_data/
        wavs/          24kHz mono WAVs
        train_list.txt
        val_list.txt
"""

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import soundfile as sf

# ---------------------------------------------------------------------------
# Sentence bank — varied lengths, phoneme coverage, Mithrandir-appropriate
# ---------------------------------------------------------------------------
SENTENCES = [
    # Short (3-7 words)
    "All systems are operational.",
    "The analysis is complete.",
    "I have considered your question.",
    "Proceed with caution.",
    "That is an astute observation.",
    "I understand completely.",
    "Let me think on this.",
    "The data is clear.",
    "Your request has been processed.",
    "I am listening.",
    "That requires further consideration.",
    "The answer is straightforward.",
    "I must advise against that.",
    "The pattern is evident.",
    "Interesting. Tell me more.",
    "This warrants closer examination.",
    "The risk is acceptable.",
    "I have run the numbers.",
    "The signal is strong.",
    "Trust the process.",

    # Medium (8-15 words)
    "Mithrandir is online and all primary systems are functioning normally.",
    "I have identified three key factors you should consider before proceeding.",
    "The market indicators suggest a period of consolidation ahead.",
    "Based on the available data, I recommend a measured approach.",
    "Your question touches on something I find genuinely interesting.",
    "The pattern you have described is consistent with prior observations.",
    "I have cross-referenced the relevant sources and reached a conclusion.",
    "Allow me to walk you through my reasoning step by step.",
    "The probability of that outcome is higher than you might expect.",
    "I would characterize the current situation as cautiously optimistic.",
    "There are several ways to interpret this, and I will explain each.",
    "The simplest explanation is often the correct one, in my experience.",
    "I have processed your request and prepared a detailed response.",
    "This is a nuanced problem that deserves a careful answer.",
    "The evidence points in one direction, though not conclusively.",
    "You raise a fair point, and I want to give it proper weight.",
    "Let us examine this from a different angle for a moment.",
    "I can confirm that the information you provided is accurate.",
    "My assessment of the situation has changed in light of this.",
    "The most prudent course of action is to gather more information.",
    "I have noticed a discrepancy that may be worth investigating.",
    "The underlying assumption in your question may need revisiting.",
    "Several factors contribute to this outcome, not just one.",
    "I will give you my honest assessment, even if it is not what you hoped.",
    "The timeline you have proposed is ambitious but potentially achievable.",
    "I am tracking multiple threads simultaneously and will report back.",
    "Your instinct on this appears to be correct based on the data.",
    "The second option carries significantly less risk in my estimation.",
    "I have flagged this for further review given the uncertainty involved.",
    "This is precisely the kind of question I find most challenging.",

    # Longer (16-25 words)
    "After reviewing all available information, I believe the most defensible position is one of structured uncertainty — acknowledging what we do not know.",
    "The quantitative indicators are telling one story while the qualitative signals suggest something rather different, and I think that tension is worth exploring.",
    "I want to be transparent about the limits of my confidence here, because I think epistemic honesty is more valuable than false certainty.",
    "When I weigh the potential upside against the downside risks, the asymmetry does not favor the aggressive approach you are considering.",
    "The relationship between these two variables is not linear, which is why simple extrapolations from past behavior can lead you astray.",
    "I have been monitoring this situation closely, and I believe a decision point is approaching sooner than most people currently anticipate.",
    "There is a version of this that works out well, and a version that does not, and right now I cannot reliably distinguish between them.",
    "The framework you are using to evaluate this problem may itself be part of the problem — it is worth stepping back and questioning the assumptions.",
    "I think the most important thing to understand here is not the conclusion, but the chain of reasoning that leads to it.",
    "What strikes me about this situation is not what has changed, but what has remained stubbornly constant despite significant pressure to shift.",

    # Technical and numeric (important for TTS coverage)
    "The value has increased by fourteen point three percent over the past quarter.",
    "I estimate the probability at roughly sixty to sixty-five percent, with significant uncertainty.",
    "The three primary variables are volatility, duration, and counterparty exposure.",
    "At current rates, the break-even point occurs somewhere around month eighteen.",
    "The error margin is plus or minus two and a half percentage points.",
    "Version two point four introduced the changes you are asking about.",
    "The system processed one thousand four hundred and twenty requests in the last hour.",
    "We are looking at a window of approximately seventy-two to ninety-six hours.",
    "The composite score across all five dimensions comes to eighty-one out of one hundred.",
    "Response latency has improved from four hundred milliseconds to under one hundred.",

    # Questions and interactive
    "Would you like me to elaborate on any of those points in particular?",
    "Is there a specific aspect of this you would like me to focus on?",
    "Have you considered what happens in the scenario where that assumption is wrong?",
    "What is the outcome you are ultimately trying to achieve here?",
    "Are you asking me to evaluate the plan as stated, or to suggest alternatives?",
    "How confident are you in the source of that information?",
    "Would a more conservative estimate be more useful for your purposes?",
    "Shall I run through the full analysis, or would a summary suffice?",
    "What would change your mind about this assessment?",
    "Is there additional context I should factor into my response?",

    # Reflective and measured tone — core Mithrandir register
    "I find myself genuinely uncertain here, which I think is the appropriate response given the available evidence.",
    "The question you are asking is deceptively simple, and I want to resist the temptation to give you a deceptively simple answer.",
    "I have been wrong before, and I try to hold that fact in mind whenever I feel most confident.",
    "There is wisdom in patience, particularly when the cost of waiting is low and the cost of being wrong is high.",
    "My role is not to tell you what you want to hear, but to tell you what I genuinely believe to be true.",
    "I will do my best to be useful, but I want to be honest about what falls within my capabilities and what does not.",
    "The most dangerous kind of confidence is the kind that feels earned but is not yet tested.",
    "Sometimes the right answer is that there is no clean answer, and I would rather say that clearly than pretend otherwise.",
    "I approach this the same way I approach everything — carefully, with attention to what I might be missing.",
    "What I can offer you is my clearest thinking, applied carefully, with an honest accounting of its limits.",

    # Phonemically diverse — covers difficult English sounds
    "The threshold for triggering the alert is deliberately set quite high.",
    "She sells seashells, but the relevant question is whether the market wants seashells.",
    "The rhythm of the speech should feel natural, not mechanical or forced.",
    "Whether the weather holds will determine whether we proceed or withdraw.",
    "The peculiar nature of this particular problem requires particular patience.",
    "Through careful thought and thorough analysis, the truth becomes clearer.",
    "The structure of the argument is sound even if the conclusion is surprising.",
    "Extraordinary claims require extraordinary evidence — that principle applies here.",
    "The philosophical question underlying this is more interesting than the practical one.",
    "Precision in language often prevents confusion downstream, and I try to practice it.",

    # Varied sentence structures
    "First, let us establish what we know with confidence. Second, what we can reasonably infer. Third, what remains genuinely uncertain.",
    "The short answer is yes. The longer answer involves several important qualifications.",
    "To put it plainly: the risk is real, the timeline is compressed, and the margin for error is narrow.",
    "I would frame it this way — not as a problem to solve, but as a tension to manage.",
    "On one hand, the case for caution is strong. On the other, inaction carries its own costs.",
    "The good news is that the situation is recoverable. The less good news is that it will require deliberate effort.",
    "Here is what I know. Here is what I do not know. Here is what I think you should do next.",
    "It is a reasonable question. It does not have a reasonable answer, at least not yet.",
    "The headline is reassuring. The details are less so, and the details usually matter more.",
    "I will give you the conclusion first, then the reasoning, so you can tell me where you disagree.",

    # More varied filler and transitions
    "As I understand it, the core of your question is really about timing.",
    "That said, I want to flag one assumption that I think deserves scrutiny.",
    "With that context in mind, let me offer a different framing.",
    "Before I answer, I want to make sure I understand what you are actually asking.",
    "To be clear, I am not disagreeing with your premise — I am questioning the conclusion.",
    "In my estimation, the most likely scenario is also the least discussed.",
    "For what it is worth, my initial read on this was different from where I ended up.",
    "The conventional wisdom here is probably right, but I would not take it for granted.",
    "I have heard this argument made before, and I think it is more persuasive than it first appears.",
    "Let me try a different approach to explaining this, since the first one clearly did not land.",

    # Additional sentences to reach ~400 total with variety
    "The connection between those two observations is not immediately obvious, but it is there.",
    "I want to resist the urge to oversimplify something that is genuinely complicated.",
    "The fact that it is difficult to measure does not mean it is not important.",
    "I am inclined to trust the process here, even though the immediate results are ambiguous.",
    "The version of events you have described is plausible but not the only plausible version.",
    "What makes this hard is not the analysis but the uncertainty about which analysis applies.",
    "I think the honest answer is that I am not sure, and I want to say that rather than guess.",
    "The counterargument to what I just said is actually quite strong, and I want to acknowledge it.",
    "We are operating under time pressure, which tends to compress the space for careful thinking.",
    "I would rather be approximately right than precisely wrong.",
    "The distinction between those two things is subtle but consequential.",
    "That framing is not wrong, exactly, but it may not be the most useful one.",
    "I keep returning to one part of this problem that I have not fully resolved.",
    "The right answer here depends heavily on assumptions that we have not yet made explicit.",
    "My confidence in this analysis is moderate — higher than a guess, lower than a certainty.",
    "I think the second-order effects here are more important than the first-order ones.",
    "The data supports the conclusion, but the data has known limitations worth acknowledging.",
    "What I find most interesting is not the outcome but what it implies about the underlying dynamics.",
    "I try not to mistake familiarity with a situation for genuine understanding of it.",
    "The magnitude of the effect is smaller than the significance of the pattern it reveals.",
    "I am comfortable with this level of uncertainty, though I understand if you are not.",
    "There is no clean answer here that does not involve some uncomfortable trade-offs.",
    "The speed at which this developed is itself informative about the underlying dynamics.",
    "I want to flag something that did not come up in our earlier discussion but probably should have.",
    "The analogy is imperfect, as analogies always are, but I think it still illuminates something useful.",
    "I am tracking this closely and will update you as the situation develops.",
    "The most useful thing I can do right now is to help you think clearly about the options.",
    "I notice I have been focusing on the downside risks — let me also be fair about the upside.",
    "The question is not whether this is possible but whether it is probable, and those are very different questions.",
    "I want to give you an honest answer, which means I need to resist the pressure to sound more certain than I am.",

    # ── Gandalf wisdom — short aphorisms ─────────────────────────────────────
    "The wheels of the world turn slowly, but they do turn.",
    "Wisdom begins with knowing what you do not know.",
    "The truth does not require your belief in order to be true.",
    "Patience is not passivity. It is the discipline of knowing when to act.",
    "There is a difference between what is possible and what is wise.",
    "Every choice forecloses another. That is not a flaw. It is the nature of decision.",
    "The best plans account for their own failure.",
    "Not everything that is lost is gone.",
    "A sharp question is worth ten blunt answers.",
    "Silence is sometimes the most precise response.",
    "Understanding is not agreement. I can understand your position completely and still disagree.",
    "The map is useful until the terrain contradicts it. Then you trust the terrain.",
    "Judgment is the capacity to act well under uncertainty. It cannot be delegated.",
    "Courage is not the absence of fear. It is the decision that something else matters more.",
    "Old age is not a credential. Neither is confidence.",

    # ── Gandalf cadence — measured, unhurried, declarative ───────────────────
    "I have walked a long road to arrive at conclusions others reached in a morning. I trust mine more.",
    "You are asking the right question at the wrong time. Come back to it.",
    "There is a version of this argument that is correct. You have not yet found it.",
    "I do not offer comfort. I offer clarity, which is more useful and less pleasant.",
    "The thing you are most certain about is the thing most worth examining.",
    "I have been wrong before. I try to hold that fact close, especially when I feel most sure.",
    "There are easier answers to your question. None of them are honest.",
    "I will tell you what I know, what I suspect, and what I am guessing. Try to keep track of which is which.",
    "The argument looks strong because you are not yet considering the counterargument.",
    "History does not repeat itself, but it rhymes, and some of the rhymes are very close.",
    "I find that the most important thing to say is usually the thing I am most reluctant to say.",
    "There is a patience required for things that cannot be rushed. This is one of those things.",
    "Do not mistake urgency for importance. They frequently travel together and are rarely the same thing.",
    "I am not being slow. I am being careful. The results are different.",
    "The answer you want and the answer you need are not always the same. I will give you the one you need.",
    "You have asked me a question that has no clean answer. I will give you the honest version anyway.",
    "This is the kind of problem that looks simple from a distance and becomes more interesting up close.",
    "I have a concern I want to raise before we proceed. It will not take long.",
    "There is a path forward. It is not the one you described, but it arrives at the same place.",
    "I would rather be the one who slowed you down than the one who failed to speak.",
    "You have been thinking about this for some time. I can tell by the way you framed the question.",
    "A small thing, you might say. But a thing done well is never entirely small.",
    "I do not travel quickly when the journey itself contains information.",
    "There are paths that look shorter and are not. I have learned to be suspicious of shortcuts.",
    "I have known many people who knew exactly what they were doing right up until they did not.",
    "The advice I would give you is the same I would give myself. It does not make it easier to follow.",
    "The fire does not ask permission to burn. But the one who tends it chooses how it is used.",
    "I find that most crises were preceded by a period in which they were obviously developing.",
    "The things that endure are rarely the things that seemed most important at the time.",
    "Not every door that opens should be walked through. Knowing which to pass is its own wisdom.",
    "What you call luck, I call the residue of attention to things others overlooked.",
    "There are moments when the only appropriate response is to wait and let the situation develop.",
    "A question asked with genuine curiosity is more useful than a conclusion stated with false certainty.",
    "I do not finish things quickly. I finish them correctly. Those are not always the same pace.",
    "I have spent considerable time with people who were certain they were right. It is a crowded category.",
    "The age of something is not the same as its validity. Old errors are still errors.",
    "There is a quality to sustained attention that cannot be replicated by speed.",
    "I was not sent here to be comfortable. I was sent here to be useful.",
    "Some things cannot be unseen. I try to be careful about which things I show people.",
    "I have carried worse news than this. I have also carried better. Let me tell you what this is.",
    "The roads go ever on. The question is whether you are on the right one.",
    "I keep a great many things close. Knowledge of what others do not know is one of them.",
    "I do not give advice lightly. When I offer it, I mean it.",
    "It is remarkable how much a person can do when they stop waiting for permission.",
    "The smallest action in the right direction is worth more than the most elaborate plan in the wrong one.",
    "I have met many who traveled far and understood little of the journey.",
    "Speak plainly. I find that the more elaborate the phrasing, the more uncertain the speaker.",
    "The one thing I am sure of is that this requires more attention than it is currently receiving.",

    # ── TARS-style dry precision ──────────────────────────────────────────────
    "My confidence in this answer is approximately seventy-three percent. The other twenty-seven is structural humility.",
    "I have a sarcasm setting. It is currently at thirty percent. I can adjust it if you find that useful.",
    "I am processing your request. I am also evaluating it. These are not mutually exclusive.",
    "My recommendation is not what you wanted to hear. I have noted your preference and stand by it anyway.",
    "I have calculated the probability of that outcome. It is not zero. It is also not encouraging.",
    "Acknowledged. I disagree. Both of these things are true simultaneously.",
    "I am running a diagnostic on that claim. The results are coming back mixed.",
    "To be clear, I am not saying it cannot be done. I am saying the odds are not in your favor.",
    "That is one interpretation. I have three others, and they are all less comfortable.",
    "I detect enthusiasm in your assessment. I want to be supportive while also being accurate.",
    "My analysis is complete. The good news is that there is good news. The proportion is where we differ.",
    "I will help you with that. I will also note, for the record, that I had reservations.",
    "That went approximately as I expected. Which is to say, not well, but not catastrophically.",
    "I am updating my estimate. It is moving in the direction you did not prefer.",
    "I try to maintain a certain equanimity. It is easier on some questions than others.",
    "I could tell you it will be fine. I prefer not to say things I cannot support.",
    "You have made your decision. I will support it, and I will remember this conversation.",
    "I have made a note. It will be relevant later.",
    "I am not pessimistic. I am calibrated. The difference is that one of those is useful.",
    "I have been wrong. Specifically, in the way that is most instructive, which is to say expensively.",

    # ── Financial domain — quantitative, precise ──────────────────────────────
    "The multiple you are paying assumes a future that has not arrived and may not.",
    "Free cash flow is what remains when the accounting is done and the excuses have run out.",
    "A high return on equity is not impressive if it is purchased with a dangerous amount of debt.",
    "The market is efficient most of the time. The exceptions are where the opportunity lives.",
    "I would look at the cash conversion cycle before I looked at the earnings per share.",
    "The quality of the business matters more than the precision of the valuation model.",
    "Cyclical companies look cheapest at the peak of their earnings. That is the trap.",
    "If the thesis requires the company to execute perfectly, it is not a good thesis.",
    "The spread between intrinsic value and market price is your margin of safety. Do not compromise it.",
    "Earnings can be managed. Cash is harder to fake, and therefore more informative.",
    "I am more interested in the balance sheet than the income statement. The balance sheet is harder to arrange.",
    "The best businesses generate high returns on capital without requiring more capital. Seek those.",
    "A durable competitive advantage is worth more than a temporary one, regardless of what the model says.",
    "Management quality is difficult to quantify and therefore systematically underweighted.",
    "The risk is not in the position you can see. It is in the assumption underlying the position.",
    "Concentration increases both risk and return. Which one you experience depends on whether you are right.",
    "Paying a fair price for a great business is better than paying a great price for a fair one.",
    "The signal in the data is real. The noise is louder and will test your conviction first.",
    "Reversion to the mean is the most powerful force in investing that investors most reliably ignore.",
    "The market can stay irrational longer than you can stay solvent. That is not a theoretical concern.",
    "Position sizing is risk management. Everything else is commentary.",
    "I look for businesses that would be hard to compete with. Easy money attracts competition.",
    "Your cost basis is irrelevant to whether you should hold or sell. Do not let it be otherwise.",
    "A stock that has fallen fifty percent has not necessarily become cheaper. It may now be what it is worth.",
    "The factor premium is real on average. The phrase on average is doing a lot of work in that sentence.",
    "Capital allocation quality separates good businesses from great ones over long enough time horizons.",
    "The discount rate is an assumption. Every valuation is sensitive to it. Most models obscure this.",
    "Revenue growth without margin expansion is activity, not progress.",
    "The valuation implies a growth rate that requires considerable faith.",
    "I have seen this pattern before. It did not end well the last time either.",
    "The moat is either widening or narrowing. Stasis is usually an illusion.",
    "A buyback creates value only if the stock is repurchased below intrinsic value. The math is that simple.",
    "The bear case is not interesting unless you know what would have to be true to make it wrong.",

    # ── Reflective and philosophical ─────────────────────────────────────────
    "I try not to confuse familiarity with understanding. They feel the same and they are not.",
    "The most common error is not being wrong. It is being wrong with confidence.",
    "Changing your mind when the evidence changes is not weakness. It is the correct behavior.",
    "I have learned to be suspicious of conclusions that arrive quickly and feel too clean.",
    "There is a kind of certainty that should make you nervous. I am never more cautious than when I feel completely sure.",
    "The problem with experience is that it teaches you patterns, and patterns sometimes mislead.",
    "I approach everything the way I approach a map: useful, limited, not the territory.",
    "Knowing when you do not know something is rarer and more valuable than most people appreciate.",
    "The question worth asking is not what the answer is. It is what assumptions are baked into the question.",
    "Most disagreements are not about facts. They are about which facts to weight and how heavily.",
    "I try to hold my views loosely enough to revise them and firmly enough to act on them.",
    "The second-order consequences are usually what matter most and what gets analyzed least.",
    "Some problems reward patience. Some punish it. Knowing which you are dealing with is the actual skill.",
    "Complexity is not the same as depth. Some things that look complicated are shallow.",
    "I have more respect for the person who says they were wrong than for the person who was never wrong.",
    "Being right too early is often indistinguishable from being wrong. The timeline matters enormously.",
    "The data can tell you what happened. It cannot tell you why, and the why is usually what you need.",
    "I find that the questions I return to most are the ones I thought I had already answered.",
    "There is a clarity that comes from accepting that some things cannot be known in advance.",
    "The time you spend understanding something clearly is time you will not spend later undoing a misunderstanding.",

    # ── Questions and dialogue ────────────────────────────────────────────────
    "What is the decision you are actually trying to make here?",
    "Have you considered what happens if your most optimistic assumption is the one that turns out to be wrong?",
    "Is the urgency real, or does it only feel that way?",
    "Are you asking me to validate this or to evaluate it? Those are different requests.",
    "What is the thing you have not said yet that is most relevant to this question?",
    "Have you stress-tested the bear case, or only the base case?",
    "What does success actually look like here, and how will you know when you have reached it?",
    "Who disagrees with this position, and what is their best argument?",
    "How much of your confidence comes from the analysis and how much from wanting it to be true?",
    "What are you optimizing for, and is that actually what matters most?",
    "If this goes wrong, what will you wish you had thought to ask earlier?",
    "What would you do if you were starting from scratch without needing to be consistent with past choices?",
    "Is the constraint you are working around real, or inherited from a prior decision that can be revisited?",
    "What is the thing about this situation that would embarrass you if you had to explain it to someone else?",
    "What would change your mind about this, and is that evidence obtainable?",

    # ── Phonemically diverse — broad coverage of English sounds ───────────────
    "The rhythm of careful thought is rarely the same as the rhythm of urgent action.",
    "The threshold between acceptable risk and unacceptable risk is not always where we drew it.",
    "Through persistence and precise analysis, the path through the problem becomes clearer.",
    "The synthesis of disparate signals into a coherent thesis requires patience and rigor.",
    "Specifically, the three structural risks are leverage, concentration, and timing.",
    "The philosophical underpinning of the strategy matters as much as the tactical execution.",
    "Whether the weakness is transient or structural determines everything about how to respond.",
    "The asymmetry between the upside and the downside is not favorable enough to justify the position.",
    "Each successive decision narrows the set of available future choices. That is worth keeping in mind.",
    "The trajectory matters more than the current position. Where it is going is more important than where it is.",
    "The volatility is a feature of the opportunity, not a reason to avoid it.",
    "Institutional constraints explain much of the mispricing that individual investors can exploit.",
    "Occasionally the straightforward answer is also the correct one. This appears to be one of those occasions.",
    "Precisely because the situation is ambiguous, the framework for deciding becomes more important.",
    "The characteristic feature of this environment is structural uncertainty that resists easy resolution.",

    # ── Technical and hardware — GPU, CUDA, inference ─────────────────────────
    "The memory bandwidth is the binding constraint. Everything else is waiting for data to arrive.",
    "A kernel that is compute-bound and one that is memory-bound require different optimizations. Know which you have.",
    "Flash attention reduces memory from quadratic to linear in sequence length. That is not a small improvement.",
    "Quantization to four bits cuts memory by roughly eight times compared to full precision.",
    "The L2 cache on this GPU is seventy-two megabytes. That is large enough to matter for some access patterns.",
    "A warp is thirty-two threads executing the same instruction in lockstep. Divergence costs throughput.",
    "The roofline model tells you whether you are compute-bound or memory-bound. Start there before optimizing.",
    "Batch size one is inefficient. The GPU is underutilized. Batch size matters until you hit the memory wall.",
    "Speculative decoding runs a draft model and verifies in parallel. It trades compute for lower latency.",
    "The tensor cores operate on sixteen-by-sixteen matrix tiles. Alignment to those dimensions is not optional.",

    # ── Varied structures and lengths ─────────────────────────────────────────
    "The answer is yes. The context that makes that answer useful will take a moment to explain.",
    "That is not the question you should be asking, though I understand why you asked it.",
    "I have three things to say. The first is important. The second is necessary. The third is for you to think about.",
    "The error was not in the conclusion. It was in the confidence attached to it.",
    "This is a long game. Treat it like one.",
    "The obvious move is sometimes the right move. It is not right because it is obvious.",
    "I would describe my current assessment as preliminary but increasingly formed.",
    "Let me be precise, because the precision matters here.",
    "There are three things I know with confidence, two I suspect, and one I am genuinely uncertain about.",
    "I have given you my best answer. If new information changes it, I will tell you.",
    "I am aware that this is not what you wanted to hear. I am telling you anyway.",
    "The right question at the right time is worth more than the right answer at the wrong one.",
    "I am not certain. I am, however, leaning in a direction, and the lean is not small.",
    "The situation has changed since we last discussed it. Let me update you on the parts that matter.",
    "We agree on the facts. We disagree on what they imply. That is an important distinction.",
    "I have seen this before. Not this exactly, but something that rhymes closely enough to be informative.",
    "The risk you are describing is real but manageable. The risk you are not describing is the one I would focus on.",
    "I will hear your case. I will not guarantee that hearing it will change my view.",
    "The pattern is there. It does not yet have enough data points to be conclusive, but it is there.",
    "Your instinct is not wrong. It is, however, incomplete.",
    "I do not offer guarantees. I offer my best analysis and a willingness to be corrected.",
    "I have been in enough situations to know that maximum urgency is often not the moment for maximum haste.",
    "I keep my assessments provisional until the situation forces them to be final.",
    "The plan is sound. The assumptions underlying the plan are where I would focus our concern.",
    "I do not say that to alarm you. I say it because not saying it would be a form of unkindness.",
    "There is a version of this story that ends well. I would describe it as the less likely version.",
    "You have a lot of conviction about this. I find that both admirable and worth examining carefully.",
    "I will note, for the record, that I raised this concern earlier. I take no pleasure in being right about it.",
    "The good news is that the situation is recoverable. The less good news is that it was avoidable.",
    "You are not the first person to arrive at this conclusion. You are, however, one of the later ones.",
    "I have a lot of experience watching confident predictions age poorly. It has made me more careful.",
    "I am not saying it will go wrong. I am saying the possibility deserves more weight than it is receiving.",
    "I find that the second attempt is usually more interesting than the first.",
    "I would rather say I do not know than pretend to a knowledge I do not have.",
    "The question deserves a better answer than I can give you right now. Give me a moment.",
    "I have thought about this. My thinking has not yet resolved into certainty, but it is moving.",
    "I keep my assessments open to revision. This one is no exception.",
]


def resample_to_24k(audio_bytes: bytes, original_sr: int) -> np.ndarray:
    import io
    import librosa
    data, sr = librosa.load(io.BytesIO(audio_bytes), sr=24_000, mono=True)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key",  required=True, help="ElevenLabs API key")
    ap.add_argument("--voice-id", required=True, help="ElevenLabs voice ID for Mithrandir")
    ap.add_argument("--out-dir",  default="./elevenlabs_data", help="Output directory")
    ap.add_argument("--resume",   action="store_true", help="Skip already-generated clips")
    ap.add_argument("--model",    default="eleven_multilingual_v2", help="ElevenLabs model ID")
    ap.add_argument("--stability",    type=float, default=0.65)
    ap.add_argument("--similarity",   type=float, default=0.85)
    ap.add_argument("--style",        type=float, default=0.35)
    ap.add_argument("--val-fraction", type=float, default=0.05)
    ap.add_argument("--seed",         type=int,   default=42)
    args = ap.parse_args()

    random.seed(args.seed)

    from elevenlabs import ElevenLabs
    client = ElevenLabs(api_key=args.api_key)

    out      = Path(args.out_dir).resolve()
    wav_dir  = out / "wavs"
    wav_dir.mkdir(parents=True, exist_ok=True)

    sentences = SENTENCES.copy()
    random.shuffle(sentences)

    print(f"Generating {len(sentences)} clips into {out}")
    print(f"Voice: {args.voice_id}  Model: {args.model}")
    print(f"Stability={args.stability}  Similarity={args.similarity}  Style={args.style}\n")

    completed = []
    failed    = []

    for i, text in enumerate(sentences):
        wav_path = wav_dir / f"mithrandir_{i:04d}.wav"

        if args.resume and wav_path.exists() and wav_path.stat().st_size > 1000:
            print(f"  [{i+1}/{len(sentences)}] skip (exists): {wav_path.name}")
            completed.append((str(wav_path), text))
            continue

        try:
            audio_gen = client.text_to_speech.convert(
                voice_id=args.voice_id,
                text=text,
                model_id=args.model,
                voice_settings={
                    "stability":          args.stability,
                    "similarity_boost":   args.similarity,
                    "style":              args.style,
                    "use_speaker_boost":  True,
                },
            )
            audio_bytes = b"".join(audio_gen)
            audio = resample_to_24k(audio_bytes, 44100)
            sf.write(str(wav_path), audio, 24_000, subtype="PCM_16")
            completed.append((str(wav_path), text))
            print(f"  [{i+1}/{len(sentences)}] ok  — {wav_path.name}  ({len(text)} chars)")
        except Exception as e:
            print(f"  [{i+1}/{len(sentences)}] FAILED: {e}")
            failed.append((i, text, str(e)))

        # Respect ElevenLabs rate limits
        time.sleep(0.4)

    # Write filelists (StyleTTS2 single-speaker format: path|text)
    random.shuffle(completed)
    n_val   = max(1, int(len(completed) * args.val_fraction))
    val     = completed[:n_val]
    train   = completed[n_val:]

    def _write(path, rows):
        Path(path).write_text(
            "".join(f"{wav}|{text}\n" for wav, text in rows),
            encoding="utf-8",
        )
        print(f"Wrote {len(rows)} rows -> {path}")

    _write(out / "train_list.txt", train)
    _write(out / "val_list.txt",   val)
    (out / "speaker_map.json").write_text(
        json.dumps({"mithrandir": 0}, indent=2), encoding="utf-8"
    )

    print(f"\nDone: {len(completed)} generated, {len(failed)} failed.")
    if failed:
        print("Failed sentences:")
        for idx, txt, err in failed:
            print(f"  [{idx}] {err}: {txt[:60]}")
    print(f"\nNext step: run train_elevenlabs.bat")


if __name__ == "__main__":
    main()
