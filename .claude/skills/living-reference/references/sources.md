# Living reference: standards and sources behind the format

Checked in November 2026. Most entries were checked through search excerpts of the publisher's page, not by reading the full standard. Check the edition and the rule number again before you rely on one of them. No behaviour of the scripts depends on these sources.

## Indexing

- ANSI/NISO Z39.4-2021, *Criteria for Indexes*.
- ISO 999:1996, the ISO standard on indexes.
- *The Chicago Manual of Style*, chapter on indexes (chapter 15 in the 18th edition; chapter 16 in the 17th edition).
- American Society for Indexing, *Index Evaluation Checklist*. The checklist asks whether main headings have "not more than 5–7 locators". The refresh script warns above 7. The Society's guidance also gives the audience example behind the rule "use the reader's word": a general reader and a clinician look up the same condition under different terms.
- Johns Hopkins University Press, indexing guidelines for authors: "Indexes require human involvement—they must be thought into being." https://www.press.jhu.edu/books/information-for-authors/author-resources/indexing-guidelines

## Controlled vocabulary

- ANSI/NISO Z39.19-2005 (R2010) covers controlled vocabularies. It uses USE and UF ("used for") to link an entry term and a preferred term. The glossary's `UF:` field and the index's *see* entries follow that notation.

## Citations

- The short-cite idea follows the short-form rules of *The Bluebook* (Rule 4 and Rule 10.9). This skill does not reproduce their conditions.
- Federal Rule of Appellate Procedure 28(a)(3) requires a table of authorities: cases in alphabetical order, then statutes, then other authorities. Finer groups and sorting inside each group are common practice, not rule text. The cite index of this skill keeps the order of the source list.
- The fields of a source line follow Citation Style Language variable names (`author`, `title`, `container-title`, `issued`, `URL`, `accessed`). A source line is free text, not CSL data, and `Grade` is not a CSL variable.

## Structure

- Law-school outlining guides (UC Davis School of Law, the American Bar Association, Touro Law Center) organise an outline by rule, not by case.
- The ID format borrows from Johnny.Decimal. Its author follows the practice of not reusing an ID. The rule "do not renumber" is this skill's own.
- Lemarié, Lorch and Péry-Woodley, "Understanding How Headings Influence Text Processing", *Discours* 10 (2012). The abstract reports that headings improve memory for text organisation and that titles bias text comprehension. https://doi.org/10.4000/discours.8600

## Typography

- Matthew Butterick, *Practical Typography*: the page on underlining is headed "Absolutely not", and the book treats bold and italic as mutually exclusive. https://practicaltypography.com/underlining.html
