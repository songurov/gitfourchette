# UX and visual guidelines

This document records where GitFourchette's current look comes from, which parts are conventions
worth keeping, which parts are traced values that should be replaced, and the rules a change to the
interface has to satisfy. It is for anyone touching `themes.py`, the stylesheets, a delegate, or a
pixel test. Every claim below was re-checked against the working tree at the version in
`gitfourchette/appconsts.py:16` (`APP_VERSION = "1.11.0"`), and the command behind each number is
given where the number appears.

Nothing here proposes a change to the product's name, its application icon, or its accent palette.
Those belong to upstream and are unchanged in this fork: `git show
upstream/master:gitfourchette/assets/icons/gitfourchette.png | cmp -
gitfourchette/assets/icons/gitfourchette.png` reports no difference. See
[rejected decisions](decisions-rejected.md) for why that stays true.

## Where the current look comes from

The default built-in look is the Neutral variant (`themes.py:63`, `DEFAULT_VARIANT =
ThemeVariant.Neutral`). Its dark colors are not derived from a rule; the code says where they came
from: *"The dark colors were measured on a reference screenshot"* (`themes.py:562`), and the tests
name the reference — `testNeutralFileRowsLookLikeForks` (`test/test_filecolumn.py:48`) and
*"Neutral's selection pill, measured on Fork"* (`test/test_sidebar.py:21`).

The important context is that all of this is local to this fork. Upstream's `themes.py` is 269
lines and contains no occurrence of "Neutral"; ours is 709. Upstream's `theme.qss` is 608 lines;
ours is 1108. `assets/icons/neutral/`, `test/test_filecolumn.py` and `test/test_theme_contrast.py`
do not exist upstream at all (`git ls-tree upstream/master -- <path>` returns nothing). Replacing a
traced value therefore costs nothing at rebase time and touches nothing upstream owns.

| Element | Anchor | What it is |
|---|---|---|
| Three panes: sidebar, graph, diff | `repowidget.py:119`, `:123` (`Split_Side`, `Split_Central`) | Category convention |
| Repo tabs | `toolbox/qtabwidget2.py` (828 lines; upstream's is 478) | Upstream's, extended here |
| Commit details in a tab beside its changes | `diffarea.py:79` | Good convention, keep |
| Permanent filter field in the sidebar | `test/test_sidebar.py:1010` | Good convention, keep |
| 26 distinct grays in the dark block | `themes.py:564-629`; light derived at `:631-690` | Traced from a screenshot |
| Folder blues `#3bb7e6` / `#1f9fd6` | `themes.py:620`, `:681` | Traced; carries no information |
| File rows: 16 px steps, 14 px icons, 10 px inset | `themes.py:597-599`, `filelists/filelist.py:269` | Traced rhythm |
| Selection pill inset 8 / 10, radius 6 | `sidebar/sidebardelegate.py:39-41` | Traced asymmetry |
| Pill tabs, radius 12 on a 14 px track | `themes.py:580-582` | Traced |
| File column 360 px, Unstaged/Staged 70/30 | `themes.py:601-602`, `diffarea.py:176` | Principle ours, numbers traced |
| No hover on file rows | `assets/style/theme.qss:870-872`, `:878-882` | An absence, copied |
| Second icon set, 10 files | `assets/icons/neutral/`, `themes.py:288`, `:618`, `:679` | Second icon language |
| macOS source list, centered toolbar | `themes.py:592`, `:595` | Mac client chrome |

Across source and tests, 21 places cite another client as the reason for a design decision. The raw
`grep -rn "Fork" gitfourchette/ test/ --include="*.py" --include="*.qss"` returns 64 lines; piping
it through `grep -viE "ForkLanguages|historyFork|Fork Point|git-flow, Fork|Fork and SourceTree"`
leaves 21. What that filter drops is the test helper `assertTranslatedInForkLanguages`, a local
variable, a fixture commit message, and the three interoperability references in `porcelain.py:769`,
`tasks/gitflowtasks.py:12` and `forms/gitflowinitdialog.py:75`, which are about `.git/config` and
must stay.

## What we keep

Category conventions, or our own work. Changing them would cost the user and differentiate nothing.

- The three-pane layout, repo tabs, commit details beside the changes, the permanent sidebar
  filter, Unstaged given more room than Staged.
- The contrast machinery. `themes.py:353-364` (`readableMix`) walks a mix down until it clears a
  stated ratio; `themes.py:383` and `:387` use it for `textDim` and `controlBorder`; and
  `test/test_theme_contrast.py:33-40` fails the build if any of the four built-in themes drops
  `controlBorder` below 3:1 (4.5:1 under a high-contrast system preference), `textDim` below 4.5:1,
  or `text` below 7:1, against both `bg` and `surface`.
- `SECONDARY_CONTRAST = 4.5` (`graphview/commitlogdelegate.py:91`) and the derivation that enforces
  it at paint time (`:164-193`): the palette's placeholder color is used only if it reads at 4.5:1
  on both plain and alternate rows, otherwise the dimmest mix of the text that does.
- The chip degradation budget (`commitlogdelegate.py:813-847`): ref chips give way before the
  commit message is cut below `MESSAGE_FLOOR_CHARS = 40` (`:131`), remotes first, then tags, then
  local branch names elided.
- Honoring the system contrast preference (`themes.py:162-168`, applied at `:453-454`).
- Deferring to the desktop. `application.py:169-173`: on KDE, when the boot style is better than
  Fusion, an empty `qtStyle` keeps the system style and the built-in theme is not applied.

## What we replace, and why

The replacing principle is one sentence: **a value belongs in `themes.py` only if it can be derived
from a stated rule or defended by a measurement of our own.** A value copied off another product's
screenshot satisfies neither, and it cannot be maintained — nobody can answer "why 21?".

- **The measured grays**: 26 distinct gray values in the dark block (`themes.py:564-629`), with the
  light block (`:631-690`) derived from them in the same ratios rather than measured (`:563`).
  Replace with values derived from a documented relationship between `bg`, `surface`, `altRow`,
  `border` and `text`. Token names stay, so nothing downstream changes.
- **The traced geometry**: pill inset 8/10 with radius 6 (`sidebardelegate.py:39-41`, in viewport
  coordinates; the comment at `:27-30` describes a 22 px pill about 10 px clear of either edge, and
  `test/test_sidebar.py:21-23` records the 9 px and 11 px it amounts to from the sidebar's edges),
  `SOURCE_LIST_INDENT = 7` and `SOURCE_LIST_MARGIN = 18` (`:31-32`), `SOURCE_LIST_CHEVRON_GAP = 21`
  (`:37`), the 16/14/10 file row rhythm (`themes.py:597-599`), `fileHeaderHeight = 30` (`:600`),
  `fileColumnWidth = 360` (`:601`), and `pillRadius = 12` on `tabTrackRadius = 14`
  (`themes.py:580-582`). A designed grid is symmetric and a multiple of its base step; a traced one
  has 7, 8, 10, 18 and 21 in it.
- **The folder blues** (`themes.py:620`, `:681`). A folder is not more blue than a file for any
  reason a user could name.
- **The hover suppression** (`theme.qss:878-882`, whose comment at `:872` gives the reason as the
  other product not having one). This is an absence that was copied, not a decision.
- **The second icon set** (`assets/icons/neutral/`, 10 SVGs, selected through `ThemeColors.iconSet`,
  `themes.py:288`, `:618`, `:679`, consumed at `application.py:694` and `toolbox/iconbank.py:142`).
  One icon language is enough. The wider set has no single stroke convention either:
  `grep -rho 'stroke-width="[^"]*"' gitfourchette/assets/icons/` returns 14 distinct values over
  176 SVGs, 155 of which are on a 16x16 viewBox. Settling on one is separate, cheap work.
- **The 21 in-code citations of another client as design authority.** Each is rewritten with our
  own reason or deleted. Until the tests are rewritten, the tracing still lives in the assertions.

## Design principles

Seven rules. Each has a threshold and a check, because a rule that cannot be tested is an adjective.

1. **Every color token carries a contrast floor that a test enforces.** Text at 4.5:1, titles at
   7:1, non-text marks at 3:1, against the surface they are drawn on. Theme tokens already comply
   (`test_theme_contrast.py:33-40`). Graph lanes do not: `getColor(laneID)` returns
   `rainbowBright[laneID % len(rainbowBright)]` (`graphview/graphpaint.py:35-36`) from a fixed list
   of 8 (`colors.py:33-35`) that no test covers. Measured with the repo's own formula
   (`toolbox/qtutils.py:407-423`) against the Neutral light surface `#ffffff` (`themes.py:634`):
   orange 2.44:1, yellow 1.70:1, lime 1.56:1, teal 1.97:1 — four of eight below 3:1. On the Neutral
   dark surface `#1c1c1c` (`themes.py:567`) all eight clear it, the lowest being purple at 3.06:1.
2. **Color carries information.** Every hue on screen maps to a meaning: lane identity, add or
   delete, ref kind, danger, selection. `folderColor` maps to nothing. The target for
   non-semantic hues is zero.
3. **Geometry is designed, not measured off a picture.** Spacing tokens are multiples of the base
   step, or carry a comment saying why not. `HOLLOW_RADIUS = 4` (`graphpaint.py:22-28`) is the
   model: its docstring argues from whole pixels at 1x and 2x — a reason, not a precedent.
4. **Every selectable row answers the pointer, and keyboard focus is drawn differently from
   selection.** Today `theme.qss:878-882` sets hover and selection backgrounds to transparent on
   `FileList`, and neither stylesheet contains a single `::item:focus` rule
   (`grep -n "::item:focus" gitfourchette/assets/style/*.qss` returns nothing). Focus is signalled
   only as an accent border on the whole view (`theme.qss:452-454`). A product that leans on
   keyboard navigation has to show where the keyboard is.
5. **Density beats white space, up to a ceiling.** A row is at most 1.30x the text line height. The
   traced look exceeds this and costs visible rows: `sidebarRowHeight = "1.5em"` (`themes.py:593`)
   and `fileRowHeight = "1.4em"` (`:596`) against the class defaults of `1.25em` (`:238`) and
   `1.15em` (`:248`), and against `base.qss:3-4`, which sets 1.2em and 1em. Any change that raises a
   row height carries a count of rows visible at a fixed window height.
6. **The platform decides the chrome; we decide the surfaces we paint.** Keep
   `application.py:169-173`. At most three tokens may vary by platform; everything else —
   typography, spacing, lane colors, states, icons — is identical everywhere. The surfaces that
   carry our identity are the ones we paint entirely: graph, diff, ref chips, status tiles.
7. **Anything the delegate paints must also be readable from the model.** See below; this is an
   accessibility rule, and it is currently violated in the one view that matters most.

## Accessibility and localization debt

Neither dimension had been measured before. The numbers below are current, each with the command
that produced it.

**Accessibility API coverage.** `grep -rn "setAccessibleName" gitfourchette/ | wc -l` returns 24;
`setAccessibleDescription` returns 3; `AccessibleTextRole`, `AccessibleDescriptionRole` and
`QAccessible` each return 0. The 27 calls live in six of 238 Python files — `diffarea.py` (14),
`prefsdialog.py` (5), `diffbuttons.py` (4), `mergeview/mergeeditor.py` (2), `aichatdialog.py` (1),
`toolbox/qhintbutton.py` (1). Toolbar buttons, the sidebar, the graph and the file lists have
none.

**The commit log is invisible to assistive technology.** `CommitLogModel.data` returns `None` for
`Qt.ItemDataRole.DisplayRole` (`graphview/commitlogmodel.py:111-112`), because `CommitLogDelegate`
paints every row itself. A client reading the view's model gets no text for any commit: not the
subject, not the author, not the hash. The model does answer `ToolTipRole` (`:145`), which
assistive technology does not read as content. `SidebarModel.data` (`sidebar/sidebarmodel.py:665`)
and `FileListModel.data` (`filelists/filelistmodel.py:239`) do return `DisplayRole` text, so those
two views are readable. Adding `AccessibleTextRole` to `CommitLogModel` is small work with a
disproportionate result, and it switches on Qt's native type-to-find as well.

**Right-to-left is declared out of scope, in code.** `application.py:433` forces the English locale
for any RTL system locale, with the comment that RTL support is not good enough and no RTL
translation exists. Only two files mention layout direction at all
(`grep -rnE "isRightToLeft|LayoutDirection|RightToLeft" gitfourchette/`). That is honest, and it
should stay documented as a limit rather than quietly implied otherwise.

**Menu tooltips.** `setToolTipsVisible(True)` appears in 10 places, including `mainwindow.py:285`
and `sidebar/sidebar.py:627`, so most menus do show their tooltips. `ActionDef.makeQMenu`
(`toolbox/actiondef.py:180-188`) does not call it, so context menus built through that helper build
tooltip text and discard it.

**Localization.** There are 14 catalogues under `gitfourchette/assets/lang/`. The current template
holds 2014 msgids (`grep -c "^msgid " gitfourchette/assets/lang/gitfourchette.pot` returns 2015,
including the header entry). This branch added 451 of them: upstream's template holds 1563. Only
three catalogues have been merged with the current template. Counting, for each language, how many
of the 2014 current msgids have a non-empty, non-fuzzy translation:

| Language | Usable | Falls back to English | Share |
|---|---:|---:|---:|
| ro, ru, tr | 2014 | 0 | 0.0% |
| fr | 1494 | 520 | 25.8% |
| cs, ko | 1458 | 556 | 27.6% |
| zh_Hans | 1098 | 916 | 45.5% |
| it | 804 | 1210 | 60.1% |
| es | 534 | 1480 | 73.5% |
| uk | 130 | 1884 | 93.5% |
| pt_BR | 18 | 1996 | 99.1% |
| pt | 16 | 1998 | 99.2% |
| zh_Hant | 8 | 2006 | 99.6% |
| de | 3 | 2011 | 99.9% |

Two facts hide behind the percentages. First, `wip.txt` reports `fr 100`, and `msgfmt --statistics`
agrees with "1565 translated messages" — but `fr.po` was never merged with the current template, so
520 of the template's msgids are absent from the catalogue entirely. The tracker measures against a
template that is out of date. Second, every UI change widens that gap: the `.pot` grows and 11 of
the 14 catalogues are not re-merged.

The rule that follows: **a change that adds user-visible strings re-runs the template extraction and
re-merges the catalogues in the same commit.** A catalogue that is merged and empty is honest; a
stale one reports a completion figure that is not true.

## Further reading

- [product vision](vision.md) — what the product is for.
- [architecture](architecture.md) — where the UI layers sit.
- [roadmap](roadmap.md) — planned work, with effort sizes.
- [rejected decisions](decisions-rejected.md) — ideas examined and turned down, with the evidence.
- [ADR 0001](adr/0001-desktop-stack.md) — the desktop stack decision.
