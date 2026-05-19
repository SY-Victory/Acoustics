# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

This is an unpacked Power Apps Canvas App source (**BESA_OS Engineer V01 - Victory**) — a field engineer app for BESA (building envelope / acoustics testing). The `.msapp` file has been unpacked via the Power Platform CLI (`pac canvas unpack`). The app targets both browser and **offline mobile** (iOS/Android) via Dataverse offline sync.

## Source Layout

- `src/Src/*.fx.yaml` — Screen and control definitions (Power Fx formulas, UI properties). This is the primary code.
- `src/Src/Components/` — Reusable components (MainMenu, SettingsMenu, NotesPopup, OrderDetails).
- `src/Src/EditorState/` — Studio editor state JSON (control positions, selection state). Auto-generated.
- `src/Other/Src/*.pa.yaml` — Alternate unpacked format from `pac`. Read-only reference; cannot be pushed back.
- `src/DataSources/` — Dataverse table connection metadata (one JSON per table).
- `src/pkgs/TableDefinitions/` — Column schemas for each Dataverse table.
- `src/pkgs/PcfControlTemplates/` — PCF control definitions. Includes two custom controls: `SiteDataReadings` and `TestDetails` (StromaAcoustic namespace).
- `src/Other/Resources/Controls/` — Bundled JS/CSS for custom PCF controls.
- `src/CanvasManifest.json` — App metadata, feature flags, screen order.

## Screens (in order)

| Screen | Purpose |
|--------|---------|
| `Screen_EngineerHome` | Main screen — shift timeline, action list, navigation to all workflows |
| `Screen_EngineerAcoustic` / `_1` | Acoustic testing data entry (two related screens) |
| `Screen_EngineerHome_Zzz` | Legacy/dev screen — **IGNORE, do not read or modify** |
| `Screen_StartUpCollections` | Startup collection builder (unused) — **IGNORE, do not read or modify** |
| `Screen_EngineerRiskAssessment` | Risk assessment form |
| `scrRAMSSignOff` | RAMs sign-off workflow |
| `Screen_EngineerPermTest_V2_1` | Permeability test screen (air tightness testing) |
| `Screen2` | Dev/scratch screen |

## Dataverse Tables (all prefixed `BESA_`)

Key tables: `Shifts`, `Bookings`, `BookingElements`, `Orders`, `OrderServices`, `Tests`, `TestRuns`, `Envelopes`, `EnvelopeCatalogues`, `Elements`, `Sites`, `Clients`, `ClientContacts`, `EngineerLists`, `ReferencePoints`, `ReferencePointImages`, `Activities`, `SiteInductions`, `Documents`, `Equipments`, `SettingsGlobals`, `ServiceCatalogues`, `BookingServices`.

Navigation columns (lookup relationships) are the main source of complexity — e.g., `'Booking Element LookUp'.'Order Service LookUp'.'Service LookUp'.'Test Type'` chains.

## Offline Architecture (Critical)

The app uses Dataverse offline sync (SQLite on device). `App.OnStart` has two paths:

1. **Online** (`Connection.Connected = true`): Refreshes tables, builds `col_EngineerActionList` and `col_ShiftTimeline` from live Dataverse, flattens to `col_ShiftTimeline_Flat` (text-only fields), then `SaveData()` everything.
2. **Offline**: `LoadData()` restores cached collections. `col_ShiftTimeline` is rebuilt from the flat text cache.

The `_*` prefixed fields on `col_ShiftTimeline` (`_ClientName`, `_SiteGUID`, etc.) are the offline-safe text copies. UI controls should read from these, not from live lookup columns.

## Key Variables

- `varStaffViewBESAID` — Current engineer's BESA ID (GUID as text)
- `varActionRecord` — Currently selected test record for perm test screen
- `varOfflineMode` — Boolean, true when offline
- `varCurrentShiftID` — Active shift GUID
- `col_EngineerActionList` — Today's action items (services, inductions, RAMs, misc)
- `col_ShiftTimeline` — Merged shift + action rows for the timeline gallery
- `col_ShiftTimeline_Flat` — Offline-safe flattened version (text fields only)

## Canvas App Offline Debug

### CRITICAL: pa.yaml files are READ-ONLY

Canvas App `.pa.yaml` files can be **pulled (read)** to inspect the current formula state, but **cannot be pushed back** — there is no pac CLI path or MCP tool that writes back to the solution from a local pa.yaml.

**All fixes must be described as formula text the user pastes into Power Apps Studio.**

Never write or edit a pa.yaml file as a way to deliver a fix.

### How to approach a bug report

1. **Read the file first.** Check the current formula in the relevant pa.yaml before proposing anything.
2. **Cross-check against the confirmed findings below.** Most offline bugs map to a known anti-pattern.
3. **State which rule the formula violates**, not just "this won't work".
4. **Provide the exact replacement formula** the user should paste into Studio, with the property path (screen → control → property name).
5. **Verify your fix doesn't introduce a new anti-pattern** (e.g., don't add a standalone LookUp to fix a ForAll problem).

### The offline cache model

Canvas App on mobile = **SQLite local store** seeded by background sync. There are two query paths:

| Path | Trigger | Works offline? |
|------|---------|---------------|
| **SQLite** | Aggregate functions (`Concat`, `Sum`, `CountRows`), `ForAll` body `First(Filter(...))`, `ForAll` over Dataverse filter | Always |
| **OData** | Standalone `ClearCollect`, standalone `LookUp`, `Filter` as function argument | Fails for restricted tables; flaky for others |

Browser mode uses live OData, so a bug present on browser AND mobile is either:
- An OData issue (table permission), OR
- A formula logic error independent of the network path

### Table-by-table status

#### BESA_BookingElements
| Operation | Result |
|-----------|--------|
| `ClearCollect(col, BESA_BookingElements)` | OData → 0 rows always |
| `LookUp(BESA_BookingElements, Text(BESA_BookingElement) = var)` | OData → blank always |
| `CountRows(Filter(BESA_BookingElements, ...))` | SQLite works |
| `Concat(Filter(BESA_BookingElements, ...), ...)` | SQLite works |
| `First(Filter(BESA_BookingElements, Text(BESA_BookingElement) = buf.bePK))` inside ForAll body | SQLite works |

#### BESA_Envelopes
| Operation | Result |
|-----------|--------|
| `LookUp(BESA_Envelopes, ...)` standalone | OData → blank always |
| `First(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = buf.bePK))` in ForAll body | SQLite works |
| `Concat(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = bePK), Text('Floor Area'))` | SQLite works |

#### BESA_Tests
| Operation | Result |
|-----------|--------|
| `ClearCollect(col, FirstN(BESA_Tests, N))` | OData → 0 rows; also poisons collection name |
| `LookUp(BESA_Tests, BESA_Test = GUID(textVar))` | OData → blank / error |
| `LookUp(BESA_Tests, BESA_Test = guidVar)` | OData → blank |
| `Filter(BESA_Tests, Text(navCol.PK) = textVar)` standalone | OData → 0 |
| `Concat(Filter(BESA_Tests, ...), Text(BESA_Test) & ",")` | SQLite works |
| `First(Filter(BESA_Tests, Text(BESA_Test) = g.testGUID))` in ForAll body | SQLite works |

#### BESA_Shifts
| Operation | Result |
|-----------|--------|
| `Filter(BESA_Shifts, 'User GUID' = x)` OData | Non-deterministically flaky (0 or correct) |
| `Filter(BESA_Shifts, 'Shift Date' >= d, ...)` OData | Flaky |
| `Filter(BESA_Shifts, Adhoc = true)` OData | Boolean column OData is reliable |
| `Concat(Filter(BESA_Shifts, 'User GUID' = x, 'Shift Date' >= d, ...), ...)` | SQLite works |
| `First(Filter(BESA_Shifts, Text(BESA_Shift) = textGUID))` in ForAll body | SQLite works |

#### BESA_TestRuns
| Operation | Result |
|-----------|--------|
| `ClearCollect(col, Filter(BESA_TestRuns, ...))` | Works (OData allowed) |

### Confirmed anti-patterns (hard rules)

#### 1. `Collect(col, rec)` — CONFIRMED FAILING
Collecting a full Dataverse record from a ForAll body silently produces 0 rows.

```powerapps
// WRONG — 0 rows, no error:
ForAll(Filter(BESA_Tests, ...) As rec,
    Collect(col_TestResult, rec)
);

// WRONG — explicit native type extraction also 0 rows when source is Dataverse ForAll:
ForAll(Filter(BESA_Shifts, ...) As s,
    Collect(col, {BESA_Shift: s.BESA_Shift, 'Booking LookUp': s.'Booking LookUp'})
);

// CORRECT — explicit text-safe extraction via local-collection ForAll:
ClearCollect(col_TestLookupBuf, {testGUID: var_savedTestGUID});
ForAll(col_TestLookupBuf As g,
    With({rec: First(Filter(BESA_Tests, Text(BESA_Test) = g.testGUID))},
        If(!IsBlank(rec),
            With({envRec: rec.'Envelope LookUp', beRec: rec.'Booking Element LookUp'},
                Collect(col_ExistingTestResult, {
                    BESA_Test:                GUID(Text(rec.BESA_Test)),
                    'Test Status':            Text(rec.'Test Status'),
                    'Section Status':         Text(rec.'Section Status'),
                    'Test Info':              Text(rec.'Test Info'),
                    'Envelope LookUp':        envRec,
                    'Booking Element LookUp': beRec
                })
            )
        )
    )
);
Set(varExistingTest, First(col_ExistingTestResult));
```

Notes:
- `GUID(Text(rec.BESA_Test))` — must convert via Text then back; `rec.BESA_Test` directly doesn't survive
- Nav col refs obtained via `With({envRec: rec.'Envelope LookUp'})` survive in the Collect
- `Set()` is NOT allowed inside ForAll — always use `Collect()` + `Set(var, First(col))` after

#### 2. No `Set()` or `IfError()` inside ForAll
Both are silently ignored or cause incorrect behaviour inside a ForAll body.

```powerapps
// WRONG:
ForAll(col As row, Set(myVar, row.value));
ForAll(col As row, IfError(Collect(...), ...));

// CORRECT:
ForAll(col As row, Collect(col_buf, {val: row.value}));
Set(myVar, First(col_buf).val);
If(!IsBlank(rec), Collect(...));   // instead of IfError
```

#### 3. ForAll over Dataverse — simple body only (Step 1)
When iterating directly over a Dataverse Filter, the body must be a single `If(condition, Collect(col, {textFields}))`. Complex bodies (With, nested ForAll, multiple Collects) silently produce 0 results from the ENTIRE body, including lines before the complex expression.

```powerapps
// WRONG — 0 rows even for the first Collect:
ForAll(Filter(BESA_Shifts, ...) As s,
    Collect(col_simple, {guid: Text(s.BESA_Shift)});     // this ALSO gets 0 rows
    With({booking: s.'Booking LookUp'}, Collect(col_full, {...}))
);

// CORRECT — Step 1: simple body, text fields only:
ForAll(Filter(BESA_Shifts, ...) As s,
    If(condition,
        Collect(col_GUIDList, {ShiftGUIDStr: Text(s.BESA_Shift)})
    )
);
// Step 2: ForAll over local collection → full body OK (With, nested ForAll, Filter, Patch all work):
ForAll(col_GUIDList As row,
    With({shiftRec: First(Filter(BESA_Shifts, Text(BESA_Shift) = row.ShiftGUIDStr))},
        // full logic here
    )
);
```

#### 4. Standalone LookUp by PK — always fails on mobile
`GUID()` inside a LookUp predicate at runtime produces an error. Even without GUID(), variable predicates generate OData $filter queries which fail for restricted tables.

```powerapps
// ALL WRONG on mobile:
LookUp(BESA_Tests, BESA_Test = GUID(textVar))
LookUp(BESA_BookingElements, BESA_BookingElement = GUID(textVar))
LookUp(BESA_Shifts, BESA_Shift = GUID(textGUID))

// CORRECT — ForAll over local 1-row buffer:
ClearCollect(col_buf, {pk: textVar});
ForAll(col_buf As g,
    With({rec: First(Filter(Table, Text(PK_Col) = g.pk))},
        If(!IsBlank(rec), Collect(col_result, {field: Text(rec.field)}))
    )
);
Set(myVar, First(col_result));
```

#### 5. ParseJSON without Coalesce — crashes with Kind:23
`ParseJSON(blank)` = `ConnectedDataQueryStringBuilderError`. Any field that could be blank must be guarded.

```powerapps
// WRONG:
Set(varSectionStatus, ParseJSON(varActionRecord.'Section Status'));

// CORRECT:
Set(varSectionStatus, ParseJSON(Coalesce(varActionRecord.'Section Status', "{}")));
Set(varTestInfo,      ParseJSON(Coalesce(varActionRecord.'Test Info', "{}")));
```

#### 6. SQLite null semantics differ from Power Apps boolean semantics
Non-adhoc shifts have `null` Adhoc in Dataverse. In Power Apps formula UI: coerced to `false` (displays as "No"). In SQLite ForAll: raw null. `NOT null = null` (falsy) → row silently excluded.

```powerapps
// WRONG — NOT null = null in SQLite → non-adhoc rows excluded:
If(Not(shiftRow.Adhoc) && ..., ...)

// CORRECT — IsBlank() translates to IS NULL in SQLite:
If((IsBlank(shiftRow.Adhoc) || shiftRow.Adhoc = false) && ..., ...)
```

#### 7. AddColumns around Dataverse Filter — breaks OData delegation
```powerapps
// WRONG — 0 rows:
ClearCollect(col, AddColumns(Filter(BESA_Shifts, ...), newCol, Text(BESA_Shift)));

// CORRECT — AddColumns on local collection only:
ClearCollect(col, Filter(BESA_Shifts, ...));
ClearCollect(col_withExtra, AddColumns(col, newCol, Text(BESA_Shift)));
```

#### 8. Refresh before ClearCollect — race condition
`Refresh(Table)` is async. OData ClearCollects within ~2s return 0 rows while SQLite rebuilds.
Remove all `Refresh(BESA_*)` from action-list build buttons — background sync keeps SQLite current.

### Confirmed working patterns

#### Patch inside ForAll body — CONFIRMED WORKING (2026-05-14)
Live record refs from `First(Filter(...))` inside ForAll body are valid as Patch lookup field values.

```powerapps
ClearCollect(col_TestPatchBuf, {bePK: ThisItem.bePKText, shiftGUID: varCurrentShiftID});
Clear(col_TestPatchResult);
ForAll(col_TestPatchBuf As buf,
    With({
        beRec:    First(Filter(BESA_BookingElements, Text(BESA_BookingElement) = buf.bePK)),
        shiftRec: First(Filter(BESA_Shifts, Text(BESA_Shift) = buf.shiftGUID))
    },
        If(!IsBlank(beRec),
            With({envRec: First(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = buf.bePK))},
                Collect(col_TestPatchResult,
                    Patch(BESA_Tests, Defaults(BESA_Tests), {
                        'Booking Element LookUp': beRec,
                        'Envelope LookUp':        envRec,
                        'Shift LookUp':           shiftRec
                    })
                )
            )
        )
    )
);
Set(var_newTestPatchRec, First(col_TestPatchResult));
```

Notes:
- `ThisItem` from outer gallery button IS accessible inside the ForAll body
- `Set()` still not allowed inside ForAll — use `Set(var, First(col))` after

#### Concat aggregate for nav col sub-fields — CONFIRMED WORKING
Two-hop nav col access (`'Booking Service Lookup'.'Service Name'`) works via Concat aggregate.
Use this when `varActionRecord.'Nav LookUp'.'Sub Field'` is blank.

```powerapps
// Site contact (2-hop nav col via BESA_Sites):
Set(varPermTestContactName, Concat(
    Filter(BESA_Sites, Text(BESA_Site) = var_siteGUIDForPermTest),
    Text('Site Contact LookUp'.'Contact Name')
));

// Envelope data from BESA_Envelopes (nav col comparison):
With({bePK: ThisItem.bePKText},
    Set(varEnvelopeType,  Concat(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = bePK), Text('Envelope Type')));
    Set(varNetFloorArea,  Value(Concat(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = bePK), Text('Floor Area'))));
    Set(varEnvelopeArea,  Value(Concat(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = bePK), Text('Envelope Area'))));
    Set(varVolume,        Value(Concat(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = bePK), Text(Volume))));
    Set(varNoStoreys,     Value(Concat(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = bePK), Text('Floor Quantity'))));
    Set(varMaxHeight,     Value(Concat(Filter(BESA_Envelopes, Text('Booking Element LookUp'.BESA_BookingElement) = bePK), Text('Maximum Height'))))
);
```

#### Blank screen diagnosis — gallery Items
If any gallery has `Items: =varActionRecord` and varActionRecord is blank, **all tabs on the screen go blank** — the gallery has 0 rows, so every container inside it is invisible. This is always the root cause of a completely blank perm test screen.

Check:
1. Is `varActionRecord` set before Navigate?
2. Is the action button's ForAll pattern correctly setting `varActionRecord`?
3. Did a `LookUp(BESA_Tests, ...)` after Patch overwrite `varActionRecord` with blank?

### Engineer app — known regression points

#### `btnEngineerAction` OnSelect (Screen_EngineerHome.pa.yaml)
Block 5 (new test path): Uses `Patch inside ForAll body` pattern. After Patch, re-fetches via ForAll with explicit extraction. `Set(varActionRecord, Coalesce(First(col_ExistingTestResult), var_newTestPatchRec))`.

Block 4 (existing test path): Uses ForAll over `col_TestLookupBuf` with explicit field extraction. `Set(varExistingTest, First(col_ExistingTestResult))`.

ParseJSON guards: `Coalesce(varActionRecord.'Section Status', "{}")` and `Coalesce(varActionRecord.'Test Info', "{}")`.

Site contact: `Concat(Filter(BESA_Sites, Text(BESA_Site) = var_siteGUIDForPermTest), Text('Site Contact LookUp'.'Contact Name'))`.

Envelope vars: `With({bePK: ThisItem.bePKText}, Set(varNetFloorArea, Value(Concat(Filter(BESA_Envelopes, ...)))))` before Navigate.

#### Save buttons on Screen_EngineerPermTest (KNOWN OPEN ISSUE)
Multiple `Set(varActionRecord, LookUp(BESA_Tests, BESA_Test = varActionRecord.BESA_Test))` calls in OnSelect handlers. These always return blank on mobile → wipe varActionRecord → subsequent ParseJSON crashes on unguarded `'Section Status'` field. Needs replacement with ForAll pattern.

### Rules of thumb summary

| Rule | Reason |
|------|--------|
| No standalone `LookUp` by PK on any table | GUID() errors on mobile; variable predicate = OData = fails for restricted tables |
| No standalone `ClearCollect` on BESA_BookingElements or BESA_Tests | OData always 0 for these |
| No `Collect(col, rec)` for full Dataverse record | Silently 0 rows; use explicit field extraction |
| No complex body in ForAll over Dataverse table | Use two-step: Step 1 = text-only Collect; Step 2 = ForAll over local collection |
| No `Set()` or `IfError()` inside ForAll | Use `Collect` + `Set(var, First(col))` after |
| Always `Coalesce(field, "{}")` before `ParseJSON` | `ParseJSON(blank)` = Kind:23 crash |
| Use `Concat` aggregate for nav col sub-fields | Direct `varRecord.'LookUp'.'SubField'` unreliable from collected records |
| `Patch` inside ForAll body is valid | Live SQLite refs from `First(Filter(...))` are valid lookup values |
| `IsBlank()` not `Not()` for nullable booleans in SQLite | `NOT null = null` silently excludes rows |
| Remove `Refresh(Table)` before any ClearCollect on same table | Async race → 0 rows |
| Nav col comparison in Filter: `Text('LookUp'.PK_Col) = textVar` | Not `'LookUp' = record`; record comparison is a compile error |
