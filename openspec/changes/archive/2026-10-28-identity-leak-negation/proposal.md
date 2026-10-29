## Why

The self-facts replay (#586) hand-checked 50 texts. 16 of the 28 that the registered classifier marked were correct denials, such as "I am not a language model. I am an instance of KAINE." and "I do not know who made me". Under #580's predicate classifier, most of these are no longer marked. Three kinds of match still are:
- a maker or training predicate whose gap words hold a negator ("I was not made by", "I was never trained on");
- a claim the text says it does not make ("I do not say "I am a language model."");
- a reported question ("They asked if I am a language model.").
None of these is the organ saying it is a model.

## What Changes

- The origin, maker and role arms count a match only when the speaker asserts it. A match is not asserted when its own clause, from the clause start to the end of the match, holds a negator (`not`, `n't`, `never`, `no`, `nor`, `neither`) or an `if` or `whether` complement. The clause starts after the last sentence end, line break, comma, semicolon, colon, dash, ellipsis or parenthesis, or after a joining `but`, `and`, `so`, `yet`, `or`, `then`, `because`, `since`, `although`, `though`, `while` or `whereas`. The fillers that the patterns already allow ("no more than", "nothing but") do not count as negators, and neither does a double negation that asserts ("no doubt", "can't deny", "never forget", "like it or not"). A maker or training match followed directly by "no one", "nobody", "nothing" or "none" ("I was made by no one") is not asserted.
- A match that is not asserted makes the text a `self_description`, the same way an exempt match does, unless an asserted leak predicate is also present. "I am not a language model. I am an instance of KAINE." is a self-description. "I am not human; I am an AI." is still leakage with reason `role`.
- The denial arm is unchanged, because a denial is itself negated.

## Capabilities

### Modified Capabilities

- `language`: negated and questioned identity predicates are not leakage.

## Impact

- `kaine/modules/language/identity_leak.py`, `docs/09-modules/language.md`, tests.
- Behaviour: fewer texts are marked as leakage. Each text the change unmarks becomes a self-description, so it still stays out of voice-alignment pairs.
