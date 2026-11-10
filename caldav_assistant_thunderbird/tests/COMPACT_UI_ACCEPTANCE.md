# Compact Thunderbird UI — resize acceptance checklist

Status: **CSS implemented on feature branch; real Thunderbird acceptance pending**.

Scope: the six shared-stylesheet add-on pages (Work, Today, Record,
Logs, WordPress and Tools). This is a presentation-only change.
Native Thunderbird Task selection, **Start / Stop / Complete / Cancel**,
`currentWorkId` and CalDAV read-back rules are unchanged.

## Resize / scaling matrix

In a real supported Thunderbird with an installed XPI, check each page at:

| Available content viewport | Expected result |
| --- | --- |
| 240 × 360 CSS px | All controls accessible by vertical scrolling; confirmation actions do not clip |
| 320 × 480 CSS px | One-column cards; controls wrap; labels and error details remain readable |
| 480 × 640 CSS px | One-column cards; no unreachable action row or form fields |
| 820 × 600 CSS px | Grid switches to single column; navigation wraps |
| 1024 × 768 CSS px | Comfortable compact two-column tool/settings view |
| 320 × 480, text/zoom 150% | Navigation, buttons, long localized labels and input fields still accessible |

## Human-path scenarios

1. **Work:** inspect no-current hint; start a real Task from Thunderbird's
   native Tasks toolbar; reopen Work, verify current title (also with a very
   long unbroken title), elapsed time, Stop/Complete/Cancel and Cancel
   confirmation/reversal. Verify the confirmation is hidden until requested.
2. **Quick Capture/Post Preview:** verify the text area is usable and
   resizable, preview does not force the whole document wider than the
   viewport, and the open/refresh controls remain visible.
3. **Today/Record:** scroll complete lists; attach a file, enter multi-line
   content and reach the submit/result section.
4. **Logs:** use every date/search/filter and copy/clear action, including
   the clear confirmation. Very long diagnostic lines must wrap or allow
   local scrolling, not hide unrelated controls.
5. **WordPress/Tools:** check long transport choices, checkboxes next to their
   explanatory text, every save/test/retry action, long errors and receipts;
   collapse to one column on narrow widths.
6. **Native Thunderbird:** in a narrow main Thunderbird window ensure the
   native Start toolbar control is discoverable or reachable through
   Thunderbird toolbar overflow. This native chrome is separate from
   `workspace.css`; record a defect if it is not reachable.
7. Verify keyboard Tab/Shift+Tab, browser zoom and dark/light themes.

## Gates

- `npm test`: unit/core/static checks, **not** a real UI acceptance result.
- Run the matrix in **real Thunderbird + installed XPI** before release.
- Existing CalDAV write → authoritative read-back and WordPress isolation
  tests still apply. Do not mark the change RELEASED/DONE solely on CI.
