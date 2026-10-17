# Thunderbird Post Preview 0.4.6 — real acceptance

The 0.4.5 screenshot demonstrated a correct WordPress Post loaded at its top
but the privileged iframe scroll failed with the generic "An unexpected error occurred".

In isolated real Thunderbird 153.1.0 ESR + real WordPress 7.1.3:
- The prior implementation failed to reach the end of the Post.
- The explicit privileged API error was `find-post-frame: ReferenceError: URL is not defined`.
- The native `nsIURI` fix passed real plugin installation, independent WordPress Post read,
  scrolling to the *Post body's last element* (approximately 477–478 pixels from a
  480-pixel iframe viewport), and text/image/file Quick Capture regression checks.
- The native Task workflow and `currentWorkId` remain unchanged.

Grounded acceptance run (pre-version-bump source):
https://github.com/ZhouAndrew/caldav_assistant_skeleton/actions/runs/38993092672

This is a real automated Thunderbird test in an isolated runner. It is not a claim
of installation or acceptance inside the user's local Thunderbird profile.
The exact new 0.4.6 XPI build and source digest are provided at the
`thunderbird-v0.4.6-test.1` release after publishing. The 0.4.2 stable package
and its accepted identity remain unchanged.
