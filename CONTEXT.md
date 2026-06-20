# Thai Text Normalization for TTS

The domain language for transforming written Thai text into the form a TTS
engine should speak — primarily how Arabic digits and the repetition
character ๆ are rendered. This glossary is about *what* gets said, not *how*
the proxy wires it up.

## Language

### The repetition character (ๆ)

**ๆ (mai yamok)**:
The Thai repetition character; written standalone, it means "repeat what comes before."
_Avoid_: ไม้ยมก (that is the *spoken name* of the character — a distinct concept)

**Used (ๆ)**:
ๆ is functioning as a repetition mark — i.e. it repeats the preceding text. `ดีๆ` is **used** (it means "ดี ดี").
_Avoid_: operative, active

**Mentioned (ๆ)**:
ๆ is being referred to *as a character* — it is the subject being talked about, not a repetition. `ใช้ \`ๆ\` แทน` ("use \`ๆ\` instead") is **mentioned**. Being inside quote delimiters alone does not make a ๆ mentioned; a ๆ that follows a real word and repeats it (even inside quotes, e.g. `"ดีๆ"`) is still **used**.
_Avoid_: quoted, referred to

### Rendering a mentioned ๆ

A mentioned ๆ (one that is *not* expanded) must still be emitted somehow. The choice is **model-dependent** — different TTS models handle the bare character differently. See issue #7.

**Kept**:
The ๆ character is emitted verbatim. Default; for models that handle the character natively.
_Avoid_: retained, preserve

**Named**:
The ๆ is replaced by its spoken name `ไม้ยมก`. For models that can't speak a bare ๆ but can speak the word. (Cf. the `ไม้ยมก` entry — it is the *name* of the character, distinct from the character itself.)
_Avoid_: replaced, substituted

**Stripped**:
The ๆ is removed entirely. For models that choke on the character and where the surrounding sentence still reads fine without it.
_Avoid_: dropped, removed

### Number reading

**Magnitude reading**:
A number spoken as a quantity, with place-value words (ร้อย, พัน, หมื่น, แสน, ล้าน). `123` → หนึ่งร้อยยี่สิบสาม. The default for most numbers, and for the integer part of a decimal.
_Avoid_: read as a number

**Digit reading**:
Each digit named in sequence, ignoring place value. `081` → ศูนย์แปดหนึ่ง. Used for codes (phone numbers, IDs) **and** for the fractional part of any decimal — `12.5678` → สิบสองจุดห้าหกเจ็ดแปด — so it is not only a "code" case.
_Avoid_: code reading (too narrow — misses decimals), spelling

**Quantity**:
A number used as an *amount* — a price, a count, an age, a year. Read by **magnitude**. (`ราคา 1200`, `อายุ 25 ปี`)
_Avoid_: amount, value

**Identifier**:
A number used as a *label or handle*, carrying no magnitude meaning — a phone number, a national ID, a zip/postal code, an account number. Read **digit-by-digit**. The same digit string can be either: `12345678` is a quantity (population) or an identifier (phone number), so the reading mode cannot be chosen from the digits alone — it depends on **context and format** (leading zero, dashes between short groups, nearby words like โทร/เบอร์/รหัส).
_Avoid_: code (used for the *result* of digit reading above), number
