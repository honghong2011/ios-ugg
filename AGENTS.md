# Working on ios-ugg (fork of ios-sweet)

- **Start here: `E:\ios-ugg\HANDOFF.md`** - the workspace-level handoff: the goal,
  every directory in `E:\ios-ugg`, current state, operating commands and the known
  traps. Then read `NOTES-UGG.md` in this repo (our log; its top section is the
  active handoff). `NOTES.md` is the *upstream sweet* log - good for methodology,
  not for ugg's state.
- **Write your own handoff doc** as `E:\ios-ugg\HANDOFF-<date>.md`: everything you
  did (commits, CI run IDs, exact boot results, what you changed and why, what is
  unfinished, facts vs guesses). Keep the active handoff at the top of
  `NOTES-UGG.md` current too. The user hands this project between agents often.
- The user switches agents frequently. Update the active handoff in `NOTES.md`
  after each milestone and before stopping. Record commits, CI run IDs, exact
  build/boot results and unfinished work. Distinguish observations from guesses.
- Commit completed changes. Use `gh` for GitHub Actions kernel builds and logs.
  Local single-file cross-compiles are useful before spending a CI run.
- Device bring-up uses temporary `fastboot boot` images; nothing gets flashed.
  **On ugg the `data`/`userdata` partition is read-only and must not be touched**
  (see the workspace README). The 2026-10-15 approval quoted below applies to
  *sweet*, the upstream phone, not to ugg. Keep bootloaders, recovery, modem,
  persist and the backups intact, and confirm every destructive step with the
  user before running it.
- Keep device dumps, serial numbers and downloaded Apple artifacts out of git.
