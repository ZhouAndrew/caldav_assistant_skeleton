# CalDAV Assistant Experimental

> **FROZEN v1.1 (2026-10-04).**
>
> Product boundary: `../FROZEN_PRODUCT_CONTRACT.md`
>
> Implementation/framework boundary: `../FROZEN_IMPLEMENTATION_CONTRACT.md`

Thunderbird-native CalDAV Assistant add-on for official Thunderbird 153.0.2 through
153.1.x.

## Work flow

There is **no Task Picker**.

Select exactly one Task in Thunderbird's native Tasks UI, then open/use CalDAV
Assistant Work.

```text
Thunderbird native Task selection
-> Start
-> Work
-> Stop | Complete | Cancel
```

If Thunderbird has no Task selected or multiple Tasks selected, CalDAV Assistant
shows guidance and does not present its own Task list/search/filter UI.

Pause, Resume and Switch Away are legacy migration/history only.

## Six pages

- **Work**
- **Today**
- **Record**
- **Logs**
- **WordPress**
- **Tools**

## Functional implementation

The canonical implementation is functional throughout:

```text
event
-> pure function
-> next state + effects
-> thin effect runner / adapter
-> verified result
-> pure state update
-> render
```

Domain/workflow/UI-state policy must not live in mutable controller objects or
side-effect adapters.

## Data ownership

- Thunderbird/CalDAV owns Task/Event facts.
- Assistant owns `currentWorkId` plus settings/audit/outbox.
- WordPress owns long-form/daily records.
- `caldavAssistant.runtime` is read-only legacy migration input.

## Reliability

Authoritative paths use:

```text
write -> read back -> compare -> receipt
```

Work VEVENT is history, not workflow truth. WordPress failure does not roll back a
verified Task transition.

## Release acceptance

A successful XPI build is not a release. Real Thunderbird acceptance must prove:

```text
native selection -> Start -> Work -> Stop/Complete/Cancel
```

A build that contains an Assistant Task Picker or requires duplicate Task selection
fails acceptance.
